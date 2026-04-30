"""Run and eval metadata loaders for eval summary generation."""

from __future__ import annotations

import json
from pathlib import Path

from _schemas import EvalCategories, ExpectedResources, PerEvalResult


def load_batch_labels(run_dir: Path, batch_order: list[int]) -> dict[int, str]:
    """Read run.json's optional `batches` block; fill missing entries with `B{i}`."""
    run_meta_path = run_dir / "run.json"
    cfg: dict[str, dict] = {}
    if run_meta_path.is_file():
        try:
            cfg = json.loads(run_meta_path.read_text()).get("batches", {})
        except (json.JSONDecodeError, OSError):
            cfg = {}
    return {b: cfg.get(str(b), {}).get("label", f"B{b}") for b in batch_order}


def load_benchmarks(workspace: Path, batch_order: list[int]) -> dict[int, dict]:
    """Read every iteration-N/benchmark.json for the run."""
    return {
        i: json.loads((workspace / f"iteration-{i}" / "benchmark.json").read_text())
        for i in batch_order
    }


def load_per_eval_timing(
    workspace: Path, batch_order: list[int]
) -> dict[tuple[int, int, str], int]:
    """Map (batch, eval_id, condition) -> total_tokens from timing.json files."""
    out: dict[tuple[int, int, str], int] = {}
    for i in batch_order:
        for eval_dir in (workspace / f"iteration-{i}").glob("eval-*"):
            try:
                eid = int(eval_dir.name.split("-")[1])
            except (IndexError, ValueError):
                continue
            for cond in ("with_skill", "without_skill"):
                tp = eval_dir / cond / "timing.json"
                if not tp.is_file():
                    continue
                try:
                    out[(i, eid, cond)] = int(json.loads(tp.read_text())["total_tokens"])
                except (json.JSONDecodeError, KeyError, OSError, ValueError):
                    continue
    return out


def load_expected_refs(evals_path: Path) -> ExpectedResources:
    """Read optional `expected_refs` annotations from evals.json."""
    return _load_expected_resources(evals_path, "expected_refs")


def load_expected_scripts(evals_path: Path) -> ExpectedResources:
    """Read optional `expected_scripts` annotations from evals.json."""
    return _load_expected_resources(evals_path, "expected_scripts")


def _load_expected_resources(evals_path: Path, key: str) -> ExpectedResources:
    evals = json.loads(evals_path.read_text())["evals"]
    out: ExpectedResources = {}
    for e in evals:
        block = e.get(key)
        if not isinstance(block, dict):
            continue
        out[e["id"]] = {
            "required": list(block.get("required", [])),
            "optional": list(block.get("optional", [])),
            "distractor": list(block.get("distractor", [])),
        }
    return out


def load_eval_categories(evals_path: Path) -> EvalCategories:
    """Map eval_id -> {stage, tier, difficulty}."""
    evals = json.loads(evals_path.read_text())["evals"]
    return {
        e["id"]: {
            "stage": e.get("stage", "unknown"),
            "tier": e.get("tier", "unknown"),
            "difficulty": e.get("difficulty", "unknown"),
        }
        for e in evals
    }


def load_per_eval_results(benchmarks: dict[int, dict]) -> list[PerEvalResult]:
    """Flatten benchmarks into a list of per-eval dicts with both conditions."""
    results = []
    for batch_id, bench in benchmarks.items():
        ws_results = {
            e["eval_id"]: e
            for e in bench["configurations"]["with_skill"]["eval_results"]
        }
        bs_results = {
            e["eval_id"]: e
            for e in bench["configurations"]["without_skill"]["eval_results"]
        }
        for eid, ws_r in ws_results.items():
            bs_r = bs_results.get(
                eid, {"all_passed": False, "passed_count": 0, "total": 0}
            )
            results.append(
                {
                    "eval_id": eid,
                    "eval_name": ws_r["eval_name"],
                    "batch": batch_id,
                    "ws_pass": bool(ws_r["all_passed"]),
                    "bs_pass": bool(bs_r["all_passed"]),
                    "ws_exp_p": ws_r["passed_count"],
                    "ws_exp_t": ws_r["total"],
                    "bs_exp_p": bs_r["passed_count"],
                    "bs_exp_t": bs_r["total"],
                }
            )
    return results
