import logging
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from database import get_db
from models import (
    GrainLot,
    ShiftActionLog,
    DryerFacility,
    StorageStack,
    LotStatus,
    SettlementStatus,
    AlertSeverity,
    EntityType,
    StackStatus,
)
from schemas import (
    GrainLotCreate,
    GrainLotResponse,
    GrainLotTriageUpdate,
    SettlementResponse,
    DryerFacilityResponse,
    CapacityStressTestResponse,
    StorageStackResponse,
    TelemetryIngestRequest,
    TelemetryIngestResponse,
    DMLMetricsResponse,
    ShiftActionLogResponse,
)
from services import (
    create_grain_lot,
    process_stack_telemetry,
    compute_dml_metrics,
    perform_capacity_stress_test,
)

logger = logging.getLogger("grainflow.api")

lots_router = APIRouter(prefix="/lots", tags=["Grain Lots & Farmgate Intake"])
capacity_router = APIRouter(prefix="/capacity", tags=["Dryer Load Balancing & Cohorts"])
storage_router = APIRouter(prefix="/storage", tags=["Storage Stack IoT Telemetry"])
logs_router = APIRouter(prefix="/logs", tags=["Action Logs & Emergency Triggers"])


# ==============================================================================
# 1. Grain Lots & Farmgate Intake Router (/api/v1/lots)
# ==============================================================================

@lots_router.post(
    "/",
    response_model=GrainLotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest new harvest intake",
    description="Calculates SLA deadline (harvest + 36h), assesses aflatoxin risk level, and generates initial digital settlement amount."
)
def ingest_grain_lot(lot_in: GrainLotCreate, db: Session = Depends(get_db)):
    try:
        lot = create_grain_lot(
            db=db,
            lot_id=lot_in.id,
            cluster_id=lot_in.cluster_id,
            gapoktan_name=lot_in.gapoktan_name,
            farmer_name=lot_in.farmer_name,
            farmer_phone=lot_in.farmer_phone,
            gross_weight_kg=lot_in.gross_weight_kg,
            moisture_pct=lot_in.moisture_pct,
            damaged_kernels_pct=lot_in.damaged_kernels_pct,
            base_price_per_kg=lot_in.base_price_per_kg,
            quality_premium_per_kg=lot_in.quality_premium_per_kg,
            harvest_timestamp=lot_in.harvest_timestamp,
        )
        return lot
    except Exception as exc:
        db.rollback()
        logger.error("Failed to ingest grain lot: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to ingest grain lot: {str(exc)}"
        )


@lots_router.get(
    "/",
    response_model=List[GrainLotResponse],
    summary="List grain lots",
    description="Retrieve all lots with optional filtering for status, cluster_id, and critical SLA urgency (<12h remaining)."
)
def list_grain_lots(
    status_filter: Optional[LotStatus] = Query(None, alias="status", description="Filter by intake status"),
    cluster_id: Optional[str] = Query(None, description="Filter by regional cluster (e.g. GROBOGAN-01)"),
    sla_urgency: Optional[str] = Query(None, description="Set 'critical_under_12h' to filter lots near expiration"),
    db: Session = Depends(get_db),
):
    stmt = select(GrainLot)
    conditions = []

    if status_filter:
        conditions.append(GrainLot.status == status_filter)
    if cluster_id:
        conditions.append(GrainLot.cluster_id == cluster_id)

    if conditions:
        stmt = stmt.where(and_(*conditions))

    stmt = stmt.order_by(GrainLot.created_at.desc())
    results = db.scalars(stmt).all()

    # Filter critical_under_12h dynamically
    if sla_urgency == "critical_under_12h":
        results = [l for l in results if l.sla_hours_remaining <= 12.0 and l.status in (LotStatus.PENDING_TRIAGE, LotStatus.DISPATCHED_TO_DRYER)]

    return results


@lots_router.get(
    "/{lot_id}",
    response_model=GrainLotResponse,
    summary="Get lot details by ID"
)
def get_grain_lot(lot_id: str, db: Session = Depends(get_db)):
    lot = db.scalar(select(GrainLot).where(GrainLot.id == lot_id))
    if not lot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Lot {lot_id} not found.")
    return lot


