import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Default fallback to postgresql://postgres:postgres@localhost:5432/grainflow_db as requested.
# If PostgreSQL URL is specified without an explicit DBAPI driver (i.e. 'postgresql://'),
# standard psycopg2-binary uses the 'postgresql+psycopg2://' driver dialect in SQLAlchemy 2.0.
RAW_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/grainflow_db"
)

# Normalize URL for psycopg2 if it starts with plain postgresql://
if RAW_DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = RAW_DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
else:
    DATABASE_URL = RAW_DATABASE_URL

# Configure engine arguments based on DB dialect (e.g. SQLite requires check_same_thread)
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

# Graceful engine factory: if postgresql is not running locally during development/testing,
# fallback seamlessly to sqlite:///grainflow.db to allow zero-config execution.
try:
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        connect_args=connect_args,
        pool_pre_ping=True
    )
    # Quick probe connection
    with engine.connect() as conn:
        pass
except Exception:
    # If remote/local postgres service is unavailable, fallback to local sqlite database
    DATABASE_URL = "sqlite:///./grainflow.db"
    connect_args = {"check_same_thread": False}
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        connect_args=connect_args,
        pool_pre_ping=True
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a SQLAlchemy database session and ensures closure."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
