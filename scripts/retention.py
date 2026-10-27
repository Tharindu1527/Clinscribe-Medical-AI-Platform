"""Retention limits, GDPR access and erasure (GDPR Art. 5(1)(e), 15 and 17; SPEC section 8;
ADR-0022).

  uv run python -m scripts.retention [--apply]
      what config/retention.yaml's limits remove; with --apply, remove it
  uv run python -m scripts.retention erase <patient id> --request <ref> --by <admin> [--apply]
      one patient's erasure request (the request reference is a ticket id, never a name)
  uv run python -m scripts.retention access <patient id> --request <ref> --by <admin>
      one patient's access request: a copy of what ClinScribe holds, with the originals from the
      de-ID mapping, written to .artifacts/subject-access/ (git-ignored; it holds PHI), never
      printed; audited as gdpr.access with counts only

Without --apply nothing changes. An applied run writes one audit row with counts, in the same
transaction as the deletions. Connects as the "retention" login (scripts/migrate.py): it may delete
de-ID mappings and checkpoints, end drafts and append to the audit log, nothing else.

Removed: drafts nobody reviewed in time (ended "expired", checkpoints deleted), lab results nobody
confirmed in time (ended "expired", their values dropped) and de-ID mappings of
idle encounters, the only place ClinScribe keeps original PHI (encrypted). Always whole encounters:
surrogate numbers count an encounter's rows, so a partial delete would hand a number out twice.
Erasure of one patient ends their drafts and lab results still waiting ("erased") and deletes the
mapping of every encounter their drafts used, whatever its age.
Kept: the audit log, the drafts and lab-results lists (pseudonymous outcome rows) and the FHIR
record. Not reached: Ask and voice encounters (not tied to a patient; the idle limit removes their
mappings), de-identified traces.
"""

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import yaml
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row

from apps.api.audit import AuditEntry, AuditLog
from apps.api.auth import users
from apps.api.drafts import WAITING
from apps.api.labs import AWAITING
from config.db import retention_conninfo
from config.settings import Settings
from privacy.deid.engine import SURROGATE_RE
from privacy.deid.store import PostgresStore
from scripts.migrate import CHECKPOINT_TABLES

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "retention.yaml"
ACCESS_DIR = ROOT / ".artifacts" / "subject-access"  # git-ignored: the copies hold PHI
PATIENT_ID = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
REQUEST_REF = re.compile(r"^[A-Za-z0-9._-]{1,64}$")  # a ticket id: no free text, so no PHI


@dataclass
class Plan:
    drafts: list[str] = field(default_factory=list)  # awaiting review: to end
    encounters: list[str] = field(default_factory=list)  # whose whole mapping goes
    mappings: Counter[str] = field(default_factory=Counter)  # rows by entity type
    labs: list[str] = field(default_factory=list)  # lab results awaiting confirmation: to end

    def summary(self) -> dict[str, Any]:
        return {
            "drafts_ended": len(self.drafts),
            "lab_results_ended": len(self.labs),
            "encounters": len(self.encounters),
            "mappings_deleted": sum(self.mappings.values()),
            "by_type": dict(sorted(self.mappings.items())),
        }


def limits(path: Path = CONFIG) -> dict[str, int]:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    keys = (
        "drafts_awaiting_review_days",
        "lab_results_awaiting_confirmation_days",
        "deid_mapping_idle_days",
    )
    return {k: int(cfg[k]) for k in keys}


def _mapping_counts(conn: psycopg.Connection[Any], encounters: list[str]) -> Counter[str]:
    rows = conn.execute(
        "SELECT entity_type, count(*) FROM deid_mappings WHERE encounter_id = ANY(%s) "
        "GROUP BY entity_type",
        (encounters,),
    ).fetchall()
    return Counter({str(t): int(n) for t, n in rows})


