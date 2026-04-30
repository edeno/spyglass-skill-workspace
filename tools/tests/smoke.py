"""Synthetic smoke test for the eval-sweep plotting pipeline.

Run with the same environment used for plotting, for example:

    uv run --with matplotlib --with numpy python3 tools/tests/smoke.py
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

    print("smoketest passed")


if __name__ == "__main__":
    main()
