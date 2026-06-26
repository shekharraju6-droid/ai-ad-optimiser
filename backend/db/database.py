"""
Database setup using SQLAlchemy.
SQLite for prototype; easy to switch to PostgreSQL later.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.getenv("ADOPTIMA_DB_PATH", os.path.join(ROOT_DIR, "adoptima.db"))

# Ensure parent directory exists (important for Railway volume mounts)
if os.path.dirname(DB_PATH):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
else:
    DB_PATH = os.path.join(ROOT_DIR, DB_PATH)
    os.makedirs(ROOT_DIR, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    import backend.db.models  # noqa: F401
    import backend.db.revenueops_models  # noqa: F401
    Base.metadata.create_all(bind=engine)