def plan_retention(conn: psycopg.Connection[Any], now: datetime, days: dict[str, int]) -> Plan:
    draft_cutoff = now - timedelta(days=days["drafts_awaiting_review_days"])
    mapping_cutoff = now - timedelta(days=days["deid_mapping_idle_days"])
    expired = [
        str(r[0])
        for r in conn.execute(
            "SELECT draft_id FROM drafts WHERE status = %s AND created_at < %s ORDER BY created_at",
            (WAITING, draft_cutoff),
        )
    ]
    still_waiting = {
        str(r[0])
        for r in conn.execute(
            "SELECT encounter_id FROM drafts WHERE status = %s AND NOT (draft_id = ANY(%s))",
            (WAITING, expired),
        )
    }
    idle = [
        str(r[0])
        for r in conn.execute(
            "SELECT encounter_id FROM deid_mappings GROUP BY encounter_id "
            "HAVING max(created_at) < %s ORDER BY encounter_id",
            (mapping_cutoff,),
        )
        if str(r[0]) not in still_waiting  # a waiting draft still needs its originals
    ]
    lab_cutoff = now - timedelta(days=days["lab_results_awaiting_confirmation_days"])
    labs = [
        str(r[0])
        for r in conn.execute(
            "SELECT lab_id FROM lab_results WHERE status = %s AND created_at < %s "
            "ORDER BY created_at",
            (AWAITING, lab_cutoff),
        )
    ]
    return Plan(expired, idle, _mapping_counts(conn, idle), labs)


def plan_erasure(conn: psycopg.Connection[Any], patient_id: str) -> Plan:
    rows = conn.execute(
        "SELECT draft_id, encounter_id, status FROM drafts WHERE patient_id = %s "
        "ORDER BY created_at",
        (patient_id,),
    ).fetchall()
    waiting = [str(d) for d, _, s in rows if s == WAITING]
    used = sorted({str(e) for _, e, _ in rows})
    encounters = [
        str(r[0])
        for r in conn.execute(
            "SELECT DISTINCT encounter_id FROM deid_mappings WHERE encounter_id = ANY(%s) "
            "ORDER BY encounter_id",
            (used,),
        )
    ]
    labs = [
        str(r[0])
        for r in conn.execute(
            "SELECT lab_id FROM lab_results WHERE patient_id = %s AND status = %s",
            (patient_id, AWAITING),
        )
    ]
    return Plan(waiting, encounters, _mapping_counts(conn, encounters), labs)


def apply(
    conn: psycopg.Connection[Any], plan: Plan, ended_as: str, idle_before: datetime | None = None
) -> Plan:
    """Delete what the plan names; returns what was actually removed. Run it inside the caller's
    transaction, with the audit row. Each encounter is locked as the de-ID service locks it, so no
    value is added mid-delete; with `idle_before` (retention) an encounter that gained a value since
    the plan is kept."""
    for encounter in sorted(plan.encounters):
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (encounter,))
    ended = [
        str(r[0])
        for r in conn.execute(
            "UPDATE drafts SET status = %s, ended_at = %s WHERE draft_id = ANY(%s) AND status = %s "
            "RETURNING draft_id",
            (ended_as, datetime.now(UTC), plan.drafts, WAITING),
        )
    ]
    for table in CHECKPOINT_TABLES:
        conn.execute(
            f"DELETE FROM {table} WHERE thread_id = ANY(%s)",  # noqa: S608 (fixed names)
            (ended,),
        )
    keep_active = (
        " AND encounter_id IN (SELECT encounter_id FROM deid_mappings GROUP BY encounter_id"
        " HAVING max(created_at) < %(idle)s)"
        if idle_before
        else ""
    )
    deleted = conn.execute(
        "DELETE FROM deid_mappings WHERE encounter_id = ANY(%(enc)s)"  # noqa: S608 (fixed text)
        + keep_active
        + " RETURNING encounter_id, entity_type",
        {"enc": plan.encounters, "idle": idle_before},
    ).fetchall()
    labs = [
        str(r[0])
        for r in conn.execute(  # the values go; the row keeps the outcome
            "UPDATE lab_results SET status = %s, payload = NULL, ended_at = %s "
            "WHERE lab_id = ANY(%s) AND status = %s RETURNING lab_id",
            (ended_as, datetime.now(UTC), plan.labs, AWAITING),
        )
    ]
    return Plan(
        ended,
        sorted({str(e) for e, _ in deleted}),
        Counter(str(t) for _, t in deleted),
        labs,
    )