@lots_router.patch(
    "/{lot_id}/triage",
    response_model=GrainLotResponse,
    summary="Triage lot status & assign dryer",
    description="Dispatches lot to a designated dryer hub, marks as drying in progress, or certifies as factory grade."
)
def triage_grain_lot(lot_id: str, triage_in: GrainLotTriageUpdate, db: Session = Depends(get_db)):
    lot = db.scalar(select(GrainLot).where(GrainLot.id == lot_id))
    if not lot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Lot {lot_id} not found.")

    old_status = lot.status
    lot.status = triage_in.status
    if triage_in.assigned_dryer_id:
        lot.assigned_dryer_id = triage_in.assigned_dryer_id

    # If dispatched to dryer, adjust dryer load
    if triage_in.assigned_dryer_id and triage_in.status in (LotStatus.DISPATCHED_TO_DRYER, LotStatus.DRYING_IN_PROGRESS):
        dryer = db.scalar(select(DryerFacility).where(DryerFacility.id == triage_in.assigned_dryer_id))
        if dryer:
            lot_tonnage = lot.gross_weight_kg / 1000.0
            dryer.current_load_tons = round(dryer.current_load_tons + lot_tonnage, 2)

    # Log action
    log = ShiftActionLog(
        entity_type=EntityType.GRAIN_LOT,
        entity_id=lot_id,
        alert_severity=AlertSeverity.INFO,
        trigger_reason=f"Triage status update from {old_status.value} to {triage_in.status.value}",
        action_taken=f"Status changed to {triage_in.status.value}. Assigned dryer: {lot.assigned_dryer_id or 'N/A'}. {triage_in.notes or ''}".strip(),
        operator_user=triage_in.operator_user or "PPL_OFFICER",
    )
    db.add(log)
    db.commit()
    db.refresh(lot)
    return lot


@lots_router.post(
    "/{lot_id}/settle",
    response_model=SettlementResponse,
    summary="Execute instant digital scale payout",
    description="Disburses payout directly to farmer account upon certified weighbridge intake, achieving 0-day DSO."
)
def settle_farmer_payout(lot_id: str, db: Session = Depends(get_db)):
    lot = db.scalar(select(GrainLot).where(GrainLot.id == lot_id))
    if not lot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Lot {lot_id} not found.")

    if lot.settlement_status == SettlementStatus.DISBURSED:
        return SettlementResponse(
            lot_id=lot.id,
            settlement_status=lot.settlement_status,
            net_payout_amount=lot.net_payout_amount,
            settlement_disbursed_at=lot.settlement_disbursed_at or datetime.now(timezone.utc),
            dso_days=0.0,
            message="Settlement already disbursed previously.",
        )

    now = datetime.now(timezone.utc)
    lot.settlement_status = SettlementStatus.DISBURSED
    lot.settlement_disbursed_at = now

    # Record payout audit trail
    log = ShiftActionLog(
        entity_type=EntityType.GRAIN_LOT,
        entity_id=lot_id,
        alert_severity=AlertSeverity.INFO,
        trigger_reason="Instant Farmgate Digital Scale Settlement Executed",
        action_taken=(
            f"Transferred Rp {lot.net_payout_amount:,.2f} to farmer {lot.farmer_name} ({lot.farmer_phone}) "
            f"via automated digital treasury gateway. DSO: 0.0 days."
        ),
        operator_user="TREASURY_GATEWAY",
    )
    db.add(log)
    db.commit()
    db.refresh(lot)

    return SettlementResponse(
        lot_id=lot.id,
        settlement_status=lot.settlement_status,
        net_payout_amount=lot.net_payout_amount,
        settlement_disbursed_at=now,
        dso_days=0.0,
        message=f"Successfully disbursed Rp {lot.net_payout_amount:,.2f} with 0-day DSO.",
    )


# ==============================================================================
# 2. Dryer Capacity Balancing & Cohorts Router (/api/v1/capacity)
# ==============================================================================

@capacity_router.get(
    "/dryers",
    response_model=List[DryerFacilityResponse],
    summary="List partner dryer facilities",
    description="Retrieve all rented/partner BUMDes and commercial dryers with active load and rated daily capacity."
)
def list_dryers(cluster_id: Optional[str] = None, db: Session = Depends(get_db)):
    stmt = select(DryerFacility)
    if cluster_id:
        stmt = stmt.where(DryerFacility.cluster_id == cluster_id)
    dryers = db.scalars(stmt).all()

    response = []
    for d in dryers:
        util = round((d.current_load_tons / d.daily_rated_capacity_tons) * 100.0, 1) if d.daily_rated_capacity_tons > 0 else 0.0
        item = DryerFacilityResponse.model_validate(d)
        item.utilization_pct = util
        response.append(item)
    return response


