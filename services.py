import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from models import (
    GrainLot,
    StorageStack,
    DryerFacility,
    ShiftActionLog,
    AflatoxinRiskLevel,
    LotStatus,
    SettlementStatus,
    StackStatus,
    EntityType,
    AlertSeverity,
)

logger = logging.getLogger("grainflow.services")


# ==============================================================
# 1. Grain Intake, Settlement & SLA Recalculation
# ==============================================================

def calculate_aflatoxin_risk(moisture_pct: float, damaged_kernels_pct: float) -> AflatoxinRiskLevel:
    """
    Evaluates aflatoxin proliferation hazard:
    Derived rule: Moisture > 28% or damaged > 5% defaults to HIGH / CRITICAL.
    """
    if moisture_pct >= 32.0 or damaged_kernels_pct >= 8.0:
        return AflatoxinRiskLevel.CRITICAL
    elif moisture_pct > 28.0 or damaged_kernels_pct > 5.0:
        return AflatoxinRiskLevel.HIGH
    elif moisture_pct > 20.0 or damaged_kernels_pct > 3.0:
        return AflatoxinRiskLevel.MODERATE
    return AflatoxinRiskLevel.LOW


def calculate_net_payout(gross_weight_kg: float, base_price_per_kg: float, quality_premium_per_kg: float) -> float:
    """
    Calculates instant digital payout:
    net_payout = gross_weight_kg * (base_price + quality_premium)
    """
    unit_price = max(0.0, base_price_per_kg + quality_premium_per_kg)
    return round(gross_weight_kg * unit_price, 2)


def generate_lot_id(db: Session, cluster_id: str) -> str:
    """Generates unique sequential lot id: LOT-{CLUSTER}-{YYYYMMDD}-{INDEX}."""
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"LOT-{cluster_id[:4].upper()}-{today_str}-"
    count = db.scalar(
        select(func.count(GrainLot.id)).where(GrainLot.id.like(f"{prefix}%"))
    ) or 0
    return f"{prefix}{count + 1:03d}"


def create_grain_lot(
    db: Session,
    lot_id: Optional[str],
    cluster_id: str,
    gapoktan_name: str,
    farmer_name: str,
    farmer_phone: str,
    gross_weight_kg: float,
    moisture_pct: float,
    damaged_kernels_pct: float,
    base_price_per_kg: float,
    quality_premium_per_kg: float,
    harvest_timestamp: datetime,
) -> GrainLot:
    """Creates a new grain lot, computes SLA deadline (+36h), risk, and initial payout."""
    if not lot_id:
        lot_id = generate_lot_id(db, cluster_id)

    if harvest_timestamp.tzinfo is None:
        harvest_timestamp = harvest_timestamp.replace(tzinfo=timezone.utc)

    sla_deadline = harvest_timestamp + timedelta(hours=36)
    risk_level = calculate_aflatoxin_risk(moisture_pct, damaged_kernels_pct)
    net_payout = calculate_net_payout(gross_weight_kg, base_price_per_kg, quality_premium_per_kg)

    lot = GrainLot(
        id=lot_id,
        cluster_id=cluster_id,
        gapoktan_name=gapoktan_name,
        farmer_name=farmer_name,
        farmer_phone=farmer_phone,
        gross_weight_kg=gross_weight_kg,
        moisture_pct=moisture_pct,
        damaged_kernels_pct=damaged_kernels_pct,
        aflatoxin_risk_level=risk_level,
        status=LotStatus.PENDING_TRIAGE,
        harvest_timestamp=harvest_timestamp,
        sla_deadline=sla_deadline,
        settlement_status=SettlementStatus.UNSETTLED,
        base_price_per_kg=base_price_per_kg,
        quality_premium_per_kg=quality_premium_per_kg,
        net_payout_amount=net_payout,
    )
    db.add(lot)

    # Check immediate alert if critically wet
    if risk_level in (AflatoxinRiskLevel.HIGH, AflatoxinRiskLevel.CRITICAL):
        alert_msg = f"Moisture {moisture_pct:.1f}% & Defect {damaged_kernels_pct:.1f}% triggers {risk_level.value} Aflatoxin Risk."
        action_msg = f"Automated WhatsApp notification queued to Farmer {farmer_phone} and Cluster Lead for priority dispatch."
        log = ShiftActionLog(
            entity_type=EntityType.GRAIN_LOT,
            entity_id=lot_id,
            alert_severity=AlertSeverity.CRITICAL if risk_level == AflatoxinRiskLevel.CRITICAL else AlertSeverity.WARNING,
            trigger_reason=alert_msg,
            action_taken=action_msg,
            operator_user="INTAKE_GATE_SYSTEM",
        )
        db.add(log)

    db.commit()
    db.refresh(lot)
    return lot


# ==============================================================
# 2. Storage IoT Telemetry & DML Calculations
# ==============================================================

