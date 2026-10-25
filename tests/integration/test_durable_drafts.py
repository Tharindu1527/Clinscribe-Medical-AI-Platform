"""Durable drafts on the real Postgres (ADR-0016): a draft checkpointed by one process is resumed by
another, the write's PHI never reaches the checkpoint tables, and an ended draft leaves no state.
Scripted model and fake tools (no model calls). Needs `just up` and `just migrate`."""

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from agents.graph import Agents
from apps.api.drafts import Draft, PostgresDrafts
from config.db import app_conninfo, owner_conninfo
from config.settings import Settings
from tests.unit.test_agent_graph import (
    APPROVE,
    CTX,
    NOTE_REPLY,
    TRANSCRIPT,
    FakeTools,
    ScriptedChat,
    _resume,
)

pytestmark = pytest.mark.integration


def _pool() -> ConnectionPool:
    kwargs = {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}
    return ConnectionPool(
        app_conninfo(Settings()), min_size=1, max_size=2, kwargs=kwargs, open=True
    )


@pytest.fixture
def thread(stack: list[dict[str, str]]) -> Iterator[str]:
    draft_id = f"draft-it-{uuid.uuid4().hex[:12]}"
    yield draft_id
    with _pool() as pool:  # clean up whatever a failed run left behind
        PostgresSaver(pool).delete_thread(draft_id)  # type: ignore[arg-type]


def _checkpoint_rows(draft_id: str) -> list[tuple[object, ...]]:
    """Every row stored for one thread in LangGraph's tables, read as the owner."""
    rows: list[tuple[object, ...]] = []
    with psycopg.connect(owner_conninfo(Settings())) as conn:
        for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            rows += conn.execute(
                f"SELECT * FROM {table} WHERE thread_id = %s",  # noqa: S608 (fixed names)
                (draft_id,),
            ).fetchall()
    return rows


def test_a_draft_is_resumed_by_another_process_and_ends_without_state(thread: str) -> None:
    config = {"configurable": {"thread_id": thread}}
    tools = FakeTools([])
    start = {
        "mode": "scribe",
        "encounter_id": "enc-1",
        "patient_id": "p-1",
        "transcript": TRANSCRIPT,
    }
    with _pool() as pool:  # the first API process makes the draft, then stops
        agents = Agents(ScriptedChat(note=[NOTE_REPLY]), tools, alias=lambda t: f"alias-{t}")
        out = agents.build(PostgresSaver(pool)).invoke(start, config)  # type: ignore[arg-type]
    draft = out["__interrupt__"][0].value["draft"]

    with _pool() as pool:  # a new process with a new pool
        saver = PostgresSaver(pool)  # type: ignore[arg-type]
        graph = Agents(ScriptedChat(), tools, alias=lambda t: f"alias-{t}").build(saver)
        assert any(task.interrupts for task in graph.get_state(config).tasks)
        done = graph.invoke(Command(resume=_resume(draft, APPROVE)), config, context=CTX)
        assert done["result"]["status"] == "written"
        stored = repr(_checkpoint_rows(thread)).encode()
        assert b"Thirsty for two weeks" in stored  # positive control: the draft is in Postgres
        assert b"1970-01-02" not in stored  # the identifiers came as run context
        assert b"Doe" not in stored
        saver.delete_thread(thread)
        assert graph.get_state(config).values == {}
    assert _checkpoint_rows(thread) == []  # no rows left in any table
    assert len(tools.writes) == 1


def test_the_draft_list_records_who_made_it_and_how_it_ended(stack: list[dict[str, str]]) -> None:
    drafts = PostgresDrafts(app_conninfo(Settings()))
    draft_id = f"draft-it-{uuid.uuid4().hex[:12]}"
    try:
        _list_round_trip(drafts, draft_id)
    finally:  # test rows go; only the owner may delete
        with psycopg.connect(owner_conninfo(Settings())) as conn:
            conn.execute("DELETE FROM drafts WHERE draft_id = %s", (draft_id,))


def _list_round_trip(drafts: PostgresDrafts, draft_id: str) -> None:
    drafts.add(Draft(draft_id, "1617", "enc-it", "dr-demo"))
    assert drafts.get(draft_id) == Draft(draft_id, "1617", "enc-it", "dr-demo")
    assert draft_id in [d.draft_id for d in drafts.waiting()]
    drafts.finish(draft_id, "written", "DocumentReference/1")
    assert drafts.get(draft_id) == Draft(
        draft_id, "1617", "enc-it", "dr-demo", "written", "DocumentReference/1"
    )
    assert draft_id not in [d.draft_id for d in drafts.waiting()]
    with psycopg.connect(app_conninfo(Settings())) as conn, pytest.raises(psycopg.Error):
        conn.execute("DELETE FROM drafts WHERE draft_id = %s", (draft_id,))  # the app never deletes