@capacity_router.get(
    "/stress-test",
    response_model=CapacityStressTestResponse,
    summary="Check 14-day harvest forecast volume vs dryer throughput",
    description="Evaluates regional cluster capacity. Returns STRESSED if load exceeds 85%, recommending cohort schedule offsets (+7 to +10 days)."
)
def capacity_stress_test(
    forecast_days: int = Query(14, ge=1, le=60, description="Forecast horizon in days"),
    forecast_daily_harvest_tons: float = Query(65.0, gt=0, description="Expected daily intake tonnage"),
    db: Session = Depends(get_db),
):
    result = perform_capacity_stress_test(
        db=db,
        forecast_days=forecast_days,
        forecast_daily_harvest_tons=forecast_daily_harvest_tons,
    )
    return result


# ==============================================================================
# 3. Storage Stack IoT Telemetry Router (/api/v1/storage)
# ==============================================================================

@storage_router.post(
    "/telemetry",
    response_model=TelemetryIngestResponse,
    summary="Ingest multi-point IoT probe telemetry",
    description="Updates stack temperature and RH. If temp > 35°C, slope > 0.5°C/h, or RH > 70%, triggers CRITICAL_HEAT_SPIKE."
)
def ingest_telemetry(payload: TelemetryIngestRequest, db: Session = Depends(get_db)):
    stack, alert_triggered, msg = process_stack_telemetry(
        db=db,
        stack_code=payload.stack_code,
        temperature_c=payload.temperature_c,
        humidity_rh_pct=payload.humidity_rh_pct,
        temp_slope_1h=payload.temp_slope_1h,
    )
    return TelemetryIngestResponse(
        stack_code=stack.stack_code,
        status=stack.status,
        temperature_c=stack.temperature_c,
        humidity_rh_pct=stack.humidity_rh_pct,
        temp_slope_1h=stack.temp_slope_1h,
        alert_triggered=alert_triggered,
        message=msg,
    )


@storage_router.get(
    "/stacks",
    response_model=List[StorageStackResponse],
    summary="List all warehouse storage stacks",
    description="Retrieve status of all rented warehouse bag-stacks instrumented with multi-point probe sensors."
)
def list_stacks(warehouse_id: Optional[str] = None, db: Session = Depends(get_db)):
    stmt = select(StorageStack)
    if warehouse_id:
        stmt = stmt.where(StorageStack.warehouse_id == warehouse_id)
    stacks = db.scalars(stmt).all()
    return stacks


@storage_router.get(
    "/dml-metrics",
    response_model=DMLMetricsResponse,
    summary="Dry Matter Loss (DML) suppression performance",
    description="Compares estimated DML against the traditional 3.2% tropical unmonitored baseline, reporting tons and IDR saved."
)
def get_dml_metrics(db: Session = Depends(get_db)):
    return compute_dml_metrics(db)


# ==============================================================================
# 4. Action Logs & Emergency Triggers Router (/api/v1/logs)
# ==============================================================================

@logs_router.get(
    "/",
    response_model=List[ShiftActionLogResponse],
    summary="List audit action logs",
    description="Retrieve recent shift logs and automated dispatch records with optional severity and entity filtering."
)
def list_action_logs(
    severity: Optional[AlertSeverity] = Query(None, description="Filter by alert severity (INFO, WARNING, CRITICAL)"),
    entity_id: Optional[str] = Query(None, description="Filter by lot or stack id"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    stmt = select(ShiftActionLog)
    conditions = []
    if severity:
        conditions.append(ShiftActionLog.alert_severity == severity)
    if entity_id:
        conditions.append(ShiftActionLog.entity_id == entity_id)
    if conditions:
        stmt = stmt.where(and_(*conditions))

    stmt = stmt.order_by(ShiftActionLog.created_at.desc()).limit(limit)
    return db.scalars(stmt).all()


@logs_router.post(
    "/{log_id}/acknowledge",
    response_model=ShiftActionLogResponse,
    summary="Acknowledge alert action",
    description="Marks an alert or emergency trigger as acknowledged/completed by field or warehouse personnel."
)
def acknowledge_log(log_id: int, db: Session = Depends(get_db)):
    log = db.scalar(select(ShiftActionLog).where(ShiftActionLog.id == log_id))
    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Log ID {log_id} not found.")

    log.acknowledged = True
    log.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(log)
    return log

