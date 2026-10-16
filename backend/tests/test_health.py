async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_api_error_body(client):
    r = await client.get("/__test_error")
    assert r.status_code == 409
    assert r.json() == {"detail": {"code": "agent_not_live", "message": "x"}}


async def test_stage1_tables_exist(db):
    from sqlalchemy import text

    rows = await db.execute(text("select tablename from pg_tables where schemaname='public'"))
    assert {"users", "llm_keys", "agents", "sessions", "messages"} <= {r[0] for r in rows}


async def test_stage2a_tables_exist(db):
    from sqlalchemy import text

    rows = await db.execute(text("select tablename from pg_tables where schemaname='public'"))
    assert {"agent_tools", "documents", "document_chunks"} <= {r[0] for r in rows}
    columns = await db.execute(text("select column_name from information_schema.columns where table_name='messages'"))
    assert "sources" in {r[0] for r in columns}
