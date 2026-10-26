"""Retention limits and GDPR erasure (GDPR Art. 5(1)(e) and 17; SPEC section 8; ADR-0022).

  uv run python -m scripts.retention [--apply]
      what config/retention.yaml's limits remove; with --apply, remove it
  uv run python -m scripts.retention erase <patient id> --request <ref> --by <admin> [--apply]
      one patient's erasure request (the request reference is a ticket id, never a name)

Without --apply nothing changes. An applied run writes one audit row with counts, in the same
transaction as the deletions. Connects as the "retention" login (scripts/migrate.py): it may delete
de-ID mappings and checkpoints, end drafts and append to the audit log, nothing else.

Removed: drafts nobody reviewed in time (ended "expired", checkpoints deleted) and de-ID mappings of
idle encounters, the only place ClinScribe keeps original PHI (encrypted). Always whole encounters:
surrogate numbers count an encounter's rows, so a partial delete would hand a number out twice.
Erasure of one patient ends their drafts still awaiting review ("erased") and deletes the mapping of
every encounter their drafts used, whatever its age.
Kept: the audit log, the drafts list (pseudonymous outcome rows) and the FHIR record. Not reached:
lab values pending confirmation (the API's memory only), Ask and voice encounters (not tied to a
patient; the idle limit removes their mappings), de-identified traces.
"""

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import yaml

from apps.api.audit import AuditEntry, AuditLog
from apps.api.auth import users
from apps.api.drafts import WAITING
from config.db import retention_conninfo
from config.settings import Settings
from scripts.migrate import CHECKPOINT_TABLES

CONFIG = Path(__file__).resolve().parents[1] / "config" / "retention.yaml"
PATIENT_ID = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
REQUEST_REF = re.compile(r"^[A-Za-z0-9._-]{1,64}$")  # a ticket id: no free text, so no PHI


@dataclass
class Plan:
    drafts: list[str] = field(default_factory=list)  # awaiting review: to end
    encounters: list[str] = field(default_factory=list)  # whose whole mapping goes
    mappings: Counter[str] = field(default_factory=Counter)  # rows by entity type

    def summary(self) -> dict[str, Any]:
        return {
            "drafts_ended": len(self.drafts),
            "encounters": len(self.encounters),
            "mappings_deleted": sum(self.mappings.values()),
            "by_type": dict(sorted(self.mappings.items())),
        }


def limits(path: Path = CONFIG) -> dict[str, int]:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {k: int(cfg[k]) for k in ("drafts_awaiting_review_days", "deid_mapping_idle_days")}


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
    return Plan(expired, idle, _mapping_counts(conn, idle))


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
    return Plan(waiting, encounters, _mapping_counts(conn, encounters))


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
    return Plan(
        ended,
        sorted({str(e) for e, _ in deleted}),
        Counter(str(t) for _, t in deleted),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="remove (default: dry run)")
    sub = parser.add_subparsers(dest="command")
    erase = sub.add_parser("erase", help="one patient's erasure request")
    erase.add_argument("patient_id")
    erase.add_argument("--request", required=True, help="request reference (ticket id)")
    erase.add_argument("--by", required=True, help="the admin handling the request")
    erase.add_argument("--apply", action="store_true", dest="apply_erase")
    args = parser.parse_args(argv)
    settings = Settings()
    audit = AuditLog(retention_conninfo(settings), settings.audit_chain_key)
    with psycopg.connect(retention_conninfo(settings)) as conn:
        if args.command == "erase":
            if not PATIENT_ID.match(args.patient_id):
                parser.error("patient id: letters, digits, '-' and '.' only")
            if not REQUEST_REF.match(args.request):
                parser.error("--request: a ticket id (letters, digits, '.', '_', '-'), not text")
            if users().get(args.by) != "admin":
                parser.error(f"--by: {args.by!r} is not an admin in config/users.yaml")
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
