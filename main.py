import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import engine, Base
import models  # Ensures declarative models are registered
from routers import lots_router, capacity_router, storage_router, logs_router

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("grainflow.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    Initializes database schema tables on startup and handles graceful shutdown.
    """
    logger.info("Initializing database tables for Grainflow Control Tower...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized successfully.")
    yield
    logger.info("Grainflow Control Tower backend shutting down.")


app = FastAPI(
    title="Grainflow Control Tower API",
    description=(
        "Asset-light grain supply chain orchestration system for rural Indonesia. "
        "Coordinates wet grain farmgate intake, 36h aflatoxin SLA triage, "
        "partner dryer load balancing, warehouse IoT micro-aeration monitoring, and 0-day DSO farmer settlement."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS Middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permits local frontends (React, Streamlit, mobile clients)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register modular API routers under prefix /api/v1
app.include_router(lots_router, prefix="/api/v1")
app.include_router(capacity_router, prefix="/api/v1")
app.include_router(storage_router, prefix="/api/v1")
app.include_router(logs_router, prefix="/api/v1")


@app.get("/", tags=["Health Check"])
def health_check():
    """System health and root status endpoint."""
    return {
        "system": "Grainflow Control Tower Backend",
        "status": "OPERATIONAL",
        "api_version": "v1",
        "endpoints": {
            "docs": "/docs",
            "lots": "/api/v1/lots",
            "capacity": "/api/v1/capacity",
            "storage": "/api/v1/storage",
            "logs": "/api/v1/logs",
        },
    }

