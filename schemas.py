from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict
from models import (
    AflatoxinRiskLevel,
    LotStatus,
    SettlementStatus,
    StackStatus,
    EntityType,
    AlertSeverity,
)


# ==========================================
# 1. Grain Lot Schemas
# ==========================================

class GrainLotBase(BaseModel):
    cluster_id: str = Field(..., example="GROBOGAN-01")
    gapoktan_name: str = Field(..., example="Gapoktan Tani Makmur")
    farmer_name: str = Field(..., example="Budi Santoso")
    farmer_phone: str = Field(..., example="+6281234567890")
    gross_weight_kg: float = Field(..., gt=0, example=4500.0)
    moisture_pct: float = Field(..., ge=5.0, le=50.0, example=32.5)
    damaged_kernels_pct: float = Field(default=0.0, ge=0.0, le=100.0, example=4.0)
    base_price_per_kg: float = Field(default=5800.0, gt=0, example=5800.0)
    quality_premium_per_kg: float = Field(default=0.0, example=0.0)
    harvest_timestamp: datetime = Field(..., example="2026-11-08T06:00:00Z")

    @field_validator("farmer_phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        clean = v.strip().replace(" ", "").replace("-", "")
        if not (clean.startswith("+") or clean.startswith("08") or clean.isdigit()):
            raise ValueError("Farmer phone must be in standard E.164 or valid national format (e.g., +62...)")
        return clean


class GrainLotCreate(GrainLotBase):
    id: Optional[str] = Field(None, example="LOT-KG-20261108-001")


class GrainLotTriageUpdate(BaseModel):
    status: LotStatus
    assigned_dryer_id: Optional[str] = None
    operator_user: Optional[str] = "PPL_OFFICER"
    notes: Optional[str] = None


class GrainLotResponse(GrainLotBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    aflatoxin_risk_level: AflatoxinRiskLevel
    status: LotStatus
    sla_deadline: datetime
    sla_hours_remaining: float
    assigned_dryer_id: Optional[str] = None
    settlement_status: SettlementStatus
    settlement_disbursed_at: Optional[datetime] = None
    net_payout_amount: float
    created_at: datetime
    updated_at: datetime


class SettlementResponse(BaseModel):
    lot_id: str
    settlement_status: SettlementStatus
    net_payout_amount: float
    settlement_disbursed_at: datetime
    dso_days: float = 0.0
    message: str


# ==========================================
# 2. Dryer Facility & Stress Test Schemas
# ==========================================

class DryerFacilityBase(BaseModel):
    id: str = Field(..., example="DRYER-BUMDES-01")
    cluster_id: str = Field(..., example="GROBOGAN-01")
    facility_name: str = Field(..., example="BUMDes Wirosari Bed Dryer Hub")
    daily_rated_capacity_tons: float = Field(..., gt=0, example=40.0)
    current_load_tons: float = Field(default=0.0, ge=0, example=15.0)
    is_operational: bool = True
    location_lat: Optional[float] = None
    location_lon: Optional[float] = None


class DryerFacilityResponse(DryerFacilityBase):
    model_config = ConfigDict(from_attributes=True)

    utilization_pct: float = 0.0


class CapacityStressTestResponse(BaseModel):
    total_partner_dryers: int
    operational_dryers: int
    total_rated_capacity_tons_daily: float
    total_current_load_tons: float
    total_14day_dryer_capacity_tons: float
    forecasted_14day_harvest_tons: float
    projected_utilization_pct: float
    capacity_status: str  # "NORMAL", "STRESSED", "CRITICAL"
    recommended_cohort_offset_days: int
    advisory_recommendation: str


# ==========================================
# 3. Storage Stack & IoT Telemetry Schemas
# ==========================================

class StorageStackBase(BaseModel):
    warehouse_id: str = Field(..., example="WH-BUMDES-BLOK-C")
    stack_code: str = Field(..., example="STACK-A1")
    capacity_tons: float = Field(..., gt=0, example=50.0)
    current_tonnage: float = Field(default=0.0, ge=0, example=42.0)
    temperature_c: float = Field(..., ge=10.0, le=75.0, example=28.5)
    humidity_rh_pct: float = Field(..., ge=10.0, le=100.0, example=65.0)
    temp_slope_1h: float = Field(default=0.0, example=0.15)


class StorageStackCreate(StorageStackBase):
    status: Optional[StackStatus] = StackStatus.NORMAL


class StorageStackResponse(StorageStackBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: StackStatus
    last_telemetry_at: datetime


class TelemetryIngestRequest(BaseModel):
    stack_code: str = Field(..., example="STACK-A1")
    temperature_c: float = Field(..., ge=10.0, le=75.0, example=36.2)
    humidity_rh_pct: float = Field(..., ge=10.0, le=100.0, example=72.5)
    temp_slope_1h: Optional[float] = Field(None, example=0.65)


class TelemetryIngestResponse(BaseModel):
    stack_code: str
    status: StackStatus
    temperature_c: float
    humidity_rh_pct: float
    temp_slope_1h: float
    alert_triggered: bool
    message: str


class DMLMetricsResponse(BaseModel):
    total_monitored_tonnage: float
    traditional_benchmark_dml_pct: float = 3.2
    actual_estimated_dml_pct: float
    suppression_savings_pct: float
    grain_tonnage_saved: float
    monetary_value_saved_idr: float
    active_critical_stacks: int
    calculation_basis: str


# ==========================================
# 4. Shift Action Log Schemas
# ==========================================

class ShiftActionLogBase(BaseModel):
    entity_type: EntityType
    entity_id: str
    alert_severity: AlertSeverity
    trigger_reason: str
    action_taken: str
    operator_user: str = "SYSTEM"


class ShiftActionLogCreate(ShiftActionLogBase):
    pass


class ShiftActionLogResponse(ShiftActionLogBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    acknowledged: bool
    acknowledged_at: Optional[datetime] = None
    created_at: datetime

