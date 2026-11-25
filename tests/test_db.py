from types import SimpleNamespace
from unittest.mock import MagicMock


def test_engine_uses_centralized_database_settings(monkeypatch):
    import src.db as db_module

    settings = SimpleNamespace(
        db=SimpleNamespace(
            user="test_user",
            password="p@ss:word",
            host="db.test.internal",
            port=5544,
            name="test_database",
        )
    )
    engine = MagicMock()
    monkeypatch.setattr(db_module, "_engine", None)
    monkeypatch.setattr(db_module, "get_settings", lambda: settings)
    create_engine = MagicMock(return_value=engine)
    monkeypatch.setattr(db_module, "create_engine", create_engine)

    assert db_module.get_engine() is engine

    url = create_engine.call_args.args[0]
    assert url.drivername == "postgresql+psycopg2"
    assert url.username == "test_user"
    assert url.password == "p@ss:word"
    assert url.host == "db.test.internal"
    assert url.port == 5544
    assert url.database == "test_database"