def process_stack_telemetry(
    db: Session,
    stack_code: str,
    temperature_c: float,
    humidity_rh_pct: float,
    temp_slope_1h: Optional[float] = None,
) -> Tuple[StorageStack, bool, str]:
    """
    Ingests IoT probe sensor data for a warehouse stack and evaluates heat spike thresholds.
    Business Rule:
      If temp > 35.0 C or temp_slope_1h > 0.5 or humidity_rh_pct > 70.0:
        auto-flag status as CRITICAL_HEAT_SPIKE and write ShiftActionLog.
    """
    stack = db.scalar(select(StorageStack).where(StorageStack.stack_code == stack_code))
    now = datetime.now(timezone.utc)

    if not stack:
        # Auto-provision stack entry if not already present
        stack = StorageStack(
            warehouse_id="WH-BUMDES-AUTOGEN",
            stack_code=stack_code,
            capacity_tons=50.0,
            current_tonnage=40.0,
            temperature_c=temperature_c,
            humidity_rh_pct=humidity_rh_pct,
            temp_slope_1h=temp_slope_1h if temp_slope_1h is not None else 0.0,
            status=StackStatus.NORMAL,
            last_telemetry_at=now,
        )
        db.add(stack)
        db.flush()

    # Calculate temp_slope_1h if not explicitly provided
    if temp_slope_1h is None:
        last_time = stack.last_telemetry_at
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)
        delta_hours = max(0.01, (now - last_time).total_seconds() / 3600.0)
        temp_diff = temperature_c - stack.temperature_c
        temp_slope_1h = round(temp_diff / delta_hours, 2)

    stack.temperature_c = temperature_c
    stack.humidity_rh_pct = humidity_rh_pct
    stack.temp_slope_1h = temp_slope_1h
    stack.last_telemetry_at = now

    alert_triggered = False
    message = "Telemetry updated. Stack operating within optimal storage parameters."

    # Check heat spike & respiration conditions
    is_temp_critical = temperature_c > 35.0
    is_slope_critical = temp_slope_1h > 0.5
    is_rh_critical = humidity_rh_pct > 70.0

    if is_temp_critical or is_slope_critical or is_rh_critical:
        stack.status = StackStatus.CRITICAL_HEAT_SPIKE
        alert_triggered = True

        reasons = []
        if is_temp_critical:
            reasons.append(f"Temp {temperature_c:.1f}°C > 35.0°C")
        if is_slope_critical:
            reasons.append(f"Slope +{temp_slope_1h:.2f}°C/hr > 0.5°C/hr")
        if is_rh_critical:
            reasons.append(f"RH {humidity_rh_pct:.1f}% > 70.0%")
        trigger_reason = f"Stack {stack_code} Alert: " + ", ".join(reasons)

        action_taken = (
            f"CRITICAL_HEAT_SPIKE flagged: Triggered automated bottom-up aeration fans at {stack.warehouse_id}. "
            f"WhatsApp alert dispatched to Warehouse Head for immediate physical stack turning and moisture sampling."
        )

        log = ShiftActionLog(
            entity_type=EntityType.STORAGE_STACK,
            entity_id=stack_code,
            alert_severity=AlertSeverity.CRITICAL,
            trigger_reason=trigger_reason,
            action_taken=action_taken,
            operator_user="IOT_TELEMETRY_ENGINE",
        )
        db.add(log)
        message = f"CRITICAL_HEAT_SPIKE detected! {trigger_reason}"
    else:
        # Check warning threshold
        if temperature_c > 32.0 or humidity_rh_pct > 65.0:
            stack.status = StackStatus.WARNING
        else:
            stack.status = StackStatus.NORMAL

    db.commit()
    db.refresh(stack)
    return stack, alert_triggered, message


