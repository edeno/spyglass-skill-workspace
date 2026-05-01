"""Synthetic smoke test for the eval-sweep plotting pipeline.

Run with the same environment used for plotting, for example:

    uv run python3 tools/tests/smoke.py
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def make_grading(eval_dir: Path, cond: str, passed: bool) -> None:
    write_json(
        eval_dir / cond / "grading.json",
        {
            "expectations": [
                {"text": "behavioral_check: smoke behavior", "passed": passed},
                {"text": "required_substring: smoke", "passed": passed},
            ]
        },
    )
    write_json(
        eval_dir / cond / "timing.json",
        {"total_tokens": 1000 if cond == "with_skill" else 600},
    )
    write_json(
        eval_dir / cond / "eval_metadata.json",
        {
            "eval_id": 1,
            "eval_name": "smoke-routing",
            "stage": "pipeline-usage",
            "tier": "joins",
            "difficulty": "easy",
        },
    )
    out = eval_dir / cond / "outputs" / "response.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("smoke\n")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="spyglass-tools-smoke-") as tmp:
        base = Path(tmp)
        skill = base / "spyglass-skill"
        run = base / "run"
        out = base / "summary"

        run_evals = {
            "evals": [
                {
                    "id": 1,
                    "name": "smoke-routing",
                    "stage": "pipeline-usage",
                    "tier": "joins",
                    "difficulty": "easy",
                    "expected_refs": {
                        "required": ["common_tables.md"],
                        "optional": [],
                        "distractor": ["spyglassmixin_methods.md"],
                    },
                    "expected_scripts": {
                        "required": ["code_graph.py"],
                        "optional": [],
                        "distractor": ["db_graph.py"],
                    },
                }
            ]
        }
        drifted_evals = {
            "evals": [
                {
                    "id": 1,
                    "name": "smoke-routing-drifted",
                    "stage": "drifted-stage",
                    "tier": "drifted-tier",
                    "difficulty": "hard",
                    "expected_refs": {
                        "required": ["wrong_reference.md"],
                        "optional": [],
                        "distractor": [],
                    },
                    "expected_scripts": {
                        "required": ["db_graph.py"],
                        "optional": [],
                        "distractor": [],
                    },
                },
                {
                    "id": 2,
                    "name": "not-run",
                    "stage": "not-run-stage",
                    "tier": "not-run-tier",
                    "difficulty": "easy",
                },
            ]
        }
        write_json(skill / "skills/spyglass/evals/evals.json", drifted_evals)
        (skill / "skills/spyglass/SKILL.md").write_text("smoke\n")

        bench = {
            "configurations": {
                "with_skill": {
                    "n_runs": 1,
                    "evals_full_pass": 0,
                    "expectations_passed": 1,
                    "expectations_total": 2,
                    "tokens_total": 1000,
                    "tokens_mean": 1000,
                    "duration_mean_s": 1.0,
                    "eval_results": [
                        {
                            "eval_id": 1,
                            "eval_name": "smoke-routing",
                            "all_passed": False,
                            "passed_count": 1,
                            "total": 2,
                        }
                    ],
                },
                "without_skill": {
                    "n_runs": 1,
                    "evals_full_pass": 0,
                    "expectations_passed": 0,
                    "expectations_total": 2,
                    "tokens_total": 600,
                    "tokens_mean": 600,
                    "duration_mean_s": 0.8,
                    "eval_results": [
                        {
                            "eval_id": 1,
                            "eval_name": "smoke-routing",
                            "all_passed": False,
                            "passed_count": 0,
                            "total": 2,
                        }
                    ],
                },
            }
        }
        write_json(run / "iteration-1/benchmark.json", bench)
        write_json(run / "run.json", {"batches": {"1": {"label": "B1\nsmoke"}}})
        write_json(run / "summary/data/evals_snapshot.json", run_evals)

        eval_dir = run / "iteration-1/eval-001-smoke-routing"
        make_grading(eval_dir, "with_skill", False)
        make_grading(eval_dir, "without_skill", False)
        write_json(
            run / "iteration-1/.agent_map.json",
            {
                "agent-ws": "iteration-1/eval-001-smoke-routing/with_skill",
                "agent-bs": "iteration-1/eval-001-smoke-routing/without_skill",
            },
        )
        transcript = {
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {
                            "file_path": str(
                                skill / "skills/spyglass/references/common_tables.md"
                            )
                        },
                    },
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {
                            "command": (
                                "python skills/spyglass/scripts/code_graph.py "
                                "describe Session"
                            )
                        },
                    },
                ]
            }
        }
        snapshot = run / "transcripts_snapshot"
        snapshot.mkdir(parents=True)
        (snapshot / "agent-ws.jsonl").write_text(json.dumps(transcript) + "\n")

        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/make_plots.py"),
                "--run",
                str(run),
                "--out",
                str(out),
                "--skill-root",
                str(skill),
            ],
            check=True,
            cwd=ROOT,
        )

        required = [
            "INDEX.md",
            "data/summary_manifest.json",
            "figures/appendix_failure_taxonomy_placeholder.png",
            "data/fix_priority.csv",
            "data/routing_diagnosis.csv",
            "data/reference_expected_by_eval.csv",
            "data/script_expected_by_eval.csv",
            "data/reference_call_confusion.csv",
            "data/script_call_confusion.csv",
            "data/per_eval_routing.csv",
        ]
        missing = [name for name in required if not (out / name).exists()]
        if missing:
            raise AssertionError(f"missing outputs: {missing}")
        for staged in (out / ".data_tmp", out / ".figures_tmp", out / ".INDEX.tmp"):
            if staged.exists():
                raise AssertionError(f"staged output was not committed: {staged}")

        with (out / "data/fix_priority.csv").open() as f:
            header = next(csv.reader(f))
        expected_prefix = [
            "eval_id",
            "batch",
            "eval_name",
            "stage",
            "tier",
            "difficulty",
        ]
        if header[:6] != expected_prefix:
            raise AssertionError(f"bad fix_priority prefix: {header[:6]}")

        manifest = json.loads((out / "data/summary_manifest.json").read_text())
        manifest_files = {row["filename"] for row in manifest}
        if (
            "INDEX.md" not in manifest_files
            or "figures/appendix_failure_taxonomy_placeholder.png" not in manifest_files
        ):
            raise AssertionError("manifest missing generated index or failure-taxonomy plot")

        cumulative = json.loads((out / "data/cumulative_summary.json").read_text())
        if cumulative["delta"]["extra_tokens_total"] != 400:
            raise AssertionError(f"bad extra-token delta: {cumulative['delta']}")
        if cumulative["combined"]["tokens_total"] != 1600:
            raise AssertionError(f"bad combined-token total: {cumulative['combined']}")

        with (out / "data/reference_expected_by_eval.csv").open(newline="") as f:
            rows = list(csv.DictReader(f))
        if rows[0]["required"] != "common_tables.md":
            raise AssertionError("routing annotations drifted from run snapshot")

        with (out / "data/eval_coverage.csv").open(newline="") as f:
            rows = list(csv.DictReader(f))
        if rows != [{"stage": "pipeline-usage", "tier": "joins", "n_evals": "1"}]:
            raise AssertionError(f"coverage included evals outside the run: {rows}")

        failure_out = base / "failure-summary"
        failure_run = base / "failure-run"
        (failure_run / "iteration-1").mkdir(parents=True)
        existing_figure = failure_out / "figures/q01_how_much_does_the_skill_help.png"
        existing_figure.parent.mkdir(parents=True)
        existing_figure.write_text("sentinel\n")
        failed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/make_plots.py"),
                "--run",
                str(failure_run),
                "--out",
                str(failure_out),
                "--skill-root",
                str(base / "missing-skill"),
            ],
            check=False,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if failed.returncode == 0:
            raise AssertionError(
                f"expected invalid skill root to fail; output:\n{failed.stdout}"
            )
        if existing_figure.read_text() != "sentinel\n":
            raise AssertionError("failed run modified existing figures")

        existing_data = failure_out / "data/evals_snapshot.json"
        existing_data.parent.mkdir(parents=True, exist_ok=True)
        existing_data.write_text("data sentinel\n")
        existing_index = failure_out / "INDEX.md"
        existing_index.write_text("index sentinel\n")
        late_failure_run = base / "late-failure-run"
        write_json(
            late_failure_run / "iteration-1/benchmark.json",
            {
                "configurations": {
                    "with_skill": {
                        "n_runs": 0,
                        "evals_full_pass": 0,
                        "expectations_passed": 0,
                        "expectations_total": 0,
                        "tokens_total": 0,
                        "tokens_mean": 0,
                        "duration_mean_s": 0,
                        "eval_results": [],
                    },
                    "without_skill": {
                        "n_runs": 0,
                        "evals_full_pass": 0,
                        "expectations_passed": 0,
                        "expectations_total": 0,
                        "tokens_total": 0,
                        "tokens_mean": 0,
                        "duration_mean_s": 0,
                        "eval_results": [],
                    },
                }
            },
        )
        failed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/make_plots.py"),
                "--run",
                str(late_failure_run),
                "--out",
                str(failure_out),
                "--skill-root",
                str(skill),
            ],
            check=False,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if failed.returncode == 0:
            raise AssertionError(
                f"expected zero-run benchmark to fail; output:\n{failed.stdout}"
            )
        if existing_figure.read_text() != "sentinel\n":
            raise AssertionError("late failed run modified existing figures")
        if existing_data.read_text() != "data sentinel\n":
            raise AssertionError("late failed run modified existing data")
        if existing_index.read_text() != "index sentinel\n":
            raise AssertionError("late failed run modified existing index")

        _smoke_compare_runs(base)

    print("smoketest passed")


def _build_compare_run(
    run_dir: Path,
    *,
    eval_results: dict[str, list[dict]],
    timing_by_eid_cond: dict[tuple[int, str], int | None],
    edit_to_evals: dict[str, list[int]] | None = None,
    failure_taxonomy: list[dict[str, str]] | None = None,
    eval_catalog: list[dict] | None = None,
    transcripts: dict[tuple[int, str], dict] | None = None,
) -> None:
    """Build a minimal synthetic run that compare_runs.py can read.

    eval_results is keyed by condition ("with_skill" / "without_skill") and
    each entry must declare {eval_id, eval_name, all_passed, passed_count, total}.
    Use a missing eval_id under one condition to simulate a partial dispatch.
    timing_by_eid_cond[(eid, cond)] = total_tokens, or None to omit timing.json
    for that cell (exercises the token-coverage block).
    """
    bench = {
        "configurations": {
            cond: {
                "n_runs": len(rows),
                "evals_full_pass": sum(1 for r in rows if r["all_passed"]),
                "expectations_passed": sum(r["passed_count"] for r in rows),
                "expectations_total": sum(r["total"] for r in rows),
                "tokens_total": 0,
                "tokens_mean": 0,
                "duration_mean_s": 0.0,
                "eval_results": rows,
            }
            for cond, rows in eval_results.items()
        }
    }
    write_json(run_dir / "iteration-1/benchmark.json", bench)
    run_meta: dict = {
        "run_id": run_dir.name,
        "skill_commit_at_sweep_end": f"sha-{run_dir.name}",
    }
    if edit_to_evals is not None:
        run_meta["subset"] = {"edit_to_evals": edit_to_evals}
    write_json(run_dir / "run.json", run_meta)
    seen_eids: set[int] = set()
    for cond, rows in eval_results.items():
        for r in rows:
            eid = r["eval_id"]
            seen_eids.add(eid)
            eval_dir = run_dir / "iteration-1" / f"eval-{eid:03d}-{r['eval_name']}"
            write_json(
                eval_dir / cond / "eval_metadata.json",
                {
                    "eval_id": eid,
                    "eval_name": r["eval_name"],
                    "stage": "pipeline-usage",
                    "tier": "joins",
                    "difficulty": "easy",
                },
            )
            tokens = timing_by_eid_cond.get((eid, cond))
            if tokens is not None:
                write_json(eval_dir / cond / "timing.json", {"total_tokens": tokens})
    if failure_taxonomy:
        path = run_dir / "summary/data/failure_taxonomy.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["eval_id", "failure_type", "notes"],
                lineterminator="\n",
            )
            writer.writeheader()
            for row in failure_taxonomy:
                writer.writerow(row)

    if eval_catalog is not None:
        write_json(
            run_dir / "evals_snapshot.json",
            {"source": str(run_dir / "evals_snapshot.json"), "evals": eval_catalog},
        )

    if transcripts:
        agent_map: dict[str, str] = {}
        snapshot_dir = run_dir / "transcripts_snapshot"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        # Use a synthetic skill path so the transcript parser's path-shape
        # heuristics fire ("skills/spyglass/references/", etc.). The actual
        # location only matters for the parser's substring checks.
        skill_root_in_transcript = "/synthetic/spyglass-skill"
        for (eid, cond), spec in transcripts.items():
            aid = f"agent-{eid}-{cond}"
            eval_dir_name = next(
                f"eval-{eid:03d}-{r['eval_name']}"
                for r in eval_results.get(cond, [])
                if r["eval_id"] == eid
            )
            agent_map[aid] = f"iteration-1/{eval_dir_name}/{cond}"
            content = []
            for ref in spec.get("ref_opens", []):
                content.append(
                    {
                        "type": "tool_use",
                        "name": "Read",
                        "input": {
                            "file_path": (
                                f"{skill_root_in_transcript}/skills/spyglass/references/{ref}"
                            )
                        },
                    }
                )
            for script in spec.get("script_executions", []):
                content.append(
                    {
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {
                            "command": (
                                f"python {skill_root_in_transcript}/skills/spyglass/scripts/{script}"
                            )
                        },
                    }
                )
            transcript_obj = {"message": {"content": content}}
            (snapshot_dir / f"{aid}.jsonl").write_text(json.dumps(transcript_obj) + "\n")
        write_json(run_dir / "iteration-1/.agent_map.json", agent_map)


def _smoke_compare_runs(base: Path) -> None:
    """End-to-end smoke for tools/compare_runs.py.

    Exercises: overlap audit (with old_only/new_only), ws-only rubric drift
    (split flags), bs-side partial dispatch (missing cells flow through),
    many-to-many edit_to_evals (one eval under two edits), token coverage
    when timing.json is missing on one side, atomic commit (no leftover
    staging dirs), and rollback when a comparison fails after staging.
    """
    old_run = base / "old-run"
    new_run = base / "new-run"
    out = base / "comparison-out"

    # Overlap = {1, 2, 3, 4}; old has extra eval 9; new has extra eval 8.
    # Eval 1: stable_pass on ws, stable_pass on bs.
    # Eval 2: ws improved (fail->pass), ws_total changed (rubric drift on ws only).
    # Eval 3: ws regressed (pass->fail) and the new run labels it rubric_friction.
    # Eval 4: bs missing on the new run (partial dispatch).
    eval_catalog = [
        {
            "id": 1,
            "name": "alpha",
            "stage": "pipeline-usage",
            "tier": "joins",
            "difficulty": "easy",
            "expected_refs": {"required": ["common_tables.md"], "optional": [], "distractor": []},
            "expected_scripts": {"required": ["code_graph.py"], "optional": [], "distractor": []},
        },
        {
            "id": 2,
            "name": "beta",
            "stage": "pipeline-usage",
            "tier": "joins",
            "difficulty": "easy",
            "expected_refs": {"required": ["common_tables.md"], "optional": [], "distractor": []},
            "expected_scripts": {"required": ["code_graph.py"], "optional": [], "distractor": []},
        },
        {
            "id": 3,
            "name": "gamma",
            "stage": "pipeline-usage",
            "tier": "joins",
            "difficulty": "easy",
            "expected_refs": {"required": ["common_tables.md"], "optional": [], "distractor": []},
            "expected_scripts": {"required": ["code_graph.py"], "optional": [], "distractor": []},
        },
        # Eval 4 has no required refs/scripts -> has_required_refs=false.
        {"id": 4, "name": "delta", "stage": "pipeline-usage", "tier": "joins", "difficulty": "easy"},
    ]
    # Old transcripts: eval 1 ws/bs both find ref + script; eval 2 ws fails to
    # open required ref; eval 3 ws/bs both find ref + script; eval 4 ws has a
    # transcript with no resources used.
    old_transcripts = {
        (1, "with_skill"):    {"ref_opens": ["common_tables.md"], "script_executions": ["code_graph.py"]},
        (1, "without_skill"): {"ref_opens": ["common_tables.md"], "script_executions": ["code_graph.py"]},
        (2, "with_skill"):    {"ref_opens": [],                   "script_executions": ["code_graph.py"]},
        (2, "without_skill"): {"ref_opens": [],                   "script_executions": []},
        (3, "with_skill"):    {"ref_opens": ["common_tables.md"], "script_executions": ["code_graph.py"]},
        (3, "without_skill"): {"ref_opens": ["common_tables.md"], "script_executions": []},
        (4, "with_skill"):    {"ref_opens": [],                   "script_executions": []},
        (4, "without_skill"): {"ref_opens": [],                   "script_executions": []},
    }
    # New transcripts: eval 2 ws now opens the ref (ref recall improvement);
    # eval 3 ws drops the script (script recall regression). Eval 4 ws is
    # *missing* a transcript entirely (routing_complete=false on that cell);
    # eval 4 bs is also absent because eval 4 bs is missing in the new run.
    new_transcripts = {
        (1, "with_skill"):    {"ref_opens": ["common_tables.md"], "script_executions": ["code_graph.py"]},
        (1, "without_skill"): {"ref_opens": ["common_tables.md"], "script_executions": ["code_graph.py"]},
        (2, "with_skill"):    {"ref_opens": ["common_tables.md"], "script_executions": ["code_graph.py"]},
        (2, "without_skill"): {"ref_opens": [],                   "script_executions": []},
        (3, "with_skill"):    {"ref_opens": ["common_tables.md"], "script_executions": []},
        (3, "without_skill"): {"ref_opens": ["common_tables.md"], "script_executions": []},
        # Eval 4 ws + bs both absent in new run.
    }
    _build_compare_run(
        old_run,
        eval_results={
            "with_skill": [
                {"eval_id": 1, "eval_name": "alpha", "all_passed": True,  "passed_count": 5, "total": 5},
                {"eval_id": 2, "eval_name": "beta",  "all_passed": False, "passed_count": 3, "total": 5},
                {"eval_id": 3, "eval_name": "gamma", "all_passed": True,  "passed_count": 5, "total": 5},
                {"eval_id": 4, "eval_name": "delta", "all_passed": False, "passed_count": 2, "total": 5},
                {"eval_id": 9, "eval_name": "old-only", "all_passed": True, "passed_count": 5, "total": 5},
            ],
            "without_skill": [
                {"eval_id": 1, "eval_name": "alpha", "all_passed": True,  "passed_count": 5, "total": 5},
                {"eval_id": 2, "eval_name": "beta",  "all_passed": False, "passed_count": 2, "total": 5},
                {"eval_id": 3, "eval_name": "gamma", "all_passed": False, "passed_count": 2, "total": 5},
                {"eval_id": 4, "eval_name": "delta", "all_passed": False, "passed_count": 1, "total": 5},
                {"eval_id": 9, "eval_name": "old-only", "all_passed": False, "passed_count": 2, "total": 5},
            ],
        },
        timing_by_eid_cond={
            (1, "with_skill"): 1000, (1, "without_skill"): 600,
            (2, "with_skill"): 1100, (2, "without_skill"): 650,
            (3, "with_skill"): 1200, (3, "without_skill"): 700,
            (4, "with_skill"): 1300, (4, "without_skill"): 750,
            (9, "with_skill"): 900,  (9, "without_skill"): 550,
        },
        eval_catalog=eval_catalog,
        transcripts=old_transcripts,
    )
    _build_compare_run(
        new_run,
        eval_results={
            "with_skill": [
                {"eval_id": 1, "eval_name": "alpha", "all_passed": True,  "passed_count": 5, "total": 5},
                # ws_total bumped 5 -> 6 to simulate ws-only rubric drift.
                {"eval_id": 2, "eval_name": "beta",  "all_passed": True,  "passed_count": 6, "total": 6},
                {"eval_id": 3, "eval_name": "gamma", "all_passed": False, "passed_count": 3, "total": 5},
                {"eval_id": 4, "eval_name": "delta", "all_passed": False, "passed_count": 2, "total": 5},
                {"eval_id": 8, "eval_name": "new-only", "all_passed": False, "passed_count": 0, "total": 5},
            ],
            "without_skill": [
                {"eval_id": 1, "eval_name": "alpha", "all_passed": True,  "passed_count": 5, "total": 5},
                {"eval_id": 2, "eval_name": "beta",  "all_passed": False, "passed_count": 2, "total": 5},
                {"eval_id": 3, "eval_name": "gamma", "all_passed": False, "passed_count": 2, "total": 5},
                # eval 4 bs missing -> partial dispatch
                {"eval_id": 8, "eval_name": "new-only", "all_passed": False, "passed_count": 1, "total": 5},
            ],
        },
        # Eval 1 ws-new timing missing -> ws coverage incomplete on new side.
        # Eval 3 ws-new timing missing -> the entire regressed bucket has no
        # complete ws timing in c05 (verifies the empty-bucket label fix).
        timing_by_eid_cond={
            (1, "with_skill"): None, (1, "without_skill"): 700,
            (2, "with_skill"): 1500, (2, "without_skill"): 650,
            (3, "with_skill"): None, (3, "without_skill"): 800,
            (4, "with_skill"): 1300, (4, "without_skill"): None,
            (8, "with_skill"): 800,  (8, "without_skill"): 500,
        },
        edit_to_evals={
            # Many-to-many: eval 2 declared under both edits.
            "edit_a": [2, 3],
            "edit_b": [2, 4],
        },
        failure_taxonomy=[
            {"eval_id": "3", "failure_type": "rubric_friction", "notes": ""},
            {"eval_id": "4", "failure_type": "rubric_friction", "notes": ""},
        ],
        eval_catalog=eval_catalog,
        transcripts=new_transcripts,
    )

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/compare_runs.py"),
            "--new", str(new_run),
            "--old", str(old_run),
            "--out", str(out),
        ],
        check=True,
        cwd=ROOT,
    )

    # Atomicity: staged dirs are gone after a successful commit.
    for staged in (out / ".data_tmp", out / ".figures_tmp"):
        if staged.exists():
            raise AssertionError(f"compare_runs left staged dir behind: {staged}")
    # Routing-record loader must not leave hidden dirs inside either input run.
    for run in (old_run, new_run):
        leak = run / ".compare_transcripts_tmp"
        if leak.exists():
            raise AssertionError(f"compare_runs leaked staging dir into input run: {leak}")

    required = [
        "INDEX.md",
        "data/comparison_manifest.json",
        "data/overlap.json",
        "data/headline_diff.json",
        "data/transitions.csv",
        "data/targeted_edits_long.csv",
        "data/targeted_edits_summary.csv",
        "data/outcome_2x2_shift.json",
        "data/cost_shift.csv",
        "data/routing_shift.csv",
        "figures/c01_headline_shift.png",
        "figures/c02_per_eval_transitions.png",
        "figures/c03_outcome_flow.png",
        "figures/c04_targeted_edits.png",
        "figures/c05_cost_shift_by_transition.png",
        "figures/c06_routing_shift.png",
    ]
    missing = [name for name in required if not (out / name).exists()]
    if missing:
        raise AssertionError(f"compare_runs missing outputs: {missing}")

    overlap = json.loads((out / "data/overlap.json").read_text())
    if overlap["n_overlap"] != 4:
        raise AssertionError(f"bad overlap n: {overlap}")
    if overlap["overlap_eval_ids"] != [1, 2, 3, 4]:
        raise AssertionError(f"bad overlap ids: {overlap}")
    if overlap["old_only"] != [9] or overlap["new_only"] != [8]:
        raise AssertionError(f"bad overlap-only sets: {overlap}")

    headline = json.loads((out / "data/headline_diff.json").read_text())
    # ws total changed on eval 2 (5 -> 6); bs totals all stable.
    if headline["rubric_sensitive"] != {"ws": True, "bs": False, "any": True}:
        raise AssertionError(f"bad rubric_sensitive split: {headline['rubric_sensitive']}")
    if headline["n_evals_with_rubric_change"] != {"ws": 1, "bs": 0, "any": 1}:
        raise AssertionError(f"bad rubric counts: {headline['n_evals_with_rubric_change']}")
    # ws full pass: old=2 (evals 1, 3), new=2 (evals 1, 2); 4 evals total, all ws cells present.
    if headline["ws_full_pass"]["old"] != 2 or headline["ws_full_pass"]["new"] != 2:
        raise AssertionError(f"bad ws_full_pass: {headline['ws_full_pass']}")
    if headline["ws_full_pass"]["n_with_data"] != 4:
        raise AssertionError(f"bad ws_full_pass n_with_data: {headline['ws_full_pass']}")
    # bs full pass uses 3 evals (eval 4 bs is missing on new).
    if headline["bs_full_pass"]["n_with_data"] != 3:
        raise AssertionError(f"bad bs_full_pass n_with_data: {headline['bs_full_pass']}")
    if headline["bs_full_pass"]["complete"]:
        raise AssertionError("bs_full_pass complete should be False on partial dispatch")
    # ws transitions: eval 1 stable_pass, eval 2 improved, eval 3 regressed, eval 4 stable_fail.
    expected_ws = {"stable_pass": 1, "improved": 1, "regressed": 1, "stable_fail": 1}
    if headline["ws_transition_table"] != expected_ws:
        raise AssertionError(f"bad ws_transition_table: {headline['ws_transition_table']}")
    # Token coverage: ws old has all 4 cells, ws new is missing eval 1, so incomplete.
    ws_tok = headline["tokens"]["ws"]
    if ws_tok["complete"] or ws_tok["delta_total"] is not None:
        raise AssertionError(f"ws tokens should be incomplete: {ws_tok}")
    if ws_tok["missing_new_eval_ids"] != [1, 3]:
        raise AssertionError(f"bad ws missing_new ids: {ws_tok}")
    bs_tok = headline["tokens"]["bs"]
    if bs_tok["complete"] or bs_tok["missing_new_eval_ids"] != [4]:
        raise AssertionError(f"bad bs token coverage: {bs_tok}")

    # Schema check: transitions.csv uses _old/_new, no _c/_d, has split rubric flags.
    with (out / "data/transitions.csv").open(newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        rows = list(reader)
    forbidden = [c for c in header if c.endswith("_c") or c.endswith("_d")]
    if forbidden:
        raise AssertionError(f"transitions.csv has _c/_d columns: {forbidden}")
    for required_col in ("ws_rubric_changed", "bs_rubric_changed", "ws_missing_old", "bs_missing_new"):
        if required_col not in header:
            raise AssertionError(f"transitions.csv missing {required_col}: {header}")
    by_id = {int(r["eval_id"]): r for r in rows}
    if len(by_id) != 4:
        raise AssertionError(f"transitions.csv should have 4 rows, has {len(by_id)}")
    if by_id[2]["ws_rubric_changed"] != "true" or by_id[2]["bs_rubric_changed"] != "false":
        raise AssertionError(f"eval 2 split rubric flags wrong: {by_id[2]}")
    if by_id[4]["bs_missing_new"] != "true":
        raise AssertionError(f"eval 4 bs_missing_new wrong: {by_id[4]}")
    if by_id[4]["bs_transition"]:
        raise AssertionError(f"eval 4 bs_transition should be empty when missing: {by_id[4]}")
    if by_id[3]["regression_interpretation"] != "rubric_friction":
        raise AssertionError(f"eval 3 should be rubric_friction: {by_id[3]}")

    # outcome_2x2_shift.json: joint set excludes eval 4 (bs missing on new).
    shift = json.loads((out / "data/outcome_2x2_shift.json").read_text())
    if shift["n_joint"] != 3:
        raise AssertionError(f"bad n_joint: {shift['n_joint']}")
    if shift["excluded_eval_ids"] != [4]:
        raise AssertionError(f"bad excluded list: {shift['excluded_eval_ids']}")
    if list(shift["flow_matrix"].keys()) != ["both_pass", "skill_only", "baseline_only", "both_fail"]:
        raise AssertionError(f"bad flow_matrix bucket order: {list(shift['flow_matrix'])}")
    flow = shift["flow_matrix"]
    if flow["both_pass"]["both_pass"] != 1:
        raise AssertionError(f"flow both_pass→both_pass should be 1: {flow}")
    if flow["both_fail"]["skill_only"] != 1:
        raise AssertionError(f"flow both_fail→skill_only should be 1: {flow}")
    if flow["skill_only"]["both_fail"] != 1:
        raise AssertionError(f"flow skill_only→both_fail should be 1: {flow}")
    if shift["n_stable"] != 1 or shift["n_changed"] != 2:
        raise AssertionError(f"bad stable/changed split: {shift}")
    # All 16 cells must be present (zero-filled), so consumers can index without try/except.
    for old_b in ("both_pass", "skill_only", "baseline_only", "both_fail"):
        for new_b in ("both_pass", "skill_only", "baseline_only", "both_fail"):
            if new_b not in flow[old_b]:
                raise AssertionError(f"flow_matrix missing {old_b}->{new_b}")
    # flow_examples must list eval ids and stay in sync with flow counts.
    if shift["flow_examples"]["both_fail"]["skill_only"] != [2]:
        raise AssertionError(f"flow_examples wrong for both_fail->skill_only: {shift['flow_examples']}")

    # cost_shift.csv: eval 1 ws_pair_complete=false (ws_new timing missing);
    # eval 4 bs_pair_complete=false (bs_new timing missing). Token deltas
    # for eval 2/3/4 should follow synthetic fixture math.
    with (out / "data/cost_shift.csv").open(newline="") as f:
        cost_rows = list(csv.DictReader(f))
    if {"ws_pair_complete", "bs_pair_complete", "token_delta_ws", "token_delta_bs"} - set(
        cost_rows[0].keys()
    ):
        raise AssertionError(f"cost_shift.csv missing expected columns: {cost_rows[0].keys()}")
    cost_by_id = {int(r["eval_id"]): r for r in cost_rows}
    if cost_by_id[1]["ws_pair_complete"] != "false" or cost_by_id[1]["token_delta_ws"] != "":
        raise AssertionError(f"eval 1 ws should be incomplete and blank delta: {cost_by_id[1]}")
    if cost_by_id[1]["bs_pair_complete"] != "true" or cost_by_id[1]["token_delta_bs"] != "100":
        raise AssertionError(f"eval 1 bs delta should be 700-600=100: {cost_by_id[1]}")
    if cost_by_id[2]["token_delta_ws"] != "400" or cost_by_id[2]["ws_transition"] != "improved":
        raise AssertionError(f"eval 2 ws_delta should be +400 improved: {cost_by_id[2]}")
    # Eval 3: regressed but ws_new timing missing, so the whole regressed
    # bucket is excluded from c05. Token delta blank, transition still set.
    if (
        cost_by_id[3]["ws_pair_complete"] != "false"
        or cost_by_id[3]["token_delta_ws"] != ""
        or cost_by_id[3]["ws_transition"] != "regressed"
    ):
        raise AssertionError(
            f"eval 3 should be regressed with incomplete ws timing: {cost_by_id[3]}"
        )
    if cost_by_id[4]["bs_pair_complete"] != "false" or cost_by_id[4]["token_delta_bs"] != "":
        raise AssertionError(f"eval 4 bs should be incomplete: {cost_by_id[4]}")

    # c05 bucket-accounting: when an entire transition bucket has no
    # complete ws timing, the figure must label it explicitly rather than
    # appearing empty. We exercise the helper directly so a layout regression
    # in plot_cost_shift_by_transition would surface here.
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        from _compare_figures import _read_csv as _read
    finally:
        sys.path.pop(0)
    cost_csv_rows = _read(out / "data/cost_shift.csv")
    bucket_total: dict[str, int] = {}
    bucket_excluded: dict[str, int] = {}
    for r in cost_csv_rows:
        bucket = r["ws_transition"]
        bucket_total[bucket] = bucket_total.get(bucket, 0) + 1
        if r["ws_pair_complete"] != "true" or r["token_delta_ws"] == "":
            bucket_excluded[bucket] = bucket_excluded.get(bucket, 0) + 1
    if bucket_total.get("regressed", 0) != 1 or bucket_excluded.get("regressed", 0) != 1:
        raise AssertionError(
            f"regressed bucket should be 1/1 excluded: total={bucket_total}, excluded={bucket_excluded}"
        )
    if bucket_total.get("improved", 0) != 1 or bucket_excluded.get("improved", 0):
        raise AssertionError(
            f"improved bucket should be fully timed: total={bucket_total}, excluded={bucket_excluded}"
        )

    # routing_shift.csv: 4 evals × 2 conditions = 8 rows.
    # Eval 4 ws is missing a transcript on the new run -> routing_complete=false
    # for that cell, with blank deltas. Eval 4 has no required refs/scripts
    # (eval_catalog) -> has_required_refs=false. Eval 2 ws ref recall improves
    # from 0.0 to 1.0; eval 3 ws script recall regresses from 1.0 to 0.0.
    with (out / "data/routing_shift.csv").open(newline="") as f:
        routing_rows = list(csv.DictReader(f))
    if len(routing_rows) != 8:
        raise AssertionError(f"routing_shift.csv should have 8 rows, has {len(routing_rows)}")
    routing = {(int(r["eval_id"]), r["condition"]): r for r in routing_rows}
    eval2_ws = routing[(2, "with_skill")]
    if (
        eval2_ws["routing_complete"] != "true"
        or eval2_ws["required_ref_recall_old"] != "0.0"
        or eval2_ws["required_ref_recall_new"] != "1.0"
        or float(eval2_ws["required_ref_recall_delta"]) != 1.0
    ):
        raise AssertionError(f"eval 2 ws ref recall should improve 0->1: {eval2_ws}")
    eval3_ws = routing[(3, "with_skill")]
    if (
        eval3_ws["required_script_recall_old"] != "1.0"
        or eval3_ws["required_script_recall_new"] != "0.0"
        or float(eval3_ws["required_script_recall_delta"]) != -1.0
    ):
        raise AssertionError(f"eval 3 ws script recall should regress 1->0: {eval3_ws}")
    eval4_ws = routing[(4, "with_skill")]
    if eval4_ws["routing_complete"] != "false":
        raise AssertionError(f"eval 4 ws routing_complete should be false: {eval4_ws}")
    if eval4_ws["required_ref_recall_delta"] != "" or eval4_ws["required_ref_recall_new"] != "":
        raise AssertionError(f"eval 4 ws routing deltas should be blank: {eval4_ws}")
    if eval4_ws["has_required_refs"] != "false" or eval4_ws["has_required_scripts"] != "false":
        raise AssertionError(f"eval 4 should have no required refs/scripts: {eval4_ws}")
    eval1_ws = routing[(1, "with_skill")]
    if float(eval1_ws["required_ref_recall_delta"]) != 0.0:
        raise AssertionError(f"eval 1 ws ref recall should be stable: {eval1_ws}")

    # comparison_manifest.json: every staged output must appear, primary
    # outputs must include the audit/headline trio, and no entry should be
    # left as a fallback classification (the override table covers all
    # current outputs).
    manifest = json.loads((out / "data/comparison_manifest.json").read_text())
    if manifest["overlap_audit"]["n_overlap"] != 4:
        raise AssertionError(f"manifest n_overlap wrong: {manifest['overlap_audit']}")
    entries = manifest["outputs"]
    by_filename = {e["filename"]: e for e in entries}
    for required_entry in (
        "INDEX.md",
        "data/comparison_manifest.json",
        "data/overlap.json",
        "data/headline_diff.json",
        "data/transitions.csv",
        "data/cost_shift.csv",
        "data/routing_shift.csv",
        "figures/c01_headline_shift.png",
        "figures/c06_routing_shift.png",
    ):
        if required_entry not in by_filename:
            raise AssertionError(
                f"comparison_manifest missing entry: {required_entry}; have {sorted(by_filename)}"
            )
    fallbacks = [e["filename"] for e in entries if e["classification_source"] == "fallback"]
    if fallbacks:
        raise AssertionError(
            f"comparison_manifest left entries unclassified: {fallbacks}"
        )
    # Spot-check one primary entry's family/priority.
    overlap_entry = by_filename["data/overlap.json"]
    if overlap_entry["priority"] != "primary" or overlap_entry["family"] != "audit":
        raise AssertionError(f"data/overlap.json should be primary/audit: {overlap_entry}")

    # INDEX.md: header should report n_overlap and the underpowered caveat
    # (n_overlap=4 < 25), and link to overlap.json + transitions.csv.
    index_text = (out / "INDEX.md").read_text()
    if "n_overlap: **4**" not in index_text:
        raise AssertionError(f"INDEX.md missing n_overlap header:\n{index_text[:400]}")
    if "underpowered" not in index_text:
        raise AssertionError("INDEX.md missing underpowered caveat for n=4")
    for link in ("data/overlap.json", "data/transitions.csv", "figures/c01_headline_shift.png"):
        if f"({link})" not in index_text:
            raise AssertionError(f"INDEX.md missing link to {link}")

    # Many-to-many: eval 2 should appear under both edit_a and edit_b.
    with (out / "data/targeted_edits_long.csv").open(newline="") as f:
        long_rows = list(csv.DictReader(f))
    eval2_edits = sorted(r["edit_id"] for r in long_rows if r["eval_id"] == "2")
    if eval2_edits != ["edit_a", "edit_b"]:
        raise AssertionError(f"eval 2 should appear under both edits: {eval2_edits}")

    # Failed comparison should not corrupt existing committed outputs.
    sentinel_data = out / "data/headline_diff.json"
    sentinel_bytes = sentinel_data.read_bytes()
    bogus_old = base / "bogus-old-run"
    bogus_old.mkdir()
    failed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/compare_runs.py"),
            "--new", str(new_run),
            "--old", str(bogus_old),
            "--out", str(out),
        ],
        check=False,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if failed.returncode == 0:
        raise AssertionError(
            f"expected missing iteration-N to fail; output:\n{failed.stdout}"
        )
    if sentinel_data.read_bytes() != sentinel_bytes:
        raise AssertionError("failed compare_runs corrupted existing committed outputs")
    if (out / ".INDEX.tmp").exists():
        raise AssertionError("failed compare_runs left .INDEX.tmp behind")
    for staged in (out / ".data_tmp", out / ".figures_tmp"):
        if staged.exists():
            raise AssertionError(
                f"failed compare_runs left staging dir behind: {staged}"
            )


if __name__ == "__main__":
    main()
