import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


ROOT = Path(__file__).resolve().parents[2]
engine = create_engine(
    os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'simulator.db'}"),
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def sqlite_constraints(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")


SessionLocal = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def transaction(db):
    try:
        # Serialize balance reads with their writes to prevent concurrent overposting.
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


def session():
    with SessionLocal() as db, transaction(db):
        yield db

