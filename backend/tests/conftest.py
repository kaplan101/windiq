import os

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import Base

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://windiq:windiq@localhost:5432/windiq_test"
)


def _create_database_if_missing(url: str) -> None:
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database})
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def db_engine():
    """Eigene Test-Datenbank (windiq_test), damit lokale Daten unangetastet bleiben."""
    try:
        _create_database_if_missing(TEST_DATABASE_URL)
    except OperationalError:
        if os.environ.get("CI"):
            raise
        pytest.skip("Keine Test-Datenbank erreichbar – lokal mit 'docker compose up -d db' starten")
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    with Session(db_engine) as session:
        yield session
    with db_engine.begin() as conn:
        conn.execute(text("TRUNCATE measurement"))
