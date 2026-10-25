from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    # pool_pre_ping: prüft Verbindungen vor der Nutzung, z. B. nach einem DB-Neustart
    # connect_timeout: bei nicht erreichbarer DB nach 5 s abbrechen statt unbegrenzt zu warten
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Eine Session pro Anfrage; wird danach automatisch geschlossen."""
    with get_session_factory()() as session:
        yield session
