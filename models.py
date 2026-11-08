import enum
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    Enum as SAEnum,
    Text,
)
from database import Base


class AflatoxinRiskLevel(str, enum.Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class LotStatus(str, enum.Enum):
    PENDING_TRIAGE = "PENDING_TRIAGE"
    DISPATCHED_TO_DRYER = "DISPATCHED_TO_DRYER"
    DRYING_IN_PROGRESS = "DRYING_IN_PROGRESS"
    FACTORY_GRADE = "FACTORY_GRADE"
    REJECTED = "REJECTED"


class SettlementStatus(str, enum.Enum):
    UNSETTLED = "UNSETTLED"
    DISBURSED = "DISBURSED"
    VOID = "VOID"


class StackStatus(str, enum.Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL_HEAT_SPIKE = "CRITICAL_HEAT_SPIKE"
    AERATION_ACTIVE = "AERATION_ACTIVE"


class EntityType(str, enum.Enum):
    GRAIN_LOT = "GRAIN_LOT"
    STORAGE_STACK = "STORAGE_STACK"
    HARVEST_SCHEDULE = "HARVEST_SCHEDULE"


class AlertSeverity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class GrainLot(Base):
    """Represents wet grain batches entering collection points."""
    __tablename__ = "grain_lots"

    id = Column(String(64), primary_key=True, index=True)
    cluster_id = Column(String(64), nullable=False, index=True)
    gapoktan_name = Column(String(128), nullable=False)
    farmer_name = Column(String(128), nullable=False)
    farmer_phone = Column(String(32), nullable=False)
    gross_weight_kg = Column(Float, nullable=False)
    moisture_pct = Column(Float, nullable=False)
    damaged_kernels_pct = Column(Float, nullable=False, default=0.0)
    aflatoxin_risk_level = Column(SAEnum(AflatoxinRiskLevel), nullable=False)
    status = Column(SAEnum(LotStatus), nullable=False, default=LotStatus.PENDING_TRIAGE, index=True)
    harvest_timestamp = Column(DateTime(timezone=True), nullable=False)
    sla_deadline = Column(DateTime(timezone=True), nullable=False)
    assigned_dryer_id = Column(String(64), nullable=True)
    settlement_status = Column(SAEnum(SettlementStatus), nullable=False, default=SettlementStatus.UNSETTLED)
    settlement_disbursed_at = Column(DateTime(timezone=True), nullable=True)
    base_price_per_kg = Column(Float, nullable=False, default=5800.0)
    quality_premium_per_kg = Column(Float, nullable=False, default=0.0)
    net_payout_amount = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    @property
    def sla_hours_remaining(self) -> float:
        """Dynamic calculation: (sla_deadline - now()) in hours."""
        if not self.sla_deadline:
            return 0.0
        now = datetime.now(timezone.utc)
        deadline = self.sla_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        diff = deadline - now
        return round(diff.total_seconds() / 3600.0, 2)


class StorageStack(Base):
    """Represents rented warehouse bag-stacks instrumented with IoT probe sensors."""
    __tablename__ = "storage_stacks"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    warehouse_id = Column(String(64), nullable=False, index=True)
    stack_code = Column(String(64), nullable=False, unique=True, index=True)
    capacity_tons = Column(Float, nullable=False)
    current_tonnage = Column(Float, nullable=False, default=0.0)
    temperature_c = Column(Float, nullable=False)
    humidity_rh_pct = Column(Float, nullable=False)
    temp_slope_1h = Column(Float, nullable=False, default=0.0)
    status = Column(SAEnum(StackStatus), nullable=False, default=StackStatus.NORMAL, index=True)
    last_telemetry_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class DryerFacility(Base):
    """Represents rented/partner BUMDes or private drying hubs."""
    __tablename__ = "dryer_facilities"

    id = Column(String(64), primary_key=True, index=True)
    cluster_id = Column(String(64), nullable=False, index=True)
    facility_name = Column(String(128), nullable=False)
    daily_rated_capacity_tons = Column(Float, nullable=False)
    current_load_tons = Column(Float, nullable=False, default=0.0)
    is_operational = Column(Boolean, nullable=False, default=True)
    location_lat = Column(Float, nullable=True)
    location_lon = Column(Float, nullable=True)


class ShiftActionLog(Base):
    """Audit trail for field interventions and automated WhatsApp dispatch alerts."""
    __tablename__ = "shift_action_logs"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    entity_type = Column(SAEnum(EntityType), nullable=False)
    entity_id = Column(String(64), nullable=False, index=True)
    alert_severity = Column(SAEnum(AlertSeverity), nullable=False, index=True)
    trigger_reason = Column(String(255), nullable=False)
    action_taken = Column(Text, nullable=False)
    operator_user = Column(String(64), nullable=False, default="SYSTEM")
    acknowledged = Column(Boolean, nullable=False, default=False)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

