"""Retention limits and GDPR erasure on the real Postgres (ADR-0022): what goes, what stays, the
audit row in the same transaction, and the logins' limits. Synthetic values and ids only; rows are
dated 2000 so the limits reach nothing else. Needs `just up` and `just migrate`."""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row

from apps.api.audit import AuditEntry, AuditLog
from apps.api.drafts import Draft, PostgresDrafts
from apps.api.edits import EditPair, PostgresEditPairs
from apps.api.labs import PendingLab, PostgresLabResults
from config.db import app_conninfo, owner_conninfo, retention_conninfo
from config.settings import Settings
from privacy.deid.store import PostgresStore
from scripts import retention
from scripts.migrate import CHECKPOINT_TABLES

pytestmark = pytest.mark.integration
OLD = datetime(2000, 1, 1, tzinfo=UTC)
NOW = datetime(2000, 3, 1, tzinfo=UTC)  # 60 days later: past both limits for rows dated OLD
DAYS = retention.limits()
PREFIX = "ret-it-"


def _cleanup() -> None:
    with psycopg.connect(owner_conninfo(Settings())) as conn:
        for table in CHECKPOINT_TABLES:
            conn.execute(f"DELETE FROM {table} WHERE thread_id LIKE %s", (PREFIX + "%",))  # noqa: S608
        conn.execute("DELETE FROM edit_pairs WHERE draft_id LIKE %s", (PREFIX + "%",))
        conn.execute("DELETE FROM drafts WHERE draft_id LIKE %s", (PREFIX + "%",))
        conn.execute("DELETE FROM deid_mappings WHERE encounter_id LIKE %s", (PREFIX + "%",))
        conn.execute("DELETE FROM lab_results WHERE lab_id LIKE %s", (PREFIX + "%",))


@pytest.fixture
def db(stack: list[dict[str, str]]) -> Iterator[None]:
    _cleanup()
    yield
    _cleanup()


def _seed(
    name: str, patient: str, *, waiting: bool = True, old_draft: bool = False, old_map: bool = False
) -> tuple[str, str]:
    """A draft with a checkpoint and a one-value de-ID mapping; returns (draft id, encounter)."""
    settings = Settings()
    draft_id, encounter = f"{PREFIX}draft-{name}", f"{PREFIX}enc-{name}"
    PostgresStore(app_conninfo(settings), settings.deid_mapping_key).surrogate_for(
        encounter, "PERSON", "Synthetic Person"
    )
    drafts = PostgresDrafts(app_conninfo(settings))
    drafts.add(Draft(draft_id, patient, encounter, "dr-demo"))
    if not waiting:
        drafts.finish(draft_id, "approved", "DocumentReference/x")
    with psycopg.connect(app_conninfo(settings), autocommit=True, row_factory=dict_row) as conn:
        config = {"configurable": {"thread_id": draft_id, "checkpoint_ns": ""}}
        PostgresSaver(conn).put(config, empty_checkpoint(), {}, {})  # type: ignore[arg-type]
    with psycopg.connect(owner_conninfo(settings)) as conn:
        if old_draft:
            conn.execute("UPDATE drafts SET created_at = %s WHERE draft_id = %s", (OLD, draft_id))
        if old_map:
            conn.execute(
                "UPDATE deid_mappings SET created_at = %s WHERE encounter_id = %s", (OLD, encounter)
            )
    return draft_id, encounter


def _lab(name: str, patient: str, *, old: bool = False) -> str:
    """A lab result awaiting confirmation, as the API stores it; returns its id."""
    lab_id = f"{PREFIX}lab-{name}"
    payload = {"observations": [{"resourceType": "Observation", "valueQuantity": {"value": 131}}]}
    PostgresLabResults(app_conninfo(Settings())).add(
        PendingLab(lab_id, patient, "dr-demo", payload)
    )
    if old:
        with psycopg.connect(owner_conninfo(Settings())) as conn:
            conn.execute("UPDATE lab_results SET created_at = %s WHERE lab_id = %s", (OLD, lab_id))
    return lab_id


def _edit_pair(draft_id: str, *, old: bool = False) -> None:
    """A doctor's edit pair for a draft, as the API keeps it (surrogate form)."""
    before = {"statements": [{"section": "plan", "text": "PERSON_1 to rest."}], "model": "m"}
    after = {"statements": [{"section": "plan", "text": "PERSON_1 to rest for a week."}]}
    PostgresEditPairs(app_conninfo(Settings())).add(
        EditPair(draft_id, "dr-demo", "note_writer@v2", "m", before, after)
    )
    if old:
        with psycopg.connect(owner_conninfo(Settings())) as conn:
            conn.execute(
                "UPDATE edit_pairs SET created_at = %s WHERE draft_id = %s", (OLD, draft_id)
            )


