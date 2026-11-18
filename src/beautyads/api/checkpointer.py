"""Async PostgreSQL checkpoint resources, created in the app's lifespan loop."""

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


async def build_checkpointer(conninfo):
    pool = AsyncConnectionPool(
        conninfo,
        open=False,
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
            "prepare_threshold": 0,
        },
    )
    try:
        await pool.open()
        return AsyncPostgresSaver(pool)
    except BaseException:
        await pool.close()
        raise


async def setup_checkpointer(checkpointer):
    await checkpointer.setup()


async def close_checkpointer(checkpointer):
    await checkpointer.conn.close()
