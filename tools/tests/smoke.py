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
    """Write a JSON payload with stable formatting.

    Parameters
    ----------
    path
        Destination file path.
    payload
        JSON-serializable object to write.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def make_grading(eval_dir: Path, cond: str, passed: bool) -> None:
    """Create a minimal synthetic eval result for one condition.

    Parameters
    ----------
    eval_dir
        Synthetic eval directory to populate.
    cond
        Condition name, such as ``"with_skill"`` or ``"without_skill"``.
    passed
        Whether both smoke expectations should pass.
    """

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
    """Build synthetic runs and verify the summary and comparison CLIs."""

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
    run_meta_extra: dict | None = None,
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
    if run_meta_extra:
        run_meta.update(run_meta_extra)
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
                # Synthetic duration: tokens / 100 seconds, deterministic.
                write_json(
                    eval_dir / cond / "timing.json",
                    {
                        "total_tokens": tokens,
                        "total_duration_seconds": tokens / 100.0,
                    },
                )
            # Minimal response.md + grading.json so regression_review.csv can
            # link to per-condition artifacts.
            response = eval_dir / cond / "outputs" / "response.md"
            response.parent.mkdir(parents=True, exist_ok=True)
            response.write_text(f"synthetic response for eval {eid} {cond}\n")
            write_json(
                eval_dir / cond / "grading.json",
                {
                    "eval_id": eid,
                    "all_passed": r["all_passed"],
                    "expectations": [],
                },
            )
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
        # Use a fixed source string (not run-dir-dependent) so two
        # runs with identical catalogs produce byte-identical snapshots
        # — exercises the provenance hash's stability guarantee.
        write_json(
            run_dir / "evals_snapshot.json",
            {"source": "synthetic://eval-catalog", "evals": eval_catalog},
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
    # Each eval declares an intent so c10 / intent_balance.csv can group on
    # it. Eval 4 deliberately omits the field to exercise the "unknown"
    # fallback bucket.
    eval_catalog = [
        {
            "id": 1,
            "name": "alpha",
            "stage": "pipeline-usage",
            "tier": "joins",
            "difficulty": "easy",
            "intent": "should_trigger",
            "expected_refs": {"required": ["common_tables.md"], "optional": [], "distractor": []},
            "expected_scripts": {"required": ["code_graph.py"], "optional": [], "distractor": []},
        },
        {
            "id": 2,
            "name": "beta",
            "stage": "pipeline-usage",
            "tier": "joins",
            "difficulty": "easy",
            "intent": "should_not_trigger",
            "expected_refs": {"required": ["common_tables.md"], "optional": [], "distractor": []},
            "expected_scripts": {"required": ["code_graph.py"], "optional": [], "distractor": []},
        },
        {
            "id": 3,
            "name": "gamma",
            "stage": "pipeline-usage",
            "tier": "joins",
            "difficulty": "easy",
            "intent": "near_miss_negative",
            "expected_refs": {"required": ["common_tables.md"], "optional": [], "distractor": []},
            "expected_scripts": {"required": ["code_graph.py"], "optional": [], "distractor": []},
        },
        # Eval 4 omits intent -> falls back to "unknown".
        {"id": 4, "name": "delta", "stage": "pipeline-usage", "tier": "joins", "difficulty": "easy"},
    ]
    # New-run catalog differs from old on multiple semantic dimensions to
    # exercise the broader catalog_diff coverage:
    #   - eval 2: difficulty easy -> hard
    #   - eval 3: prompt edited (silent prompt-change case)
    #   - eval 4: assertions.required_substrings edited (dict-shape sub-field)
    #   - eval 6: added in new run only
    # Old-run catalog adds prompt + dict-shape assertions to all evals so
    # the diff has something concrete to detect, including the real-world
    # catalog shape where `assertions` is a dict-of-lists. Eval 1 gets two
    # required_substrings so the new run can reorder them — that order-only
    # change must NOT surface as drift (the canonical hash sorts and the
    # diff must agree).
    for entry in eval_catalog:
        entry.setdefault("prompt", f"baseline prompt for {entry['name']}")
        if entry["id"] == 1:
            entry.setdefault(
                "assertions",
                {
                    "required_substrings": ["req-1-a", "req-1-b"],
                    "forbidden_substrings": [],
                    "behavioral_checks": ["behavioral-1"],
                },
            )
        else:
            entry.setdefault(
                "assertions",
                {
                    "required_substrings": [f"req-{entry['id']}-a"],
                    "forbidden_substrings": [],
                    "behavioral_checks": [f"behavioral-{entry['id']}"],
                },
            )
    new_eval_catalog = [dict(e) for e in eval_catalog]
    # eval 1: reorder required_substrings (b then a) — content unchanged.
    # Must not surface as a catalog change.
    new_eval_catalog[0] = {
        **eval_catalog[0],
        "assertions": {
            "required_substrings": ["req-1-b", "req-1-a"],
            "forbidden_substrings": [],
            "behavioral_checks": ["behavioral-1"],
        },
    }
    new_eval_catalog[1] = {**eval_catalog[1], "difficulty": "hard"}
    new_eval_catalog[2] = {**eval_catalog[2], "prompt": "edited prompt for eval 3"}
    # eval 4: edit a sub-list of the dict-shape assertions field. This is
    # the real-shape silent-rubric-change case the previous list-only
    # implementation missed.
    new_eval_catalog[3] = {
        **eval_catalog[3],
        "assertions": {
            "required_substrings": ["req-4-a", "req-4-b-NEW"],
            "forbidden_substrings": [],
            "behavioral_checks": [f"behavioral-{eval_catalog[3]['id']}"],
        },
    }
    new_eval_catalog.append(
        {
            "id": 6,
            "name": "zeta",
            "stage": "pipeline-usage",
            "tier": "joins",
            "difficulty": "easy",
            "prompt": "new eval prompt",
            "assertions": {
                "required_substrings": ["req-6-a"],
                "forbidden_substrings": [],
                "behavioral_checks": [],
            },
        }
    )
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
        # Eval 3 (near_miss_negative): ws transcript opens ONLY SKILL.md
        # — c10 must not let SKILL.md alone inflate the spyglass-ref
        # activation rate. Required-ref recall is 0 here (common_tables.md
        # was not opened), so the previous behavior would double-count.
        (3, "with_skill"):    {"ref_opens": ["SKILL.md"],         "script_executions": []},
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
        # Old run declares its grader so provenance can detect drift on the
        # new side. grader_prompt_sha256 stays stable; grader_model is the
        # field the synthetic new run drifts.
        run_meta_extra={
            "grader_model": "old-grader-model",
            "grader_prompt_sha256": "abc123",
        },
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
        eval_catalog=new_eval_catalog,
        transcripts=new_transcripts,
        # New run drifts grader_model; grader_prompt_sha256 stays stable so
        # smoke can verify per-field changed-flag behavior.
        run_meta_extra={
            "grader_model": "new-grader-model",
            "grader_prompt_sha256": "abc123",
        },
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
        "data/provenance_diff.json",
        "data/catalog_diff.json",
        "data/headline_diff.json",
        "data/transitions.csv",
        "data/targeted_edits_long.csv",
        "data/targeted_edits_summary.csv",
        "data/outcome_2x2_shift.json",
        "data/cost_shift.csv",
        "data/routing_shift.csv",
        "data/category_shift.csv",
        "data/intent_balance.csv",
        "data/regression_review.csv",
        "data/regression_root_cause.csv",
        "data/regression_root_cause_summary.json",
        "figures/c01_did_the_headline_improve.png",
        "figures/c02_did_outcomes_move_per_eval.png",
        "figures/c03_where_did_evals_move_in_2x2.png",
        "figures/c04_did_targeted_edits_explain_movement.png",
        "figures/c05_did_improvements_cost_more.png",
        "figures/c06_did_routing_change.png",
        "figures/c07_where_does_category_drift.png",
        "figures/c08_did_skill_lift_change.png",
        "figures/c09_regression_root_causes.png",
        "figures/c10_is_intent_balanced.png",
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
        from compare.figures import _read_csv as _read
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
        "figures/c01_did_the_headline_improve.png",
        "figures/c06_did_routing_change.png",
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
    for link in ("data/overlap.json", "data/transitions.csv", "figures/c01_did_the_headline_improve.png"):
        if f"({link})" not in index_text:
            raise AssertionError(f"INDEX.md missing link to {link}")

    # skill_lift block in headline_diff.json: joint set has 3 evals (eval 4
    # is excluded because bs_new is missing). On those 3 joint evals:
    #   ws_pass_old = eval 1 + eval 3 = 2;  bs_pass_old = eval 1 = 1
    #   ws_pass_new = eval 1 + eval 2 = 2;  bs_pass_new = eval 1 = 1
    # Both lifts equal +1/3, so delta_pp ≈ 0.
    headline_full = json.loads((out / "data/headline_diff.json").read_text())
    lift = headline_full["skill_lift"]
    if lift["n_joint"] != 3:
        raise AssertionError(f"skill_lift n_joint should be 3: {lift}")
    if lift["complete"]:
        raise AssertionError(
            f"skill_lift.complete should be false (eval 4 excluded): {lift}"
        )
    if lift["ws_pass_old"] != 2 or lift["bs_pass_old"] != 1:
        raise AssertionError(f"skill_lift old counts wrong: {lift}")
    if lift["ws_pass_new"] != 2 or lift["bs_pass_new"] != 1:
        raise AssertionError(f"skill_lift new counts wrong: {lift}")
    if abs(lift["delta_pp"]) > 0.5:
        raise AssertionError(
            f"skill_lift delta should be ~0 (both lifts equal +33.3pp): {lift}"
        )
    if not lift["underpowered"]:
        raise AssertionError("skill_lift should flag underpowered (n_joint=3 < 25)")
    for ci_key in ("old_pp_ci95", "new_pp_ci95", "delta_pp_ci95"):
        ci = lift[ci_key]
        if not (isinstance(ci, list) and len(ci) == 2 and ci[0] <= ci[1]):
            raise AssertionError(f"skill_lift {ci_key} should be a 2-list lo<=hi: {ci}")

    # ws_full_pass and bs_full_pass should now carry CI lists too.
    ws_fp = headline_full["ws_full_pass"]
    if "old_rate_ci95" not in ws_fp or "delta_pp_ci95" not in ws_fp:
        raise AssertionError(
            f"ws_full_pass should carry bootstrap CI keys: {sorted(ws_fp)}"
        )

    # catalog_diff.json: eval 2 difficulty changed, eval 3 prompt edited,
    # eval 4 assertions.required_substrings edited (dict-shape sub-field
    # edit), eval 6 added. Verifies the full semantic field coverage,
    # including the real-shape dict-of-lists case for assertions.
    catalog_diff = json.loads((out / "data/catalog_diff.json").read_text())
    if catalog_diff["n_added"] != 1 or catalog_diff["added_eval_ids"] != [6]:
        raise AssertionError(f"catalog_diff added wrong: {catalog_diff}")
    if catalog_diff["n_removed"] != 0:
        raise AssertionError(f"catalog_diff removed should be 0: {catalog_diff}")
    if catalog_diff["n_changed"] != 3:
        raise AssertionError(f"catalog_diff should have 3 changed evals: {catalog_diff}")
    by_id = {ce["eval_id"]: ce for ce in catalog_diff["changed_evals"]}
    for required in (2, 3, 4):
        if required not in by_id:
            raise AssertionError(
                f"changed evals should include {required}: {sorted(by_id)}"
            )
    eval2_diff = by_id[2]
    if "difficulty" not in eval2_diff["fields_changed"]:
        raise AssertionError(
            f"eval 2 difficulty change should be detected: {eval2_diff}"
        )
    if eval2_diff.get("difficulty_old") != "easy" or eval2_diff.get("difficulty_new") != "hard":
        raise AssertionError(
            f"eval 2 difficulty old/new wrong: {eval2_diff}"
        )
    eval3_diff = by_id[3]
    if "prompt" not in eval3_diff["fields_changed"]:
        raise AssertionError(
            f"eval 3 prompt edit should be detected (silent-prompt-change case): "
            f"{eval3_diff}"
        )
    if eval3_diff.get("prompt_new") != "edited prompt for eval 3":
        raise AssertionError(f"eval 3 prompt_new wrong: {eval3_diff}")
    eval4_diff = by_id[4]
    # The dict-shape silent-rubric-change case: assertions is stored as
    # {required_substrings, forbidden_substrings, behavioral_checks}.
    # Editing one sub-list MUST surface as assertions.<sub_field> in
    # fields_changed and as added/removed lists in the diff.
    if "assertions.required_substrings" not in eval4_diff["fields_changed"]:
        raise AssertionError(
            "eval 4 assertions.required_substrings edit should be detected "
            f"(dict-shape sub-field): {eval4_diff}"
        )
    if eval4_diff.get("assertions.required_substrings_added") != ["req-4-b-NEW"]:
        raise AssertionError(
            f"eval 4 assertions.required_substrings_added wrong: {eval4_diff}"
        )
    if "assertions" in eval4_diff["fields_changed"]:
        raise AssertionError(
            "Dict-shape assertions should not surface as a flat 'assertions' "
            f"field; only the sub-keys: {eval4_diff}"
        )
    # Eval 1 reordered its required_substrings between runs but the content
    # is identical. The canonical hash sorts; the diff MUST agree, so eval 1
    # should not appear in changed_evals at all.
    if 1 in by_id:
        raise AssertionError(
            f"eval 1 should NOT be flagged changed (order-only edit): {by_id[1]}"
        )

    # Many-to-many: eval 2 should appear under both edit_a and edit_b.
    with (out / "data/targeted_edits_long.csv").open(newline="") as f:
        long_rows = list(csv.DictReader(f))
    eval2_edits = sorted(r["edit_id"] for r in long_rows if r["eval_id"] == "2")
    if eval2_edits != ["edit_a", "edit_b"]:
        raise AssertionError(f"eval 2 should appear under both edits: {eval2_edits}")

    # provenance_diff.json: skill commits differ between synthetic fixtures
    # (`sha-old-run` vs `sha-new-run`) so causal_changed should be true and
    # the skill_commit_at_sweep_end field should be flagged changed and
    # tagged kind="causal". metadata_changed will be true because the
    # *raw* snapshot hash drifts (catalogs differ on eval 2 difficulty +
    # eval 6, both real edits — but the raw bytes hash is metadata-only;
    # the causal signal lives in evals_catalog_semantic_sha256).
    prov = json.loads((out / "data/provenance_diff.json").read_text())
    if not prov["causal_changed"]:
        raise AssertionError(
            f"provenance_diff should flag causal_changed=true on synthetic fixture: {prov}"
        )
    if "any_changed" in prov:
        raise AssertionError(
            "provenance_diff should not emit a back-compat any_changed key"
        )
    skill_field = prov["fields"]["skill_commit_at_sweep_end"]
    if (
        not skill_field["changed"]
        or skill_field["old"] == skill_field["new"]
        or skill_field.get("kind") != "causal"
    ):
        raise AssertionError(
            f"skill_commit_at_sweep_end should be flagged changed/causal: {skill_field}"
        )
    # evals_catalog_semantic_sha256: synthetic new run differs from old
    # (eval 2 difficulty bumped, eval 6 added) so the *semantic* hash MUST
    # be flagged changed and tagged kind="causal". catalog_diff.json
    # (asserted below) explains what specifically moved. The raw bytes
    # hash also differs, but it is tagged metadata-only so it does not
    # contribute to causal_changed.
    semantic_field = prov["fields"]["evals_catalog_semantic_sha256"]
    if not semantic_field["changed"] or semantic_field.get("kind") != "causal":
        raise AssertionError(
            f"evals_catalog_semantic_sha256 should be flagged changed/causal "
            f"on real eval drift: {semantic_field}"
        )
    raw_field = prov["fields"]["evals_snapshot_sha256_raw"]
    if raw_field.get("kind") != "metadata":
        raise AssertionError(
            f"evals_snapshot_sha256_raw should be tagged metadata: {raw_field}"
        )
    # Fields that are absent on both runs (e.g. spyglass_src_commit, model)
    # must NOT be flagged changed even though the writer normalizes None to
    # "" — guards against the "None" stringification false positive.
    src = prov["fields"]["spyglass_src_commit"]
    if src["changed"] or src["old"] == "None" or src["new"] == "None":
        raise AssertionError(
            f"spyglass_src_commit (absent on synthetic fixture) should be empty/unchanged: {src}"
        )

    # provenance_diff: grader_model drifted between runs (old=old-grader-model,
    # new=new-grader-model) so it must be flagged changed and tagged causal.
    # grader_prompt_sha256 stays stable; it must NOT be flagged.
    grader_model = prov["fields"]["grader_model"]
    if not grader_model["changed"] or grader_model.get("kind") != "causal":
        raise AssertionError(
            f"grader_model drift should be flagged causal: {grader_model}"
        )
    grader_prompt_sha = prov["fields"]["grader_prompt_sha256"]
    if grader_prompt_sha["changed"]:
        raise AssertionError(
            f"grader_prompt_sha256 stable both sides should not flag: {grader_prompt_sha}"
        )

    # regression_root_cause.csv: synthetic fixture has eval 3 (regressed,
    # rubric_friction taxonomy) and eval 4 (stable_fail, rubric_friction
    # taxonomy). Both should bucket as "rubric".
    with (out / "data/regression_root_cause.csv").open(newline="") as f:
        rc_rows = list(csv.DictReader(f))
    rc_by_id = {int(r["eval_id"]): r for r in rc_rows}
    if sorted(rc_by_id) != [3, 4]:
        raise AssertionError(
            f"regression_root_cause should classify evals 3 and 4 only: {sorted(rc_by_id)}"
        )
    for eid in (3, 4):
        if rc_by_id[eid]["root_cause"] != "rubric":
            raise AssertionError(
                f"eval {eid} should classify as rubric on synthetic fixture: {rc_by_id[eid]}"
            )
    rc_summary = json.loads(
        (out / "data/regression_root_cause_summary.json").read_text()
    )
    # Eval 3 is a strict ws regression; eval 4 is stable_fail labeled
    # rubric_friction. Both feed the review queue but only one is a
    # strict regression — the summary must surface both counts honestly
    # so c09's "n_review_items=2" is never miscounted as 2 regressions.
    if rc_summary["n_review_items"] != 2 or rc_summary["buckets"]["rubric"] != 2:
        raise AssertionError(
            f"regression_root_cause_summary should report 2 rubric: {rc_summary}"
        )
    if rc_summary["n_ws_regressions"] != 1:
        raise AssertionError(
            f"n_ws_regressions should be 1 (eval 3 only): {rc_summary}"
        )
    if rc_summary["n_rubric_friction_stable_fail"] != 1:
        raise AssertionError(
            f"n_rubric_friction_stable_fail should be 1 (eval 4 only): {rc_summary}"
        )
    if "n_regressions" in rc_summary:
        raise AssertionError(
            f"obsolete n_regressions key should be gone: {rc_summary}"
        )

    # Direct classifier branch tests: covers each rule independently, since
    # the end-to-end fixture only exercises the rubric branch.
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        from compare.writers import _classify_regression
    finally:
        sys.path.pop(0)

    def _classify(**overrides):
        defaults = dict(
            regression_interpretation="content_regression",
            failure_type_new="",
            ref_recall_delta=0.0,
            script_recall_delta=0.0,
            unexpected_ref_delta=0,
            unexpected_script_delta=0,
            tool_errors_delta=0,
            duration_ratio=1.0,
            has_routing=True,
            has_required_refs=True,
        )
        defaults.update(overrides)
        return _classify_regression(**defaults)

    classifier_cases = {
        "rubric (interp)": (
            {"regression_interpretation": "rubric_friction"},
            "rubric",
        ),
        "rubric (taxonomy)": (
            {"regression_interpretation": "", "failure_type_new": "rubric_friction"},
            "rubric",
        ),
        "routing (ref recall down)": (
            {"ref_recall_delta": -0.5},
            "routing",
        ),
        "routing (script recall down)": (
            {"script_recall_delta": -1.0},
            "routing",
        ),
        "source_selection": (
            {"unexpected_ref_delta": 1},
            "source_selection",
        ),
        "tooling (errors)": (
            {"tool_errors_delta": 3},
            "tooling",
        ),
        "tooling (duration)": (
            {"duration_ratio": 2.5},
            "tooling",
        ),
        "synthesis": ({}, "synthesis"),
        "unknown (no routing)": (
            {"has_routing": False},
            "unknown",
        ),
    }
    for label, (overrides, expected) in classifier_cases.items():
        got = _classify(**overrides)
        if got != expected:
            raise AssertionError(
                f"_classify_regression {label}: expected {expected!r}, got {got!r}"
            )

    # cost_shift.csv duration columns: eval 2 ws timing went 1100 -> 1500
    # tokens, so duration went 11.0s -> 15.0s for a +4.0s delta.
    # Eval 1 ws timing is missing on new -> duration_pair_complete=false too.
    eval2_cost = cost_by_id[2]
    if (
        eval2_cost["ws_duration_pair_complete"] != "true"
        or float(eval2_cost["duration_delta_ws"]) != 4.0
    ):
        raise AssertionError(f"eval 2 ws duration delta should be +4.0s: {eval2_cost}")
    eval1_cost = cost_by_id[1]
    if eval1_cost["ws_duration_pair_complete"] != "false":
        raise AssertionError(f"eval 1 ws duration should be incomplete: {eval1_cost}")

    # category_shift.csv: 4 overlap evals all under (pipeline-usage, joins).
    # Expect 1 cell row + 1 stage rollup + 1 tier rollup + 1 overall = 4 rows.
    with (out / "data/category_shift.csv").open(newline="") as f:
        cat_rows = list(csv.DictReader(f))
    cells = [r for r in cat_rows if r["scope"] == "cell"]
    rollups = [r for r in cat_rows if r["scope"] == "rollup"]
    if len(cells) != 1 or cells[0]["stage"] != "pipeline-usage" or cells[0]["tier"] != "joins":
        raise AssertionError(f"unexpected category cells: {cells}")
    if int(cells[0]["n_evals"]) != 4:
        raise AssertionError(f"category cell should cover 4 evals: {cells[0]}")
    overall = next((r for r in rollups if r["stage"] == "*" and r["tier"] == "*"), None)
    if overall is None or int(overall["n_evals"]) != 4:
        raise AssertionError(f"overall rollup missing or wrong: {overall}")
    # ws_pass_old=2 (evals 1, 3 with ws_pass_old=true), ws_pass_new=2 (evals 1, 2),
    # so ws_delta_pp should be 0 even though individual evals moved.
    if float(overall["ws_pass_old"]) != 2 or float(overall["ws_pass_new"]) != 2:
        raise AssertionError(f"overall ws pass counts wrong: {overall}")

    # regression_review.csv: eval 3 (regressed, rubric_friction) + eval 4
    # (failure_type_new=rubric_friction, stable_fail) = 2 rows. Eval 2 is
    # improved, eval 1 is stable_pass — neither should appear.
    with (out / "data/regression_review.csv").open(newline="") as f:
        review_rows = list(csv.DictReader(f))
    review_ids = sorted(int(r["eval_id"]) for r in review_rows)
    if review_ids != [3, 4]:
        raise AssertionError(
            f"regression_review should cover only evals 3 and 4: {review_ids}"
        )
    eval3_review = next(r for r in review_rows if int(r["eval_id"]) == 3)
    if eval3_review["ws_transition"] != "regressed":
        raise AssertionError(f"eval 3 review row wrong transition: {eval3_review}")
    if not eval3_review["new_response_path"] or not eval3_review["old_response_path"]:
        raise AssertionError(
            f"eval 3 review row should have both response paths: {eval3_review}"
        )

    # INDEX.md: provenance summary line should always be present; the
    # subset-rerun warning should *not* fire here because old=5 and new=5
    # are equal-sized (the warning needs new < 0.5 * old). Round-D vs
    # round-C real-data exercises the warning path separately.
    if "causal provenance dimensions changed" not in index_text:
        raise AssertionError("INDEX.md missing causal-provenance summary line")
    if "Subset rerun" in index_text:
        raise AssertionError(
            "INDEX.md should NOT warn about subset rerun on equal-sized synthetic runs"
        )

    # intent_balance.csv: 4 overlap evals with 4 distinct intents — eval 1
    # should_trigger, eval 2 should_not_trigger, eval 3 near_miss_negative,
    # eval 4 unknown (intent absent on the catalog entry). Joint set
    # excludes eval 4 (bs missing on new), so the `unknown` row has
    # n_evals_overlap=1 but n_evals_with_all_cells=0.
    with (out / "data/intent_balance.csv").open(newline="") as f:
        intent_rows = list(csv.DictReader(f))
    intent_by = {r["intent"]: r for r in intent_rows}
    expected_intents = {"should_trigger", "should_not_trigger", "near_miss_negative", "unknown"}
    if set(intent_by) != expected_intents:
        raise AssertionError(
            f"intent_balance should cover {sorted(expected_intents)}, got {sorted(intent_by)}"
        )
    if int(intent_by["should_trigger"]["n_evals_overlap"]) != 1:
        raise AssertionError(f"should_trigger n_evals_overlap should be 1: {intent_by}")
    if int(intent_by["should_not_trigger"]["n_evals_overlap"]) != 1:
        raise AssertionError(f"should_not_trigger n_evals_overlap should be 1: {intent_by}")
    # Restraint intent (should_not_trigger): eval 2 went bs_fail->bs_fail and
    # ws_fail->ws_pass, so ws_rate_new=100 and skill_lift_new_pp=+100. The
    # writer stays neutral and just reports the number; c10 figures hatch it.
    snt = intent_by["should_not_trigger"]
    if float(snt["skill_lift_new_pp"]) != 100.0:
        raise AssertionError(
            f"should_not_trigger skill_lift_new_pp should be +100 on synthetic: {snt}"
        )
    # Activation columns: eval 2's new ws transcript opens common_tables.md
    # (which is also its required ref) and executes code_graph.py — the
    # skill is NOT staying quiet on a should_not_trigger eval. Verify
    # those activation rates surface so c10 can answer the restraint
    # question directly, not just via pass-rate.
    if int(snt["ws_with_transcript_new"]) != 1:
        raise AssertionError(
            f"should_not_trigger ws_with_transcript_new should be 1: {snt}"
        )
    if float(snt["ws_any_spyglass_ref_open_rate_new"]) != 100.0:
        raise AssertionError(
            f"should_not_trigger ws_any_spyglass_ref_open_rate_new should be 100 "
            f"(skill activated on a restraint eval): {snt}"
        )
    if float(snt["ws_required_ref_open_rate_new"]) != 100.0:
        raise AssertionError(
            f"should_not_trigger ws_required_ref_open_rate_new should be 100: {snt}"
        )
    if float(snt["ws_script_execution_rate_new"]) != 100.0:
        raise AssertionError(
            f"should_not_trigger ws_script_execution_rate_new should be 100: {snt}"
        )
    # Eval 1 (should_trigger) also has new ws transcript with ref + script.
    st = intent_by["should_trigger"]
    if float(st["ws_required_ref_open_rate_new"]) != 100.0:
        raise AssertionError(
            f"should_trigger ws_required_ref_open_rate_new should be 100: {st}"
        )
    # Eval 3 (near_miss_negative): new ws transcript opens ONLY SKILL.md.
    # ws_skill_md_open_rate_new must be 100, but
    # ws_any_spyglass_ref_open_rate_new must be 0 — opening only the skill
    # entrypoint should NOT inflate the spyglass-ref activation count.
    nmn = intent_by["near_miss_negative"]
    if float(nmn["ws_skill_md_open_rate_new"]) != 100.0:
        raise AssertionError(
            f"near_miss_negative ws_skill_md_open_rate_new should be 100: {nmn}"
        )
    if float(nmn["ws_any_spyglass_ref_open_rate_new"]) != 0.0:
        raise AssertionError(
            "near_miss_negative ws_any_spyglass_ref_open_rate_new should be 0 "
            f"(SKILL.md alone must NOT inflate the spyglass-ref rate): {nmn}"
        )
    # Required-ref recall should also be 0 — eval 3 declares
    # common_tables.md as required, but the new ws transcript only
    # opened SKILL.md.
    if float(nmn["ws_required_ref_open_rate_new"]) != 0.0:
        raise AssertionError(
            f"near_miss_negative ws_required_ref_open_rate_new should be 0: {nmn}"
        )
    # Eval 4 (unknown): bs missing on new -> joint excludes it.
    unk = intent_by["unknown"]
    if int(unk["n_evals_overlap"]) != 1 or int(unk["n_evals_with_all_cells"]) != 0:
        raise AssertionError(
            f"unknown bucket should have 1 overlap, 0 joint (eval 4 bs missing): {unk}"
        )

    # Catalog hash must cover intent — the new run inherits the same intent
    # values, so the per-eval intent column being present should not change
    # the semantic hash relative to a hypothetical run with identical evals.
    # Verified indirectly by catalog_diff.json reporting eval 1 ∉ changed
    # (intent matches old/new). Direct check: every changed_evals entry must
    # NOT list "intent" in its fields_changed since synthetic catalog keeps
    # intent stable per eval id.
    for ce in catalog_diff["changed_evals"]:
        if "intent" in ce.get("fields_changed", []):
            raise AssertionError(
                f"intent should not be flagged changed on synthetic fixture: {ce}"
            )

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
