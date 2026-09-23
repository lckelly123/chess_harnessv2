import os
import uuid

import pytest


@pytest.fixture
def postgres(monkeypatch):
    if os.getenv("POSITIONS_INTEGRATION_TEST") != "1":
        pytest.skip("Set POSITIONS_INTEGRATION_TEST=1 to test against local PostgreSQL")
    import psycopg.sql

    from positional_testing.datasets import store

    original_connect = store.connect
    schema = "test_positions_" + uuid.uuid4().hex
    with original_connect() as conn:
        conn.execute(
            psycopg.sql.SQL("CREATE SCHEMA {}").format(psycopg.sql.Identifier(schema))
        )

    def isolated_connect():
        conn = original_connect()
        conn.execute(
            psycopg.sql.SQL("SET search_path TO {}").format(
                psycopg.sql.Identifier(schema)
            )
        )
        return conn

    monkeypatch.setattr(store, "connect", isolated_connect)
    try:
        yield store
    finally:
        with original_connect() as conn:
            conn.execute(
                psycopg.sql.SQL("DROP SCHEMA {} CASCADE").format(
                    psycopg.sql.Identifier(schema)
                )
            )
