from backend.config.settings import get_settings
from threading import Lock
from typing import Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL

_engine: Optional[Engine] = None
_engine_lock = Lock()


def get_engine() -> Engine:
    global _engine
    if _engine is not None:
        return _engine

    with _engine_lock:
        if _engine is None:
            database = get_settings().db
            url = URL.create(
                drivername="postgresql+psycopg2",
                username=database.user,
                password=database.password,
                host=database.host,
                port=database.port,
                database=database.name,
            )
            _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def test_connection():
    with get_engine().connect() as conn:
        version = conn.execute(text("SELECT version();")).scalar()
        has_vector = conn.execute(
            text("SELECT COUNT(*) FROM pg_extension WHERE extname='vector';")
        ).scalar()
    return version, bool(has_vector)

if __name__ == "__main__":
    print(test_connection())