def _pairs(*draft_ids: str) -> list[str]:
    with psycopg.connect(owner_conninfo(Settings())) as conn:
        rows = conn.execute(
            "SELECT draft_id FROM edit_pairs WHERE draft_id = ANY(%s) ORDER BY draft_id",
            (list(draft_ids),),
        ).fetchall()
    return [str(r[0]) for r in rows]


def _lab_state(lab_id: str) -> tuple[str, bool]:
    """(status, values still held), read as the owner."""
    with psycopg.connect(owner_conninfo(Settings())) as conn:
        row = conn.execute(
            "SELECT status, payload IS NOT NULL FROM lab_results WHERE lab_id = %s", (lab_id,)
        ).fetchone()
    assert row is not None
    return str(row[0]), bool(row[1])


def _state(draft_id: str, encounter: str) -> tuple[str | None, int, int]:
    """(draft status, checkpoint rows, mapping rows), read as the owner."""
    with psycopg.connect(owner_conninfo(Settings())) as conn:
        status = conn.execute(
            "SELECT status FROM drafts WHERE draft_id = %s", (draft_id,)
        ).fetchone()
        checkpoints = conn.execute(
            "SELECT count(*) FROM checkpoints WHERE thread_id = %s", (draft_id,)
        ).fetchone()
        mappings = conn.execute(
            "SELECT count(*) FROM deid_mappings WHERE encounter_id = %s", (encounter,)
        ).fetchone()
    assert checkpoints is not None
    assert mappings is not None
    return (str(status[0]) if status else None), int(checkpoints[0]), int(mappings[0])


def _apply(plan: retention.Plan, ended_as: str, entry: AuditEntry, idle: datetime | None) -> int:
    settings = Settings()
    audit = AuditLog(retention_conninfo(settings), settings.audit_chain_key)
    with psycopg.connect(retention_conninfo(settings)) as conn, conn.transaction():
        done = retention.apply(conn, plan, ended_as, idle)
        return audit.append(AuditEntry(**{**entry.__dict__, "details": done.summary()}), conn)


def _audit_row(seq: int) -> dict[str, Any]:
    with psycopg.connect(owner_conninfo(Settings()), row_factory=dict_row) as conn:
        row = conn.execute("SELECT * FROM audit_log WHERE seq = %s", (seq,)).fetchone()
    assert row is not None
    return dict(row)


def test_retention_ends_stale_drafts_and_removes_idle_mappings(db: None) -> None:
    stale = _seed("stale", "p-a", old_draft=True, old_map=True)
    waiting = _seed("waiting", "p-a", old_map=True)  # mapping idle, but its draft still waits
    ended = _seed("ended", "p-a", waiting=False, old_draft=True, old_map=True)
    fresh = _seed("fresh", "p-a")
    stale_lab, fresh_lab = _lab("stale", "p-a", old=True), _lab("fresh", "p-a")
    _edit_pair(ended[0], old=True)
    _edit_pair(fresh[0])  # a recent pair (the draft itself still waits: a fixture shortcut)
    later = NOW + timedelta(days=DAYS["edit_pairs_days"])  # past the pairs' limit for OLD rows
    with psycopg.connect(retention_conninfo(Settings())) as conn:
        plan = retention.plan_retention(conn, NOW, DAYS)
        assert retention.plan_retention(conn, later, DAYS).edit_pairs == [ended[0]]
    assert plan.drafts == [stale[0]]
    assert plan.labs == [stale_lab]
    assert plan.edit_pairs == []  # 60 days old: inside the limit
    plan.edit_pairs = [ended[0]]
    assert plan.encounters == sorted([stale[1], ended[1]])
    idle = NOW - timedelta(days=DAYS["deid_mapping_idle_days"])
    entry = AuditEntry(actor="retention-job", role="operator", action="retention.run")
    seq = _apply(plan, "expired", entry, idle)
    assert _state(*stale) == ("expired", 0, 0)
    assert _state(*waiting) == ("awaiting_review", 1, 1)
    assert _state(*ended) == ("approved", 1, 0)  # an ended draft's row and state are not ours
    assert _state(*fresh) == ("awaiting_review", 1, 1)
    assert _lab_state(stale_lab) == ("expired", False)  # nobody confirmed it: the values go
    assert _lab_state(fresh_lab) == ("awaiting_confirmation", True)
    assert _pairs(ended[0], fresh[0]) == [fresh[0]]
    row = _audit_row(seq)
    assert (row["action"], row["details"]["drafts_ended"], row["details"]["mappings_deleted"]) == (
        "retention.run",
        1,
        2,
    )


