from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

from backend.database.query_executor import QueryExecutor


@pytest.mark.parametrize(
    "diagnostic",
    [None, SimpleNamespace(message_primary=None)],
)
def test_database_error_handles_missing_primary_message(diagnostic):
    original = Exception("private driver detail")
    original.pgcode = "08006"
    if diagnostic is not None:
        original.diag = diagnostic

    error = OperationalError("SELECT 1", {}, original)

    code, message, sqlstate = QueryExecutor._classify_database_error(error)

    assert code == "CONNECTION_ERROR"
    assert sqlstate == "08006"
    assert "private driver detail" not in message
