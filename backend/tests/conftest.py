import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.database import Base, session, transaction as database_transaction
from app.main import app
from app.seed import seed


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as db, db.begin():
        seed(db, "zero")
    yield engine
    engine.dispose()


@pytest.fixture
def client(engine):
    def transaction():
        with Session(engine, expire_on_commit=False) as db, database_transaction(db):
            yield db

    app.dependency_overrides[session] = transaction
    client = TestClient(app, raise_server_exceptions=True)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.clear()

