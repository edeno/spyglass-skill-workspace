"""Shared aggregations for eval summary outputs."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from schemas import WONG, PerEvalResult
from scipy.stats import binomtest


def delta_color(d: float) -> str:
    """WONG palette entry for a per-batch / per-category delta."""
    if d > 0:
        return WONG["delta_pos"]
    if d < 0:
        return WONG["delta_neg"]
    return WONG["neutral"]

def summarize_benchmarks(benchmarks: dict[int, dict]) -> dict:
    """Cumulative ws/bs counts across all batches."""
    totals = {"ws": {}, "bs": {}}
    for cond_key, cond_name in (("ws", "with_skill"), ("bs", "without_skill")):
        totals[cond_key] = {
            "full_pass": sum(
                b["configurations"][cond_name]["evals_full_pass"]
                for b in benchmarks.values()
            ),
            "n_runs": sum(
                b["configurations"][cond_name]["n_runs"] for b in benchmarks.values()
            ),
            "exp_p": sum(
                b["configurations"][cond_name]["expectations_passed"]
                for b in benchmarks.values()
            ),
            "exp_t": sum(
                b["configurations"][cond_name]["expectations_total"]
                for b in benchmarks.values()
            ),
            "tokens": sum(
                b["configurations"][cond_name]["tokens_total"]
                for b in benchmarks.values()
            ),
        }
    return totals

def outcome_label(r: PerEvalResult) -> str:
    """2x2 ws/bs outcome label for a per-eval result row."""
    if r["ws_pass"] and r["bs_pass"]:
        return "both_pass"
    if r["ws_pass"]:
        return "skill_only"
    if r["bs_pass"]:
        return "baseline_only"
    return "both_fail"

def count_outcomes(rows: list[PerEvalResult]) -> Counter:
    """Shared outcome counter used by category/cost/fix-priority writers."""
    ctr = Counter(outcome_label(r) for r in rows)
    ctr["__total"] = len(rows)
    return ctr

def build_spend_by_outcome(
    per_eval: list[PerEvalResult], timing: dict[tuple[int, int, str], int]
) -> dict:
    """Aggregate per-eval extra ws tokens by 2x2 outcome (both_pass, skill_only,
    baseline_only, both_fail).

    Per-eval timing.json reads are tolerant of missing files; evals without
    both ws and bs token counts are skipped. The result exposes which outcome
    bucket the skill's extra spend concentrates on — round-c showed 54% of
    extra tokens go to evals baseline already passes, suggesting a
    'do I need the skill on this prompt?' gate could roughly halve cost.
    """
    buckets: dict[str, list[int]] = {
        "both_pass": [], "skill_only": [], "baseline_only": [], "both_fail": []
    }
    for r in per_eval:
        ws_tok = timing.get((r["batch"], r["eval_id"], "with_skill"))
        bs_tok = timing.get((r["batch"], r["eval_id"], "without_skill"))
        if ws_tok is None or bs_tok is None:
            continue
        buckets[outcome_label(r)].append(ws_tok - bs_tok)

    total_extra = sum(sum(v) for v in buckets.values())
    out: dict = {}
    for k, vs in buckets.items():
        if not vs:
            out[k] = {"n": 0, "mean_extra_tokens": 0, "total_extra_tokens": 0, "share_of_total_extra": 0.0}
            continue
        s = sum(vs)
        out[k] = {
            "n": len(vs),
            "mean_extra_tokens": round(sum(vs) / len(vs)),
            "total_extra_tokens": s,
            "share_of_total_extra": round(100 * s / total_extra, 1) if total_extra else 0.0,
        }
    out["note"] = (
        "Where the skill's extra-token spend lands. A high share on "
        "'both_pass' means the skill is paying for verification of evals "
        "baseline would have answered correctly without help — a candidate "
        "for a routing gate. Tokens are per-eval timing.json totals; "
        "evals with missing timing.json (e.g. round-c batch 3 partial) are "
        "skipped."
    )
    return out

def exact_mcnemar_p(b: int, c: int) -> float:
    """Two-sided exact-binomial McNemar p-value for paired binary outcomes.

    Counts discordant pairs only: b = ws-pass-only, c = bs-pass-only.
    Under H0 each discordant pair is 50/50, so the count of (ws-only) is
    Binomial(b+c, 0.5).
    """
    n = b + c
    if n == 0:
        return 1.0
    return float(binomtest(min(b, c), n, p=0.5, alternative="two-sided").pvalue)



def collect_behavioral(workspace: Path, batch_id: int) -> tuple[int, int, int, int]:
    """Return (ws_pass, ws_total, bs_pass, bs_total) on behavioral checks."""
    ws_p = ws_t = bs_p = bs_t = 0
    for eval_dir in (workspace / f"iteration-{batch_id}").glob("eval-*"):
        for cond in ("with_skill", "without_skill"):
            grading_path = eval_dir / cond / "grading.json"
            if not grading_path.exists():
                continue
            grading = json.loads(grading_path.read_text())
            for e in grading["expectations"]:
                if not e["text"].startswith("behavioral_check:"):
                    continue
                if cond == "with_skill":
                    ws_t += 1
                    ws_p += int(bool(e["passed"]))
                else:
                    bs_t += 1
                    bs_p += int(bool(e["passed"]))
    return ws_p, ws_t, bs_p, bs_t