ABOUT = {
    "controller_note": "ClinScribe's own processing only. The clinical record (approved notes, lab "
    "results) is the clinic's record in the EHR (FHIR); a copy of it comes from there.",
    "purposes": [
        "drafting clinical notes from consultations for a doctor's review (Scribe)",
        "answering clinicians' questions with cited evidence (Ask)",
        "reading lab reports into results a doctor confirms (Lab)",
    ],
    "recipients": [
        "model providers behind the gateway (Gemini, Groq, OpenRouter) and a local model: "
        "de-identified text only",
        "speech recognition (Deepgram) in voice mode: consultation audio",
        "tracing (Langfuse Cloud, EU): de-identified, redacted spans only",
        "details: docs/compliance/baa_vendor_matrix.md",
    ],
    "rights": "erasure: an admin runs `just erase` (ADR-0022); the audit log is kept "
    "(accountability)",
}


def subject_access(
    conn: psycopg.Connection[Any],
    store: PostgresStore,
    saver: PostgresSaver,
    patient_id: str,
) -> dict[str, Any]:
    """Everything ClinScribe holds about one patient: drafts (a waiting draft's transcript and note
    re-identified), the de-ID mapping's originals, and the audit rows that name the patient, their
    drafts or encounters (who read or changed what, when)."""
    drafts = conn.execute(
        "SELECT draft_id, encounter_id, created_by, created_at, status, ended_at, resource_id "
        "FROM drafts WHERE patient_id = %s ORDER BY created_at",
        (patient_id,),
    ).fetchall()
    encounters = sorted({str(d[1]) for d in drafts})
    held = {e: store.entries(e) for e in encounters}
    originals = {e: {sur: orig for _, sur, orig in rows} for e, rows in held.items()}

    def restore(text: str, encounter: str) -> str:
        return SURROGATE_RE.sub(lambda m: originals[encounter].get(m.group(0), m.group(0)), text)

    items = []
    for draft_id, encounter, by, created, status, ended, resource in drafts:
        item: dict[str, Any] = {
            "draft_id": draft_id,
            "encounter_id": encounter,
            "created_by": by,
            "created_at": created,
            "status": status,
            "ended_at": ended,
            "record": resource,
        }
        if status == WAITING:  # ended drafts keep no content (ADR-0016)
            saved = saver.get_tuple({"configurable": {"thread_id": draft_id}})
            values = saved.checkpoint["channel_values"] if saved else {}
            note = values.get("note") or {}
            item["awaiting_review"] = {
                "transcript": [restore(turn, encounter) for turn in values.get("transcript", [])],
                "statements": [
                    {"section": s["section"], "text": restore(s["text"], encounter)}
                    for s in note.get("statements", [])
                ],
            }
        items.append(item)
    ids = [str(d[0]) for d in drafts]
    log = conn.execute(
        "SELECT seq, ts, actor, role, action, resource_type, resource_id, encounter_id "
        "FROM audit_log WHERE resource_id = %s OR resource_id = ANY(%s) "
        "OR encounter_id = ANY(%s) OR details->>'draft_id' = ANY(%s) ORDER BY seq",
        (patient_id, ids, encounters, ids),
    ).fetchall()
    labs = conn.execute(
        "SELECT lab_id, created_by, created_at, status, ended_at, written, payload "
        "FROM lab_results WHERE patient_id = %s ORDER BY created_at",
        (patient_id,),
    ).fetchall()
    lab_ids = [str(r[0]) for r in labs]
    log = [
        *log,
        *conn.execute(
            "SELECT seq, ts, actor, role, action, resource_type, resource_id, encounter_id "
            "FROM audit_log WHERE resource_id = ANY(%s) AND NOT (resource_id = %s) ORDER BY seq",
            (lab_ids, patient_id),
        ).fetchall(),
    ]
    columns = ("seq", "ts", "actor", "role", "action", "resource_type", "resource_id", "encounter")
    return {
        "patient_id": patient_id,
        **ABOUT,
        "retention": limits(),
        "drafts": items,
        "identifiers_held": [
            {"encounter_id": e, "type": kind, "surrogate": sur, "original": orig}
            for e, rows in held.items()
            for kind, sur, orig in rows
        ],
        "lab_results": [
            {
                "lab_id": lab_id,
                "created_by": by,
                "created_at": created,
                "status": status,
                "ended_at": ended,
                "observations_written": written,
                "awaiting_confirmation": payload,  # None once it ended: the values are in FHIR
            }
            for lab_id, by, created, status, ended, written, payload in labs
        ],
        "access_log": [dict(zip(columns, row, strict=True)) for row in sorted(log)],
    }


