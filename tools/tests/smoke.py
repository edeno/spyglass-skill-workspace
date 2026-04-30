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
    write_json(eval_dir / cond / "timing.json", {"total_tokens": 1000 if cond == "with_skill" else 600})
    out = eval_dir / cond / "outputs" / "response.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("smoke\n")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="spyglass-tools-smoke-") as tmp:
        base = Path(tmp)
        skill = base / "spyglass-skill"
        run = base / "run"
        out = base / "summary"

        evals = {
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
        write_json(skill / "skills/spyglass/evals/evals.json", evals)
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
                            "command": "python skills/spyglass/scripts/code_graph.py describe Session"
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
            "figures/18_failure_taxonomy.png",
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

        with (out / "data/fix_priority.csv").open() as f:
            header = next(csv.reader(f))
        expected_prefix = ["eval_id", "batch", "eval_name", "stage", "tier", "difficulty"]
        if header[:6] != expected_prefix:
            raise AssertionError(f"bad fix_priority prefix: {header[:6]}")

        manifest = json.loads((out / "data/summary_manifest.json").read_text())
        manifest_files = {row["filename"] for row in manifest}
        if "INDEX.md" not in manifest_files or "figures/18_failure_taxonomy.png" not in manifest_files:
            raise AssertionError("manifest missing generated index or plot 18")

    print("smoketest passed")


if __name__ == "__main__":
    main()
