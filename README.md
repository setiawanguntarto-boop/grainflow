# Grainflow Control Tower - Backend API

Production-ready FastAPI backend for the **Grainflow Control Tower**: an asset-light grain supply chain orchestration system built for Indonesian smallholder agriculture and feedmill supply chains.

## Key Capabilities

1. **Farmgate Intake & 36h Aflatoxin SLA Triage (`/api/v1/lots`)**:
   - Automated 36-hour drying countdown calculated upon intake (`sla_deadline = harvest_timestamp + 36h`).
   - Dynamic aflatoxin hazard estimation based on moisture % and defect rate.
   - Farmgate digital scale payout with instant settlement timestamping for **0-day Days Sales Outstanding (DSO)**.

2. **Dryer Load Balancing & Cohort Stress Testing (`/api/v1/capacity`)**:
   - Aggregates partner and rented BUMDes drying hubs.
   - 14-day harvest forecast stress test; flags capacity bottlenecks ($>85\%$ load) and calculates cohort planting/harvest shift advisories (+7 to +10 days).

3. **Storage Stack IoT Multi-Point Telemetry (`/api/v1/storage`)**:
   - Ingests IoT probe readings (`temperature_c`, `humidity_rh_pct`, `temp_slope_1h`).
   - Automated threshold detection: Triggers `CRITICAL_HEAT_SPIKE` and aeration dispatch if Temp $> 35^\circ\text{C}$, slope $> 0.5^\circ\text{C/hr}$, or RH $> 70\%$.
   - **Dry Matter Loss (DML) Suppression Analytics**: Computes grain tonnage and IDR monetary value protected against the traditional 3.2% tropical unmonitored baseline.

4. **Shift Action Logs & WhatsApp Emergency Dispatch (`/api/v1/logs`)**:
   - Complete audit trail of system alerts, dispatch directives, and operational acknowledgments.

---

## Project Structure

```
grainflow/
├── database.py       # SQLAlchemy 2.0 engine, SessionLocal, Base, get_db() dependency
├── models.py         # Declarative models: GrainLot, StorageStack, DryerFacility, ShiftActionLog
├── schemas.py        # Pydantic V2 schemas with validation & from_attributes = True
├── services.py       # Core business logic: SLA calculation, DML metrics, stress test, telemetry alerts
├── routers.py        # Modular API endpoints under /api/v1 prefix
├── main.py           # FastAPI application factory, CORS, lifespan startup table init
├── seed.py           # Realistic database seeder script (Grobogan-01 cluster)
├── test_api.py       # Comprehensive unit & integration tests
├── requirements.txt  # Dependencies
└── .env.example      # Environment variables template
```

---

## Getting Started

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment (Optional)
By default, the backend connects to:
`postgresql://postgres:postgres@localhost:5432/grainflow_db`
with an automatic fallback to local SQLite (`sqlite:///./grainflow.db`) if PostgreSQL is not active.

To set your custom PostgreSQL database:
```bash
cp .env.example .env
# Edit DATABASE_URL in .env
```

### 3. Seed Realistic Data
Populate the Grobogan-01 cluster with sample dryers, grain lots across triage states, storage stacks, and action logs:
```bash
python seed.py
```

### 4. Run the API Server
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Interactive documentation will be available at:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

### 5. Run Test Suite
```bash
python -m unittest test_api.py
```
