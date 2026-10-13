"""Phase 2 ablation report and gate criteria, from the committed runs and answer rows (task 12)."""

from evals.rag.ablation import BASELINE, CHOSEN, REPORTS, STEPS, gate_checks, per_question


def test_every_ablation_step_has_a_run_for_the_current_golden_set() -> None:
    systems = {s for _, _, baseline, candidate, _ in STEPS for s in (baseline, candidate)}
    for system in systems:
        assert (REPORTS / "runs" / f"{system}.json").exists(), system
        assert len(per_question(system)) == 209, system  # raises if the golden set changed


def test_phase2_gate_criteria_pass_on_the_committed_results() -> None:
    checks = gate_checks()
    assert [name for name, _, _ in checks] == [
        "recall@10: chosen beats dense-only",
        "answer correctness: chosen beats dense-only",
        "faithfulness: chosen not worse than dense-only by > 0.05",
    ]
    failed = [f"{name}: {evidence}" for name, ok, evidence in checks if not ok]
    assert not failed, failed
    assert (BASELINE, CHOSEN) == ("dense", "hybrid_colbert_ctx")
