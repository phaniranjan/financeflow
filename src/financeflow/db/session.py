from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from financeflow.core.config import get_settings

settings = get_settings()

engine = create_engine(
    str(settings.database_url),
    pool_pre_ping=True,
    echo=(settings.log_level == "DEBUG"),
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Dependency provider yielding a synchronous database session.

    Guarantees that uncommitted transactions are rolled back if an unhandled
    exception escapes, and that sessions are properly closed in all cases.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