def test_a_mapping_that_gains_a_value_after_the_plan_is_kept(db: None) -> None:
    draft = _seed("revived", "p-b", waiting=False, old_map=True)
    with psycopg.connect(retention_conninfo(Settings())) as conn:
        plan = retention.plan_retention(conn, NOW, DAYS)
    assert draft[1] in plan.encounters
    settings = Settings()  # the encounter is used again before the plan is applied
    PostgresStore(app_conninfo(settings), settings.deid_mapping_key).surrogate_for(
        draft[1], "PERSON", "Another Synthetic Person"
    )
    idle = NOW - timedelta(days=DAYS["deid_mapping_idle_days"])
    entry = AuditEntry(actor="retention-job", role="operator", action="retention.run")
    _apply(plan, "expired", entry, idle)
    assert _state(*draft)[2] == 2


def test_erasure_removes_one_patients_mappings_and_waiting_drafts(db: None) -> None:
    settings = Settings()
    waiting = _seed("p1-waiting", "ret-p1")
    ended = _seed("p1-ended", "ret-p1", waiting=False)
    other = _seed("p2", "ret-p2")
    lab, other_lab = _lab("p1", "ret-p1"), _lab("p2", "ret-p2")
    _edit_pair(ended[0])
    _edit_pair(other[0])
    store = PostgresStore(app_conninfo(settings), settings.deid_mapping_key)
    assert store.original_for(waiting[1], "PERSON_1") == "Synthetic Person"
    assert retention.main(["erase", "ret-p1", "--request", "DSR-1", "--by", "admin-demo"]) == 0
    assert _state(*waiting) == ("awaiting_review", 1, 1)  # a dry run changes nothing
    assert (
        retention.main(["erase", "ret-p1", "--request", "DSR-1", "--by", "admin-demo", "--apply"])
        == 0
    )
    assert _state(*waiting) == ("erased", 0, 0)
    assert _state(*ended) == ("approved", 1, 0)
    assert _state(*other) == ("awaiting_review", 1, 1)
    assert _lab_state(lab) == ("erased", False)
    assert _lab_state(other_lab) == ("awaiting_confirmation", True)
    assert _pairs(ended[0], other[0]) == [other[0]]
    assert store.original_for(waiting[1], "PERSON_1") is None  # nothing left to re-identify
    assert store.surrogate_for(waiting[1], "PERSON", "New Synthetic") == "PERSON_1"
    with psycopg.connect(owner_conninfo(settings), row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT * FROM audit_log WHERE action = 'gdpr.erasure' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert (row["actor"], row["resource_id"]) == ("admin-demo", "ret-p1")
    assert row["details"] == {
        "request": "DSR-1",
        "drafts_ended": 1,
        "lab_results_ended": 1,
        "edit_pairs_deleted": 1,
        "encounters": 2,
        "mappings_deleted": 2,
        "by_type": {"PERSON": 2},
    }
    assert AuditLog(owner_conninfo(settings), settings.audit_chain_key).verify().ok


def test_no_deletion_without_its_audit_row(db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    draft = _seed("atomic", "ret-p3")

    def broken(*_: Any) -> int:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(AuditLog, "append", broken)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        retention.main(["erase", "ret-p3", "--request", "DSR-2", "--by", "admin-demo", "--apply"])
    assert _state(*draft) == ("awaiting_review", 1, 1)


@pytest.mark.parametrize(
    "args",
    [
        ["erase", "ret-p1", "--request", "Jane Doe asked", "--by", "admin-demo"],  # free text
        ["erase", "ret-p1", "--request", "DSR-3", "--by", "dr-demo"],  # not an admin
        ["erase", "ret p1", "--request", "DSR-3", "--by", "admin-demo"],
    ],
)
def test_erasure_requests_are_checked(args: list[str], db: None) -> None:
    with pytest.raises(SystemExit):
        retention.main(args)


def test_each_login_can_do_only_its_part(db: None) -> None:
    settings = Settings()
    _seed("rights", "ret-p4")
    with psycopg.connect(retention_conninfo(settings)) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # append-only: no grant
            conn.execute("DELETE FROM audit_log WHERE seq = (SELECT max(seq) FROM audit_log)")
        conn.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE deid_mappings SET surrogate = 'X' WHERE encounter_id LIKE 'ret-%'")
    with (
        psycopg.connect(app_conninfo(settings)) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("DELETE FROM deid_mappings WHERE encounter_id LIKE 'ret-it-%'")
    with (
        psycopg.connect(app_conninfo(settings)) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("DELETE FROM edit_pairs WHERE draft_id LIKE 'ret-it-%'")


def _waiting_draft_with_content(name: str, patient: str) -> tuple[str, str]:
    """A draft made by the real graph (scripted model) whose saved state mentions a surrogate."""
    from agents.graph import Agents
    from tests.unit.test_agent_graph import FakeTools, ScriptedChat

    settings = Settings()
    draft_id, encounter = f"{PREFIX}draft-{name}", f"{PREFIX}enc-{name}"
    surrogate = PostgresStore(app_conninfo(settings), settings.deid_mapping_key).surrogate_for(
        encounter, "PERSON", "Ada Synthetic"
    )
    transcript = ["DOCTOR: What brings you in?", f"PATIENT: I am {surrogate}, thirsty for weeks."]
    reply = {
        "statements": [{"section": "subjective", "text": f"{surrogate} is thirsty.", "turns": [1]}]
    }
    start = {
        "mode": "scribe",
        "encounter_id": encounter,
        "patient_id": patient,
        "transcript": transcript,
    }
    with psycopg.connect(app_conninfo(settings), autocommit=True, row_factory=dict_row) as conn:
        agents = Agents(ScriptedChat(note=[reply]), FakeTools([]), alias=lambda t: f"alias-{t}")
        graph = agents.build(PostgresSaver(conn))
        out = graph.invoke(start, {"configurable": {"thread_id": draft_id}})
    assert out.get("__interrupt__"), out
    PostgresDrafts(app_conninfo(settings)).add(Draft(draft_id, patient, encounter, "dr-demo"))
    return draft_id, encounter


def test_an_access_request_copies_one_patients_data_and_nothing_else(db: None) -> None:
    settings = Settings()
    patient = f"ret-p5-{uuid.uuid4().hex[:8]}"  # the audit log keeps every earlier run's rows
    waiting = _waiting_draft_with_content("p5-waiting", patient)
    ended = _seed("p5-ended", patient, waiting=False)  # its mapping holds "Synthetic Person"
    other = _seed("p6", "ret-p6")
    PostgresStore(app_conninfo(settings), settings.deid_mapping_key).surrogate_for(
        other[1], "PERSON", "Cy Unrelated"
    )
    AuditLog(app_conninfo(settings), settings.audit_chain_key).append(
        AuditEntry(actor="dr-demo", role="doctor", action="fhir.read", resource_id=patient)
    )
    pending_lab = _lab("p5", patient)
    _edit_pair(ended[0])  # its mapping holds PERSON_1 = "Synthetic Person"
    path = retention.ACCESS_DIR / f"DSR-A1-{patient}.json"
    try:
        assert retention.main(["access", patient, "--request", "DSR-A1", "--by", "admin-demo"]) == 0
        text = path.read_text(encoding="utf-8")
        report = json.loads(text)
        assert sorted(d["draft_id"] for d in report["drafts"]) == sorted([waiting[0], ended[0]])
        [held] = [d for d in report["drafts"] if d["draft_id"] == waiting[0]]
        assert (
            held["awaiting_review"]["transcript"][1]
            == "PATIENT: I am Ada Synthetic, thirsty for weeks."
        )
        assert held["awaiting_review"]["statements"] == [
            {"section": "subjective", "text": "Ada Synthetic is thirsty."}
        ]
        originals = {i["original"] for i in report["identifiers_held"]}
        assert originals == {"Ada Synthetic", "Synthetic Person"}
        assert "fhir.read" in {row["action"] for row in report["access_log"]}
        [lab_copy] = report["lab_results"]
        assert lab_copy["lab_id"] == pending_lab
        assert lab_copy["awaiting_confirmation"]["observations"][0]["valueQuantity"]["value"] == 131
        [pair] = report["edit_pairs"]
        assert pair["after"] == [
            {"section": "plan", "text": "Synthetic Person to rest for a week."}
        ]
        assert "Cy Unrelated" not in text  # another patient's identifiers
        assert other[0] not in text  # and drafts
    finally:
        path.unlink(missing_ok=True)
    with psycopg.connect(owner_conninfo(settings), row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT * FROM audit_log WHERE action = 'gdpr.access' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert (row["actor"], row["resource_id"]) == ("admin-demo", patient)
    assert row["details"] == {
        "request": "DSR-A1",
        "drafts": 2,
        "lab_results": 1,
        "edit_pairs": 1,
        "identifiers": 2,
        "audit_rows": 1,
    }
    assert "Ada Synthetic" not in json.dumps(row, default=str)  # the log holds counts, not data
    assert AuditLog(owner_conninfo(settings), settings.audit_chain_key).verify().ok