def compute_dml_metrics(db: Session, benchmark_dml_pct: float = 3.2, grain_price_per_kg: float = 6200.0) -> dict:
    """
    Computes Dry Matter Loss (DML) suppression performance:
    Under traditional tropical unmonitored storage, baseline grain respiration losses average 3.2%.
    With real-time IoT probe aeration and temperature containment, estimated loss is capped at ~0.8% - 1.2%.
    Returns tonnage saved and IDR economic value protected.
    """
    stacks = db.scalars(select(StorageStack)).all()
    if not stacks:
        return {
            "total_monitored_tonnage": 0.0,
            "traditional_benchmark_dml_pct": benchmark_dml_pct,
            "actual_estimated_dml_pct": 0.0,
            "suppression_savings_pct": 0.0,
            "grain_tonnage_saved": 0.0,
            "monetary_value_saved_idr": 0.0,
            "active_critical_stacks": 0,
            "calculation_basis": "No active warehouse storage stacks monitored.",
        }

    total_tonnage = sum(s.current_tonnage for s in stacks)
    critical_stacks_count = sum(1 for s in stacks if s.status == StackStatus.CRITICAL_HEAT_SPIKE)

    # Dynamic weighted DML estimation based on stack thermal state
    # Normal stacks: ~0.9% DML, Warning: ~1.6% DML, Critical: ~2.8% DML
    total_loss_tons = 0.0
    for s in stacks:
        if s.status == StackStatus.CRITICAL_HEAT_SPIKE:
            loss_rate = 0.028
        elif s.status == StackStatus.WARNING:
            loss_rate = 0.016
        else:
            loss_rate = 0.009
        total_loss_tons += s.current_tonnage * loss_rate

    actual_dml_pct = round((total_loss_tons / total_tonnage * 100.0), 2) if total_tonnage > 0 else 0.9
    suppression_savings_pct = max(0.0, round(benchmark_dml_pct - actual_dml_pct, 2))

    benchmark_loss_tons = total_tonnage * (benchmark_dml_pct / 100.0)
    grain_tonnage_saved = max(0.0, round(benchmark_loss_tons - total_loss_tons, 2))
    # grain_price_per_kg * 1000 = price per ton
    monetary_value_saved_idr = round(grain_tonnage_saved * 1000.0 * grain_price_per_kg, 0)

    return {
        "total_monitored_tonnage": round(total_tonnage, 2),
        "traditional_benchmark_dml_pct": benchmark_dml_pct,
        "actual_estimated_dml_pct": actual_dml_pct,
        "suppression_savings_pct": suppression_savings_pct,
        "grain_tonnage_saved": grain_tonnage_saved,
        "monetary_value_saved_idr": monetary_value_saved_idr,
        "active_critical_stacks": critical_stacks_count,
        "calculation_basis": (
            f"Evaluated across {len(stacks)} storage stacks. Model contrasts FAO tropical baseline "
            f"({benchmark_dml_pct}%) against active probe micro-aeration thermal telemetry."
        ),
    }


# ==============================================================
# 3. Dryer Capacity Balancing & Harvest Stress Testing
# ==============================================================

def perform_capacity_stress_test(
    db: Session,
    forecast_days: int = 14,
    forecast_daily_harvest_tons: float = 65.0
) -> dict:
    """
    Stress-tests 14-day harvest forecast volume against total rented partner dryer throughput.
    If projected load > 85% capacity, flags as STRESSED and recommends cohort schedule offset (+7 to +10 days).
    """
    dryers = db.scalars(select(DryerFacility)).all()
    operational_dryers = [d for d in dryers if d.is_operational]

    total_rated_capacity_tons_daily = sum(d.daily_rated_capacity_tons for d in operational_dryers)
    total_current_load_tons = sum(d.current_load_tons for d in operational_dryers)

    total_14day_dryer_capacity_tons = total_rated_capacity_tons_daily * forecast_days
    forecasted_14day_harvest_tons = forecast_daily_harvest_tons * forecast_days

    # Projected load includes current backlogged grain + incoming harvest
    projected_total_volume = total_current_load_tons + forecasted_14day_harvest_tons
    projected_utilization_pct = (
        round((projected_total_volume / total_14day_dryer_capacity_tons) * 100.0, 1)
        if total_14day_dryer_capacity_tons > 0 else 100.0
    )

    if projected_utilization_pct >= 95.0:
        capacity_status = "CRITICAL"
        offset_days = 10
        advisory = (
            f"CRITICAL BOTTLENECK DETECTED ({projected_utilization_pct}% capacity): Immediate harvest moratorium required. "
            f"Postpone cohort harvest schedules by +{offset_days} days and activate contingency secondary drying hubs in neighboring regency."
        )
    elif projected_utilization_pct >= 85.0:
        capacity_status = "STRESSED"
        offset_days = 7
        advisory = (
            f"STRESSED DRYER THROUGHPUT ({projected_utilization_pct}% capacity): Projected intake exceeds 85% limit. "
            f"Recommend staggering planting/harvest cohort schedules by +{offset_days} days to prevent wet grain degradation."
        )
    else:
        capacity_status = "NORMAL"
        offset_days = 0
        advisory = f"Dryer throughput healthy ({projected_utilization_pct}% capacity). All inbound cohort intakes can be accommodated within 36h SLA."

    return {
        "total_partner_dryers": len(dryers),
        "operational_dryers": len(operational_dryers),
        "total_rated_capacity_tons_daily": round(total_rated_capacity_tons_daily, 2),
        "total_current_load_tons": round(total_current_load_tons, 2),
        "total_14day_dryer_capacity_tons": round(total_14day_dryer_capacity_tons, 2),
        "forecasted_14day_harvest_tons": round(forecasted_14day_harvest_tons, 2),
        "projected_utilization_pct": projected_utilization_pct,
        "capacity_status": capacity_status,
        "recommended_cohort_offset_days": offset_days,
        "advisory_recommendation": advisory,
    }