def _check_request(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not PATIENT_ID.match(args.patient_id):
        parser.error("patient id: letters, digits, '-' and '.' only")
    if not REQUEST_REF.match(args.request):
        parser.error("--request: a ticket id (letters, digits, '.', '_', '-'), not text")
    if users().get(args.by) != "admin":
        parser.error(f"--by: {args.by!r} is not an admin in config/users.yaml")


def access(args: argparse.Namespace, settings: Settings, audit: AuditLog) -> int:
    store = PostgresStore(retention_conninfo(settings), settings.deid_mapping_key)
    with (
        psycopg.connect(retention_conninfo(settings)) as conn,
        psycopg.connect(retention_conninfo(settings), autocommit=True, row_factory=dict_row) as raw,
    ):
        report = subject_access(conn, store, PostgresSaver(raw), args.patient_id)
        counts = {
            "drafts": len(report["drafts"]),
            "lab_results": len(report["lab_results"]),
            "identifiers": len(report["identifiers_held"]),
            "audit_rows": len(report["access_log"]),
        }
        seq = audit.append(  # before the file exists: a failed write is recorded as an attempt
            AuditEntry(
                actor=args.by,
                role="admin",
                action="gdpr.access",
                resource_type="Patient",
                resource_id=args.patient_id,
                details={"request": args.request, **counts},
            ),
            conn,
        )
        conn.commit()
    report = {"request": args.request, "generated_by": args.by, **report}
    report["generated_at"] = datetime.now(UTC)
    ACCESS_DIR.mkdir(parents=True, exist_ok=True)
    path = ACCESS_DIR / f"{args.request}-{args.patient_id}.json"
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"gdpr.access: {counts}; audit row {seq}; written to {path} (holds PHI: hand it over")
    print("securely, then delete it)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="remove (default: dry run)")
    sub = parser.add_subparsers(dest="command")
    erase = sub.add_parser("erase", help="one patient's erasure request")
    erase.add_argument("patient_id")
    erase.add_argument("--request", required=True, help="request reference (ticket id)")
    erase.add_argument("--by", required=True, help="the admin handling the request")
    erase.add_argument("--apply", action="store_true", dest="apply_erase")
    copy = sub.add_parser("access", help="one patient's access request (a copy of their data)")
    copy.add_argument("patient_id")
    copy.add_argument("--request", required=True, help="request reference (ticket id)")
    copy.add_argument("--by", required=True, help="the admin handling the request")
    args = parser.parse_args(argv)
    if args.command in ("erase", "access"):
        _check_request(parser, args)
    settings = Settings()
    audit = AuditLog(retention_conninfo(settings), settings.audit_chain_key)
    if args.command == "access":
        return access(args, settings, audit)
    with psycopg.connect(retention_conninfo(settings)) as conn:
        if args.command == "erase":
            plan = plan_erasure(conn, args.patient_id)
            action, run, ended_as, idle_before = "gdpr.erasure", args.apply_erase, "erased", None

            def entry(done: Plan) -> AuditEntry:
                return AuditEntry(
                    actor=args.by,
                    role="admin",
                    action=action,
                    resource_type="Patient",
                    resource_id=args.patient_id,
                    details={"request": args.request, **done.summary()},
                )
        else:
            days, now = limits(), datetime.now(UTC)
            plan = plan_retention(conn, now, days)
            action, run, ended_as = "retention.run", args.apply, "expired"
            idle_before = now - timedelta(days=days["deid_mapping_idle_days"])

            def entry(done: Plan) -> AuditEntry:
                return AuditEntry(
                    actor="retention-job",
                    role="operator",
                    action=action,
                    details={"limits": days, **done.summary()},
                )

        print(f"{action}: {plan.summary()}")
        if not (run or args.apply):
            print("dry run: nothing changed (add --apply)")
            return 0
        with conn.transaction():
            done = apply(conn, plan, ended_as, idle_before)
            seq = audit.append(entry(done), conn)
    print(f"applied: {done.summary()}; audit row {seq}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
