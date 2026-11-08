import logging
from datetime import datetime, timedelta, timezone
from database import engine, SessionLocal, Base
from models import (
    GrainLot,
    DryerFacility,
    StorageStack,
    ShiftActionLog,
    AflatoxinRiskLevel,
    LotStatus,
    SettlementStatus,
    StackStatus,
    EntityType,
    AlertSeverity,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("grainflow.seed")


def seed_database():
    """
    Populates realistic seed data for Grainflow Control Tower:
    - 1 Cluster (Grobogan-01) with 3 Partner Dryer Facilities (representing 3 drying cohorts/hubs)
    - 5 Grain Lots across varied triage and moisture conditions
    - 4 Warehouse Storage Stacks with multi-point probe thermal telemetry
    - Initial Shift Action Logs
    """
    logger.info("Ensuring database tables exist...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # Check if already seeded
        existing_lots = db.query(GrainLot).count()
        if existing_lots > 0:
            logger.info("Database already seeded with %d grain lots. Skipping duplicate seeding.", existing_lots)
            return

        now = datetime.now(timezone.utc)
        logger.info("Seeding realistic Grainflow master & operational data...")

        # -------------------------------------------------------------
        # 1. Dryer Facilities (3 Cohort Hubs in Grobogan Cluster)
        # -------------------------------------------------------------
        dryers = [
            DryerFacility(
                id="DRYER-BUMDES-WIROSARI-01",
                cluster_id="GROBOGAN-01",
                facility_name="BUMDes Wirosari Bed Dryer Hub",
                daily_rated_capacity_tons=40.0,
                current_load_tons=28.5,
                is_operational=True,
                location_lat=-7.0982,
                location_lon=111.1345,
            ),
            DryerFacility(
                id="DRYER-UD-TANI-MAKMUR-02",
                cluster_id="GROBOGAN-01",
                facility_name="UD Tani Makmur Continuous Dryer",
                daily_rated_capacity_tons=60.0,
                current_load_tons=45.0,
                is_operational=True,
                location_lat=-7.0854,
                location_lon=111.1120,
            ),
            DryerFacility(
                id="DRYER-KOPERASI-PURWODADI-03",
                cluster_id="GROBOGAN-01",
                facility_name="Koperasi Produsen Purwodadi Hub",
                daily_rated_capacity_tons=30.0,
                current_load_tons=8.0,
                is_operational=True,
                location_lat=-7.0890,
                location_lon=110.9167,
            ),
        ]
        db.add_all(dryers)
        db.flush()

        # -------------------------------------------------------------
        # 2. Grain Lots (5 Lots across Triage & Moisture states)
        # -------------------------------------------------------------
        # Lot 1: Critical urgency, high moisture, near SLA deadline
        lot1_harvest = now - timedelta(hours=28)
        lot1 = GrainLot(
            id="LOT-GROB-20261108-001",
            cluster_id="GROBOGAN-01",
            gapoktan_name="Gapoktan Sumber Rejeki",
            farmer_name="Slamet Riyadi",
            farmer_phone="+6281234567891",
            gross_weight_kg=5200.0,
            moisture_pct=34.2,
            damaged_kernels_pct=6.5,
            aflatoxin_risk_level=AflatoxinRiskLevel.CRITICAL,
            status=LotStatus.PENDING_TRIAGE,
            harvest_timestamp=lot1_harvest,
            sla_deadline=lot1_harvest + timedelta(hours=36),  # 8h remaining!
            assigned_dryer_id=None,
            settlement_status=SettlementStatus.UNSETTLED,
            base_price_per_kg=5800.0,
            quality_premium_per_kg=-150.0,  # moisture deduction
            net_payout_amount=round(5200.0 * (5800.0 - 150.0), 2),
        )

        # Lot 2: Dispatched to dryer, currently drying
        lot2_harvest = now - timedelta(hours=14)
        lot2 = GrainLot(
            id="LOT-GROB-20261108-002",
            cluster_id="GROBOGAN-01",
            gapoktan_name="Gapoktan Tani Mulya",
            farmer_name="Ahmad Suparno",
            farmer_phone="+6281398765432",
            gross_weight_kg=7800.0,
            moisture_pct=29.0,
            damaged_kernels_pct=3.2,
            aflatoxin_risk_level=AflatoxinRiskLevel.HIGH,
            status=LotStatus.DRYING_IN_PROGRESS,
            harvest_timestamp=lot2_harvest,
            sla_deadline=lot2_harvest + timedelta(hours=36),
            assigned_dryer_id="DRYER-BUMDES-WIROSARI-01",
            settlement_status=SettlementStatus.DISBURSED,
            settlement_disbursed_at=now - timedelta(hours=10),
            base_price_per_kg=5800.0,
            quality_premium_per_kg=0.0,
            net_payout_amount=round(7800.0 * 5800.0, 2),
        )

        # Lot 3: Fresh intake from morning harvest, normal moisture
        lot3_harvest = now - timedelta(hours=3)
        lot3 = GrainLot(
            id="LOT-GROB-20261108-003",
            cluster_id="GROBOGAN-01",
            gapoktan_name="Gapoktan Berkah Tani",
            farmer_name="Bambang Sutrisno",
            farmer_phone="+6285211223344",
            gross_weight_kg=4300.0,
            moisture_pct=23.5,
            damaged_kernels_pct=1.8,
            aflatoxin_risk_level=AflatoxinRiskLevel.MODERATE,
            status=LotStatus.DISPATCHED_TO_DRYER,
            harvest_timestamp=lot3_harvest,
            sla_deadline=lot3_harvest + timedelta(hours=36),
            assigned_dryer_id="DRYER-UD-TANI-MAKMUR-02",
            settlement_status=SettlementStatus.UNSETTLED,
            base_price_per_kg=5800.0,
            quality_premium_per_kg=100.0,
            net_payout_amount=round(4300.0 * 5900.0, 2),
        )

        # Lot 4: Completed drying, certified Factory Grade
        lot4_harvest = now - timedelta(hours=40)
        lot4 = GrainLot(
            id="LOT-GROB-20261108-004",
            cluster_id="GROBOGAN-01",
            gapoktan_name="Gapoktan Margo Rukun",
            farmer_name="Kartono",
            farmer_phone="+6287766554433",
            gross_weight_kg=8500.0,
            moisture_pct=13.8,  # Below 14% feedmill standard!
            damaged_kernels_pct=1.0,
            aflatoxin_risk_level=AflatoxinRiskLevel.LOW,
            status=LotStatus.FACTORY_GRADE,
            harvest_timestamp=lot4_harvest,
            sla_deadline=lot4_harvest + timedelta(hours=36),
            assigned_dryer_id="DRYER-KOPERASI-PURWODADI-03",
            settlement_status=SettlementStatus.DISBURSED,
            settlement_disbursed_at=now - timedelta(hours=20),
            base_price_per_kg=5800.0,
            quality_premium_per_kg=250.0,
            net_payout_amount=round(8500.0 * 6050.0, 2),
        )

        # Lot 5: Rejected due to extreme decay and mold
        lot5_harvest = now - timedelta(hours=35)
        lot5 = GrainLot(
            id="LOT-GROB-20261108-005",
            cluster_id="GROBOGAN-01",
            gapoktan_name="Gapoktan Sari Bumi",
            farmer_name="Sudirman",
            farmer_phone="+6281900112233",
            gross_weight_kg=3100.0,
            moisture_pct=36.0,
            damaged_kernels_pct=14.0,
            aflatoxin_risk_level=AflatoxinRiskLevel.CRITICAL,
            status=LotStatus.REJECTED,
            harvest_timestamp=lot5_harvest,
            sla_deadline=lot5_harvest + timedelta(hours=36),
            assigned_dryer_id=None,
            settlement_status=SettlementStatus.VOID,
            base_price_per_kg=5800.0,
            quality_premium_per_kg=0.0,
            net_payout_amount=0.0,
        )

        db.add_all([lot1, lot2, lot3, lot4, lot5])
        db.flush()

        # -------------------------------------------------------------
        # 3. Storage Stacks (4 Monitored Stacks in BUMDes Warehouse)
        # -------------------------------------------------------------
        stacks = [
            StorageStack(
                warehouse_id="WH-BUMDES-BLOK-C",
                stack_code="STACK-A1",
                capacity_tons=50.0,
                current_tonnage=46.5,
                temperature_c=27.8,
                humidity_rh_pct=62.0,
                temp_slope_1h=0.08,
                status=StackStatus.NORMAL,
                last_telemetry_at=now - timedelta(minutes=15),
            ),
            StorageStack(
                warehouse_id="WH-BUMDES-BLOK-C",
                stack_code="STACK-A2",
                capacity_tons=50.0,
                current_tonnage=48.0,
                temperature_c=36.4,  # Over 35°C threshold!
                humidity_rh_pct=72.5,  # Over 70% threshold!
                temp_slope_1h=0.68,   # Over 0.5°C/hr threshold!
                status=StackStatus.CRITICAL_HEAT_SPIKE,
                last_telemetry_at=now - timedelta(minutes=5),
            ),
            StorageStack(
                warehouse_id="WH-BUMDES-BLOK-C",
                stack_code="STACK-B1",
                capacity_tons=50.0,
                current_tonnage=35.0,
                temperature_c=33.2,
                humidity_rh_pct=67.0,
                temp_slope_1h=0.25,
                status=StackStatus.WARNING,
                last_telemetry_at=now - timedelta(minutes=30),
            ),
            StorageStack(
                warehouse_id="WH-BUMDES-BLOK-C",
                stack_code="STACK-B2",
                capacity_tons=50.0,
                current_tonnage=42.0,
                temperature_c=28.1,
                humidity_rh_pct=63.5,
                temp_slope_1h=-0.05,
                status=StackStatus.AERATION_ACTIVE,
                last_telemetry_at=now - timedelta(minutes=10),
            ),
        ]
        db.add_all(stacks)
        db.flush()

        # -------------------------------------------------------------
        # 4. Initial Audit Shift Action Logs
        # -------------------------------------------------------------
        logs = [
            ShiftActionLog(
                entity_type=EntityType.STORAGE_STACK,
                entity_id="STACK-A2",
                alert_severity=AlertSeverity.CRITICAL,
                trigger_reason="Stack A2 Temp 36.4°C > 35°C & RH 72.5% > 70% with +0.68°C/hr slope",
                action_taken="Automated WhatsApp sent to Warehouse Head. Bottom-up micro-aeration fans engaged automatically.",
                operator_user="IOT_TELEMETRY_ENGINE",
                acknowledged=False,
                created_at=now - timedelta(minutes=25),
            ),
            ShiftActionLog(
                entity_type=EntityType.GRAIN_LOT,
                entity_id="LOT-GROB-20261108-001",
                alert_severity=AlertSeverity.WARNING,
                trigger_reason="Moisture 34.2% with <8h SLA remaining",
                action_taken="Priority dispatch recommended to BUMDes Wirosari Bed Dryer Hub.",
                operator_user="INTAKE_GATE_SYSTEM",
                acknowledged=True,
                acknowledged_at=now - timedelta(minutes=45),
                created_at=now - timedelta(hours=2),
            ),
            ShiftActionLog(
                entity_type=EntityType.GRAIN_LOT,
                entity_id="LOT-GROB-20261108-002",
                alert_severity=AlertSeverity.INFO,
                trigger_reason="Instant Farmgate Digital Scale Settlement Executed",
                action_taken="Disbursed Rp 45,240,000.00 to Ahmad Suparno (+6281398765432). DSO: 0.0 days.",
                operator_user="TREASURY_GATEWAY",
                acknowledged=True,
                acknowledged_at=now - timedelta(hours=10),
                created_at=now - timedelta(hours=10),
            ),
        ]
        db.add_all(logs)

        db.commit()
        logger.info("Database successfully seeded with realistic sample data!")
    except Exception as e:
        db.rollback()
        logger.exception("Failed to seed database: %s", e)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()

