"""Generate summary plots for the 130-eval Spyglass skill sweep.

Reads benchmark.json from each iteration-N/ workspace and the eval source
metadata from skills/spyglass/evals/evals.json. Produces six figures:

1. Per-batch full-eval pass rate (with vs without skill).
2. Per-batch delta (behavioral and total expectations).
3. Per-batch eval-level outcomes (both pass / skill-only / baseline-only / both fail).
4. Per-batch cost (mean tokens and wall-clock).
5. Cumulative summary (full-pass + expectation pass rate, all 130 evals).
6. Per-CATEGORY breakdown — pass rate by stage and by tier (across all batches).

Run with:
    uv run --with matplotlib --with numpy python make_plots.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent
# WORKSPACE is the run directory containing iteration-N/ siblings of summary/.
WORKSPACE = OUT.parent


def find_skill_root(args_skill_root: Path | None) -> Path:
    """Locate the spyglass-skill repo root.

    Resolution order:
    1. --skill-root CLI arg (explicit override)
    2. SPYGLASS_SKILL environment variable
    3. Sibling-clone convention: ../spyglass-skill/ relative to the workspace repo
    4. Legacy in-tree layout: walk up from this script looking for
       skills/spyglass/SKILL.md (only resolves when this script lived under
       the spyglass-skill repo, before the workspace was extracted).
    """
    marker = ("skills", "spyglass", "SKILL.md")

    if args_skill_root:
        candidate = args_skill_root.expanduser().resolve()
        if (candidate.joinpath(*marker)).is_file():
            return candidate
        raise SystemExit(
            f"--skill-root {candidate} is not a spyglass-skill repo "
            f"(missing {'/'.join(marker)})"
        )

    env_path = os.environ.get("SPYGLASS_SKILL")
    if env_path:
        candidate = Path(env_path).expanduser().resolve()
        if (candidate.joinpath(*marker)).is_file():
            return candidate

    # Sibling-clone default: spyglass-skill-workspace and spyglass-skill cloned
    # next to each other. OUT is summary/; ../ is run dir; ../.. is runs/;
    # ../../.. is the workspace repo root.
    workspace_repo_root = OUT.parent.parent.parent
    sibling = workspace_repo_root.parent / "spyglass-skill"
    if (sibling.joinpath(*marker)).is_file():
        return sibling.resolve()

    # Legacy in-tree layout (this script lived inside spyglass-skill).
    for parent in [OUT, *OUT.parents]:
        if (parent.joinpath(*marker)).is_file():
            return parent

    raise SystemExit(
        "Could not locate spyglass-skill repo. Pass --skill-root <path>, "
        "set SPYGLASS_SKILL=<path>, or clone spyglass-skill as a sibling "
        f"of {workspace_repo_root}."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skill-root",
        type=Path,
        default=None,
        help=(
            "Path to the spyglass-skill repo. Defaults to ../spyglass-skill/ "
            "as a sibling of the workspace repo. Override via this flag or "
            "the SPYGLASS_SKILL environment variable."
        ),
    )
    return parser.parse_args()


# Resolved by main() (or by configure_skill_root() if a caller imports this
# module). Module-level resolution would consume the importer's argv and would
# raise SystemExit if skill-root can't be found, both unfriendly for notebook
# / test imports.
EVALS_PATH: Path | None = None


def configure_skill_root(skill_root: Path | None = None) -> None:
    """Resolve the skill repo and set EVALS_PATH. Called from main().

    Importers that want to call individual plot functions can call this
    directly (passing an explicit path) instead of going through main().
    """
    global EVALS_PATH
    repo = find_skill_root(skill_root)
    EVALS_PATH = repo / "skills" / "spyglass" / "evals" / "evals.json"

WONG = {
    "ws": "#0072B2",
    "bs": "#D55E00",
    "delta_pos": "#009E73",
    "delta_neg": "#CC79A7",
    "neutral": "#999999",
    "both_pass": "#56B4E9",
    "both_fail": "#666666",
}

BATCH_ORDER = [1, 2, 3, 4, 5, 6, 7]
BATCH_LABELS = {
    1: "B1\nkey hygiene\n+ merge",
    2: "B2\nhallucination",
    3: "B3\npipeline-use 1",
    4: "B4\npipeline-use 2",
    5: "B5\nparam +\ncounterfactual",
    6: "B6\nruntime\ndebug",
    7: "B7\nsetup / ingest /\nauthoring / adv",
}


def load_benchmarks() -> dict[int, dict]:
    return {
        i: json.loads((WORKSPACE / f"iteration-{i}" / "benchmark.json").read_text())
        for i in BATCH_ORDER
    }


def load_eval_categories() -> dict[int, dict[str, str]]:
    """Map eval_id -> {stage, tier, difficulty}."""
    if EVALS_PATH is None:
        raise RuntimeError(
            "EVALS_PATH not set. Call configure_skill_root() (or main()) first."
        )
    evals = json.loads(EVALS_PATH.read_text())["evals"]
    return {
        e["id"]: {
            "stage": e.get("stage", "unknown"),
            "tier": e.get("tier", "unknown"),
            "difficulty": e.get("difficulty", "unknown"),
        }
        for e in evals
    }


def load_per_eval_results(benchmarks: dict[int, dict]) -> list[dict]:
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


def collect_behavioral(batch_id: int) -> tuple[int, int, int, int]:
    """Return (ws_pass, ws_total, bs_pass, bs_total) on behavioral checks for a batch.

    Walks each eval_dir/{with_skill,without_skill}/grading.json. Skips runs whose
    grading.json is missing (e.g. a malformed eval directory) — those should be
    rare; we log them but don't crash the pipeline.
    """
    ws_p = ws_t = bs_p = bs_t = 0
    for eval_dir in (WORKSPACE / f"iteration-{batch_id}").glob("eval-*"):
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


def setup_axes(ax, title: str, xlabel: str = "", ylabel: str = "") -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_title(title, fontsize=11, loc="left", pad=8)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=10)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=10)
    ax.tick_params(labelsize=9)


def plot_per_batch_pass_rate(benchmarks: dict[int, dict]) -> None:
    fig, ax = plt.subplots(figsize=(10, 5.5), constrained_layout=True)
    x = np.arange(len(BATCH_ORDER))
    width = 0.38
    ws_rates, bs_rates, n_evals = [], [], []
    for b in BATCH_ORDER:
        cfg = benchmarks[b]["configurations"]
        ws_rates.append(
            100 * cfg["with_skill"]["evals_full_pass"] / cfg["with_skill"]["n_runs"]
        )
        bs_rates.append(
            100
            * cfg["without_skill"]["evals_full_pass"]
            / cfg["without_skill"]["n_runs"]
        )
        n_evals.append(cfg["with_skill"]["n_runs"])
    ax.bar(x - width / 2, ws_rates, width, label="with skill", color=WONG["ws"])
    ax.bar(x + width / 2, bs_rates, width, label="baseline", color=WONG["bs"])
    for i, (ws_r, bs_r) in enumerate(zip(ws_rates, bs_rates)):
        ax.text(
            i - width / 2,
            ws_r + 1.5,
            f"{ws_r:.0f}%",
            ha="center",
            fontsize=8,
            color=WONG["ws"],
        )
        ax.text(
            i + width / 2,
            bs_r + 1.5,
            f"{bs_r:.0f}%",
            ha="center",
            fontsize=8,
            color=WONG["bs"],
        )
    ax.set_xticks(x)
    ax.set_xticklabels(
        [f"{BATCH_LABELS[b]}\n(n={n_evals[i]})" for i, b in enumerate(BATCH_ORDER)],
        fontsize=9,
    )
    ax.set_ylim(0, 115)
    ax.set_yticks(np.arange(0, 101, 20))
    setup_axes(ax, "Full-eval pass rate per batch", ylabel="evals fully passing (%)")
    ax.legend(loc="upper right", frameon=False, fontsize=10)
    ax.grid(axis="y", alpha=0.3, linestyle=":")
    fig.suptitle(
        "Spyglass skill — full-eval pass rate per batch (130 evals × 2 conditions)",
        fontsize=12,
        y=1.02,
    )
    fig.savefig(OUT / "01_per_batch_pass_rate.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_delta_per_batch(benchmarks: dict[int, dict]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), constrained_layout=True)
    x = np.arange(len(BATCH_ORDER))
    behavioral_deltas = []
    for b in BATCH_ORDER:
        ws_p, ws_t, bs_p, bs_t = collect_behavioral(b)
        ws_pp = 100 * ws_p / ws_t if ws_t else 0
        bs_pp = 100 * bs_p / bs_t if bs_t else 0
        behavioral_deltas.append(ws_pp - bs_pp)
    # Compute expectation deltas directly from configurations (older batches store delta in
    # fractional form `expectation_pass_rate`, newer ones in percentage points
    # `expectation_pass_rate_pp`; recomputing avoids that schema drift).
    expectation_deltas = []
    for b in BATCH_ORDER:
        cfg = benchmarks[b]["configurations"]
        ws_pp = (
            100
            * cfg["with_skill"]["expectations_passed"]
            / cfg["with_skill"]["expectations_total"]
        )
        bs_pp = (
            100
            * cfg["without_skill"]["expectations_passed"]
            / cfg["without_skill"]["expectations_total"]
        )
        expectation_deltas.append(ws_pp - bs_pp)
    for ax, deltas, title in [
        (axes[0], behavioral_deltas, "Behavioral-check delta (with_skill − baseline)"),
        (
            axes[1],
            expectation_deltas,
            "Total expectation delta (with_skill − baseline)",
        ),
    ]:
        colors = [
            WONG["delta_pos"]
            if d > 0
            else WONG["delta_neg"]
            if d < 0
            else WONG["neutral"]
            for d in deltas
        ]
        bars = ax.bar(x, deltas, color=colors, width=0.7)
        for bar, d in zip(bars, deltas):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                d + (0.6 if d >= 0 else -1.5),
                f"{d:+.1f}",
                ha="center",
                fontsize=9,
                fontweight="bold",
            )
        ax.axhline(0, color="black", linewidth=0.7)
        ax.set_xticks(x)
        ax.set_xticklabels([BATCH_LABELS[b] for b in BATCH_ORDER], fontsize=9)
        ax.set_ylim(-3, max(max(behavioral_deltas), max(expectation_deltas)) + 5)
        setup_axes(ax, title, ylabel="percentage points (pp)")
        ax.grid(axis="y", alpha=0.3, linestyle=":")
    fig.suptitle(
        "Skill delta per batch — where with_skill helped most", fontsize=12, y=1.02
    )
    fig.savefig(OUT / "02_delta_per_batch.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_per_eval_outcomes(benchmarks: dict[int, dict]) -> None:
    fig, ax = plt.subplots(figsize=(10, 5.5), constrained_layout=True)
    x = np.arange(len(BATCH_ORDER))
    both_pass, skill_only, bs_only, both_fail = [], [], [], []
    for b in BATCH_ORDER:
        cfg = benchmarks[b]["configurations"]
        ws = {e["eval_id"]: e["all_passed"] for e in cfg["with_skill"]["eval_results"]}
        bs = {
            e["eval_id"]: e["all_passed"] for e in cfg["without_skill"]["eval_results"]
        }
        bp = so = bo = bf = 0
        for eid, ws_pass in ws.items():
            bs_pass = bs.get(eid, False)
            if ws_pass and bs_pass:
                bp += 1
            elif ws_pass:
                so += 1
            elif bs_pass:
                bo += 1
            else:
                bf += 1
        both_pass.append(bp)
        skill_only.append(so)
        bs_only.append(bo)
        both_fail.append(bf)
    bottom = np.zeros(len(BATCH_ORDER))
    series = [
        (both_pass, "both pass", WONG["both_pass"]),
        (skill_only, "skill only", WONG["delta_pos"]),
        (bs_only, "baseline only", WONG["delta_neg"]),
        (both_fail, "both fail", WONG["both_fail"]),
    ]
    for vals, lab, color in series:
        ax.bar(x, vals, width=0.7, bottom=bottom, label=lab, color=color)
        for i, v in enumerate(vals):
            if v > 0:
                ax.text(
                    i,
                    bottom[i] + v / 2,
                    str(v),
                    ha="center",
                    va="center",
                    fontsize=9,
                    color="white" if lab != "both pass" else "black",
                    fontweight="bold",
                )
        bottom = bottom + np.array(vals)
    ax.set_xticks(x)
    ax.set_xticklabels([BATCH_LABELS[b] for b in BATCH_ORDER], fontsize=9)
    setup_axes(ax, "Per-eval outcomes by batch", ylabel="number of evals")
    ax.legend(
        loc="upper left", frameon=False, fontsize=10, ncol=4, bbox_to_anchor=(0, 1.08)
    )
    ax.grid(axis="y", alpha=0.3, linestyle=":")
    fig.suptitle("Skill-only vs baseline-only wins per batch", fontsize=12, y=1.04)
    fig.savefig(OUT / "03_per_eval_outcomes.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_tokens_and_duration(benchmarks: dict[int, dict]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), constrained_layout=True)
    x = np.arange(len(BATCH_ORDER))
    width = 0.38
    ws_tokens = [
        benchmarks[b]["configurations"]["with_skill"]["tokens_mean"] / 1000
        for b in BATCH_ORDER
    ]
    bs_tokens = [
        benchmarks[b]["configurations"]["without_skill"]["tokens_mean"] / 1000
        for b in BATCH_ORDER
    ]
    ws_dur = [
        benchmarks[b]["configurations"]["with_skill"]["duration_mean_s"]
        for b in BATCH_ORDER
    ]
    bs_dur = [
        benchmarks[b]["configurations"]["without_skill"]["duration_mean_s"]
        for b in BATCH_ORDER
    ]
    axes[0].bar(x - width / 2, ws_tokens, width, label="with skill", color=WONG["ws"])
    axes[0].bar(x + width / 2, bs_tokens, width, label="baseline", color=WONG["bs"])
    axes[0].set_xticks(x)
    axes[0].set_xticklabels([BATCH_LABELS[b] for b in BATCH_ORDER], fontsize=9)
    setup_axes(axes[0], "Mean tokens per run", ylabel="tokens (thousands)")
    axes[0].legend(loc="upper left", frameon=False, fontsize=10)
    axes[0].grid(axis="y", alpha=0.3, linestyle=":")
    axes[1].bar(x - width / 2, ws_dur, width, label="with skill", color=WONG["ws"])
    axes[1].bar(x + width / 2, bs_dur, width, label="baseline", color=WONG["bs"])
    axes[1].set_xticks(x)
    axes[1].set_xticklabels([BATCH_LABELS[b] for b in BATCH_ORDER], fontsize=9)
    setup_axes(axes[1], "Mean wall-clock duration per run", ylabel="seconds")
    axes[1].legend(loc="upper left", frameon=False, fontsize=10)
    axes[1].grid(axis="y", alpha=0.3, linestyle=":")
    fig.suptitle("Cost: tokens and wall-clock per run", fontsize=12, y=1.02)
    fig.savefig(OUT / "04_cost_per_batch.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_cumulative_summary(benchmarks: dict[int, dict]) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.5), constrained_layout=True)
    ws_full = sum(
        b["configurations"]["with_skill"]["evals_full_pass"]
        for b in benchmarks.values()
    )
    bs_full = sum(
        b["configurations"]["without_skill"]["evals_full_pass"]
        for b in benchmarks.values()
    )
    n_evals = sum(
        b["configurations"]["with_skill"]["n_runs"] for b in benchmarks.values()
    )
    ws_exp_p = sum(
        b["configurations"]["with_skill"]["expectations_passed"]
        for b in benchmarks.values()
    )
    ws_exp_t = sum(
        b["configurations"]["with_skill"]["expectations_total"]
        for b in benchmarks.values()
    )
    bs_exp_p = sum(
        b["configurations"]["without_skill"]["expectations_passed"]
        for b in benchmarks.values()
    )
    bs_exp_t = sum(
        b["configurations"]["without_skill"]["expectations_total"]
        for b in benchmarks.values()
    )
    rows = [
        ("Evals fully pass", ws_full, n_evals, bs_full, n_evals),
        ("Expectations", ws_exp_p, ws_exp_t, bs_exp_p, bs_exp_t),
    ]
    y_positions = np.arange(len(rows))
    bar_height = 0.36
    for i, (_, ws_p, ws_t, bs_p, bs_t) in enumerate(rows):
        ws_pct = 100 * ws_p / ws_t
        bs_pct = 100 * bs_p / bs_t
        ax.barh(y_positions[i] - bar_height / 2, ws_pct, bar_height, color=WONG["ws"])
        ax.barh(y_positions[i] + bar_height / 2, bs_pct, bar_height, color=WONG["bs"])
        ax.text(
            ws_pct + 0.5,
            y_positions[i] - bar_height / 2,
            f"{ws_p}/{ws_t} ({ws_pct:.1f}%)",
            va="center",
            fontsize=10,
            color=WONG["ws"],
            fontweight="bold",
        )
        ax.text(
            bs_pct + 0.5,
            y_positions[i] + bar_height / 2,
            f"{bs_p}/{bs_t} ({bs_pct:.1f}%)",
            va="center",
            fontsize=10,
            color=WONG["bs"],
            fontweight="bold",
        )
        ax.text(
            101,
            y_positions[i],
            f"Δ +{ws_pct - bs_pct:.1f}pp",
            va="center",
            fontsize=10,
            color="black",
            fontweight="bold",
        )
    ax.set_yticks(y_positions)
    ax.set_yticklabels([r[0] for r in rows], fontsize=11)
    ax.set_xlim(0, 120)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("% passing", fontsize=10)
    ax.invert_yaxis()
    setup_axes(ax, "Cumulative — all 7 batches, 130 evals")
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=WONG["ws"], label="with skill"),
        plt.Rectangle((0, 0), 1, 1, color=WONG["bs"], label="baseline"),
    ]
    ax.legend(handles=handles, loc="lower right", frameon=False, fontsize=10)
    ax.grid(axis="x", alpha=0.3, linestyle=":")
    fig.suptitle("Spyglass skill — final cumulative result", fontsize=13, y=1.02)
    fig.savefig(OUT / "05_cumulative_summary.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_by_category(benchmarks: dict[int, dict]) -> None:
    """Two-panel: per-eval pass rates grouped by stage and by tier."""
    cats = load_eval_categories()
    per_eval = load_per_eval_results(benchmarks)

    def aggregate(key: str) -> list[tuple[str, int, int, int, int]]:
        """Return [(category, ws_pass_n, ws_total, bs_pass_n, bs_total), ...] sorted by total desc."""
        agg: dict[str, list[int]] = defaultdict(
            lambda: [0, 0, 0, 0]
        )  # [ws_pass, ws_total, bs_pass, bs_total]
        for r in per_eval:
            cat = cats.get(r["eval_id"], {}).get(key, "unknown")
            agg[cat][0] += int(r["ws_pass"])
            agg[cat][1] += 1
            agg[cat][2] += int(r["bs_pass"])
            agg[cat][3] += 1
        rows: list[tuple[str, int, int, int, int]] = [
            (c, vals[0], vals[1], vals[2], vals[3]) for c, vals in agg.items()
        ]
        rows.sort(key=lambda x: -x[2])
        return rows

    fig, axes = plt.subplots(2, 1, figsize=(12, 13), constrained_layout=True)

    for ax_i, key, title in [
        (0, "stage", "Pass rate by STAGE (high-level eval category)"),
        (1, "tier", "Pass rate by TIER (fine-grained eval category)"),
    ]:
        rows = aggregate(key)
        labels = [r[0] for r in rows]
        ws_rates = [100 * r[1] / r[2] for r in rows]
        bs_rates = [100 * r[3] / r[4] for r in rows]
        deltas = [w - b for w, b in zip(ws_rates, bs_rates)]
        counts = [r[2] for r in rows]

        y = np.arange(len(rows))
        height = 0.38
        ax = axes[ax_i]
        ax.barh(y - height / 2, ws_rates, height, color=WONG["ws"], label="with skill")
        ax.barh(y + height / 2, bs_rates, height, color=WONG["bs"], label="baseline")

        for i in range(len(rows)):
            ax.text(
                ws_rates[i] + 1,
                y[i] - height / 2,
                f"{ws_rates[i]:.0f}%",
                va="center",
                fontsize=8,
                color=WONG["ws"],
            )
            ax.text(
                bs_rates[i] + 1,
                y[i] + height / 2,
                f"{bs_rates[i]:.0f}%",
                va="center",
                fontsize=8,
                color=WONG["bs"],
            )
            d = deltas[i]
            color = (
                WONG["delta_pos"]
                if d > 0
                else WONG["delta_neg"]
                if d < 0
                else WONG["neutral"]
            )
            ax.text(
                108,
                y[i],
                f"Δ {d:+.0f}pp",
                va="center",
                fontsize=9,
                color=color,
                fontweight="bold",
            )

        ax.set_yticks(y)
        ax.set_yticklabels(
            [f"{lab}  (n={n})" for lab, n in zip(labels, counts)], fontsize=10
        )
        ax.set_xlim(0, 130)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.invert_yaxis()
        setup_axes(ax, title, xlabel="% of evals fully passing")
        ax.legend(loc="lower right", frameon=False, fontsize=10)
        ax.grid(axis="x", alpha=0.3, linestyle=":")

    fig.suptitle("Spyglass skill — pass rate by eval category", fontsize=13, y=1.01)
    fig.savefig(OUT / "06_by_category.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_by_difficulty(benchmarks: dict[int, dict]) -> None:
    """Per-difficulty pass rate (easy / medium / hard) and outcome breakdown."""
    cats = load_eval_categories()
    per_eval = load_per_eval_results(benchmarks)
    diff_order = ["easy", "medium", "hard"]

    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0])
    # [ws_pass, total, bs_pass, both_pass, skill_only, bs_only, both_fail]
    outcomes: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])

    for r in per_eval:
        d = cats.get(r["eval_id"], {}).get("difficulty", "unknown")
        agg[d][0] += int(r["ws_pass"])
        agg[d][1] += 1
        agg[d][2] += int(r["bs_pass"])
        if r["ws_pass"] and r["bs_pass"]:
            outcomes[d][0] += 1
        elif r["ws_pass"]:
            outcomes[d][1] += 1
        elif r["bs_pass"]:
            outcomes[d][2] += 1
        else:
            outcomes[d][3] += 1

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), constrained_layout=True)

    # Panel A: pass rate per difficulty.
    x = np.arange(len(diff_order))
    width = 0.38
    ws_rates = [100 * agg[d][0] / agg[d][1] if agg[d][1] else 0 for d in diff_order]
    bs_rates = [100 * agg[d][2] / agg[d][1] if agg[d][1] else 0 for d in diff_order]
    counts = [agg[d][1] for d in diff_order]
    axes[0].bar(x - width / 2, ws_rates, width, label="with skill", color=WONG["ws"])
    axes[0].bar(x + width / 2, bs_rates, width, label="baseline", color=WONG["bs"])
    for i, (ws_r, bs_r) in enumerate(zip(ws_rates, bs_rates)):
        axes[0].text(
            i - width / 2,
            ws_r + 1.5,
            f"{ws_r:.0f}%",
            ha="center",
            fontsize=9,
            color=WONG["ws"],
        )
        axes[0].text(
            i + width / 2,
            bs_r + 1.5,
            f"{bs_r:.0f}%",
            ha="center",
            fontsize=9,
            color=WONG["bs"],
        )
        axes[0].text(
            i, -8, f"Δ +{ws_r - bs_r:.0f}pp", ha="center", fontsize=9, fontweight="bold"
        )
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(
        [f"{d}\n(n={n})" for d, n in zip(diff_order, counts)], fontsize=10
    )
    axes[0].set_ylim(-15, 115)
    axes[0].set_yticks(np.arange(0, 101, 20))
    setup_axes(axes[0], "Full-eval pass rate by difficulty", ylabel="% passing")
    axes[0].legend(loc="lower right", frameon=False, fontsize=10)
    axes[0].grid(axis="y", alpha=0.3, linestyle=":")

    # Panel B: outcome breakdown per difficulty.
    bottom = np.zeros(len(diff_order))
    series = [
        ([outcomes[d][0] for d in diff_order], "both pass", WONG["both_pass"]),
        ([outcomes[d][1] for d in diff_order], "skill only", WONG["delta_pos"]),
        ([outcomes[d][2] for d in diff_order], "baseline only", WONG["delta_neg"]),
        ([outcomes[d][3] for d in diff_order], "both fail", WONG["both_fail"]),
    ]
    for vals, lab, color in series:
        axes[1].bar(x, vals, width=0.6, bottom=bottom, label=lab, color=color)
        for i, v in enumerate(vals):
            if v > 0:
                axes[1].text(
                    i,
                    bottom[i] + v / 2,
                    str(v),
                    ha="center",
                    va="center",
                    fontsize=9,
                    color="white" if lab != "both pass" else "black",
                    fontweight="bold",
                )
        bottom = bottom + np.array(vals)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(
        [f"{d}\n(n={n})" for d, n in zip(diff_order, counts)], fontsize=10
    )
    setup_axes(axes[1], "Outcome breakdown by difficulty", ylabel="number of evals")
    axes[1].legend(
        loc="upper left", frameon=False, fontsize=9, ncol=2, bbox_to_anchor=(0, 1.13)
    )
    axes[1].grid(axis="y", alpha=0.3, linestyle=":")

    fig.suptitle(
        "Spyglass skill — pass rate and outcomes by difficulty", fontsize=12, y=1.02
    )
    fig.savefig(OUT / "07_by_difficulty.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_difficulty_x_stage_heatmap(benchmarks: dict[int, dict]) -> None:
    """Heatmap: skill delta (pp) by difficulty × stage. Reveals where the skill helps on hard prompts."""
    cats = load_eval_categories()
    per_eval = load_per_eval_results(benchmarks)
    diff_order = ["easy", "medium", "hard"]

    # Order stages by total skill lift (across all difficulties).
    stage_lift = defaultdict(lambda: [0, 0, 0])  # [ws_pass, bs_pass, total]
    for r in per_eval:
        s = cats.get(r["eval_id"], {}).get("stage", "unknown")
        stage_lift[s][0] += int(r["ws_pass"])
        stage_lift[s][1] += int(r["bs_pass"])
        stage_lift[s][2] += 1
    stage_order = sorted(
        stage_lift.keys(),
        key=lambda s: -100 * (stage_lift[s][0] - stage_lift[s][1]) / stage_lift[s][2],
    )

    delta = np.full((len(stage_order), len(diff_order)), np.nan)
    counts = np.zeros((len(stage_order), len(diff_order)), dtype=int)
    for i, s in enumerate(stage_order):
        for j, d in enumerate(diff_order):
            ws = bs = n = 0
            for r in per_eval:
                cat = cats.get(r["eval_id"], {})
                if cat.get("stage") == s and cat.get("difficulty") == d:
                    ws += int(r["ws_pass"])
                    bs += int(r["bs_pass"])
                    n += 1
            counts[i, j] = n
            if n > 0:
                delta[i, j] = 100 * (ws - bs) / n

    fig, ax = plt.subplots(figsize=(8, 9), constrained_layout=True)
    cmap = plt.cm.RdYlGn
    im = ax.imshow(delta, cmap=cmap, vmin=-50, vmax=100, aspect="auto")
    ax.set_xticks(np.arange(len(diff_order)))
    ax.set_xticklabels(diff_order, fontsize=11)
    ax.set_yticks(np.arange(len(stage_order)))
    ax.set_yticklabels(stage_order, fontsize=10)
    for i in range(len(stage_order)):
        for j in range(len(diff_order)):
            n = counts[i, j]
            if n == 0:
                ax.text(
                    j, i, "—", ha="center", va="center", fontsize=10, color="#888888"
                )
            else:
                d = delta[i, j]
                color = "white" if d < -10 or d > 50 else "black"
                ax.text(
                    j,
                    i,
                    f"{d:+.0f}\nn={n}",
                    ha="center",
                    va="center",
                    fontsize=9,
                    color=color,
                    fontweight="bold" if d > 0 else "normal",
                )
    cbar = fig.colorbar(im, ax=ax, shrink=0.7, pad=0.02)
    cbar.set_label("skill delta (pp on full-eval pass)", fontsize=10)
    setup_axes(ax, "Skill delta by stage × difficulty (pp)", xlabel="difficulty")
    fig.suptitle(
        "Where does the skill help on HARD prompts vs EASY?", fontsize=12, y=1.01
    )
    fig.savefig(OUT / "08_difficulty_x_stage_heatmap.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_per_eval_scatter(benchmarks: dict[int, dict]) -> None:
    """Per-eval scatter: skill expectation pass rate vs baseline. Each dot is one eval."""
    per_eval = load_per_eval_results(benchmarks)
    cats = load_eval_categories()

    ws_rates, bs_rates, sizes, colors, names = [], [], [], [], []
    diff_color = {
        "easy": "#56B4E9",
        "medium": "#F0E442",
        "hard": "#D55E00",
        "unknown": "#999999",
    }
    for r in per_eval:
        if r["ws_exp_t"] == 0:
            continue
        ws_r = 100 * r["ws_exp_p"] / r["ws_exp_t"]
        bs_r = 100 * r["bs_exp_p"] / r["bs_exp_t"] if r["bs_exp_t"] else 0
        ws_rates.append(ws_r)
        bs_rates.append(bs_r)
        sizes.append(60)
        d = cats.get(r["eval_id"], {}).get("difficulty", "unknown")
        colors.append(diff_color.get(d, "#999999"))
        names.append((r["eval_id"], r["eval_name"], ws_r, bs_r))

    fig, ax = plt.subplots(figsize=(8.5, 8.5), constrained_layout=True)

    # Diagonal y=x; above the line = skill helps.
    ax.plot(
        [0, 100],
        [0, 100],
        "--",
        color="#333333",
        linewidth=1,
        alpha=0.5,
        label="parity (y=x)",
    )
    # Jitter so 100/100 dots don't all stack on a single pixel.
    rng = np.random.default_rng(42)
    jitter_ws = np.array(ws_rates) + rng.uniform(-0.8, 0.8, len(ws_rates))
    jitter_bs = np.array(bs_rates) + rng.uniform(-0.8, 0.8, len(bs_rates))
    ax.scatter(
        jitter_bs,
        jitter_ws,
        s=sizes,
        c=colors,
        alpha=0.7,
        edgecolors="white",
        linewidths=0.5,
    )

    # Annotate the most interesting outliers: large skill wins (skill ≥ 90, baseline ≤ 50).
    for eid, _name, ws_r, bs_r in names:
        if ws_r >= 90 and bs_r <= 50:
            ax.annotate(
                f"#{eid}",
                (bs_r, ws_r),
                fontsize=8,
                ha="left",
                va="bottom",
                xytext=(3, 3),
                textcoords="offset points",
                color=WONG["delta_pos"],
            )
        elif ws_r < bs_r - 15:  # skill substantially worse
            ax.annotate(
                f"#{eid}",
                (bs_r, ws_r),
                fontsize=8,
                ha="left",
                va="top",
                xytext=(3, -3),
                textcoords="offset points",
                color=WONG["delta_neg"],
                fontweight="bold",
            )

    ax.set_xlim(-3, 103)
    ax.set_ylim(-3, 103)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_xlabel("baseline expectation pass rate (%)", fontsize=11)
    ax.set_ylabel("with-skill expectation pass rate (%)", fontsize=11)
    setup_axes(ax, "Per-eval scatter — each point is one of 130 evals")

    handles = [
        plt.Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor=diff_color["easy"],
            markersize=10,
            label="easy (n=35)",
        ),
        plt.Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor=diff_color["medium"],
            markersize=10,
            label="medium (n=62)",
        ),
        plt.Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor=diff_color["hard"],
            markersize=10,
            label="hard (n=33)",
        ),
        plt.Line2D([0], [0], linestyle="--", color="#333333", label="parity (y=x)"),
    ]
    ax.legend(handles=handles, loc="lower right", frameon=False, fontsize=9)
    ax.text(
        2, 95, "skill helps\n(above line)", fontsize=9, color="#666666", style="italic"
    )
    ax.text(
        75, 5, "skill hurts\n(below line)", fontsize=9, color="#666666", style="italic"
    )

    fig.suptitle(
        "Skill vs baseline — per-eval scatter (color = difficulty)", fontsize=12, y=1.02
    )
    fig.savefig(OUT / "09_per_eval_scatter.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_top_skill_wins(benchmarks: dict[int, dict]) -> None:
    """Horizontal bar: top-15 evals where skill helped most (largest passed-count delta)."""
    per_eval = load_per_eval_results(benchmarks)
    cats = load_eval_categories()

    items = []
    for r in per_eval:
        ws_pct = 100 * r["ws_exp_p"] / r["ws_exp_t"] if r["ws_exp_t"] else 0
        bs_pct = 100 * r["bs_exp_p"] / r["bs_exp_t"] if r["bs_exp_t"] else 0
        items.append(
            {
                "eval_id": r["eval_id"],
                "name": r["eval_name"],
                "ws_pct": ws_pct,
                "bs_pct": bs_pct,
                "delta": ws_pct - bs_pct,
                "stage": cats.get(r["eval_id"], {}).get("stage", "unknown"),
                "difficulty": cats.get(r["eval_id"], {}).get("difficulty", "unknown"),
            }
        )

    top = sorted(items, key=lambda x: -x["delta"])[:15]
    bottom = sorted(items, key=lambda x: x["delta"])[:5]
    bottom = [b for b in bottom if b["delta"] < 0]

    fig, axes = plt.subplots(
        2,
        1,
        figsize=(12, 9),
        gridspec_kw={"height_ratios": [3, max(1, len(bottom)) / 5]},
        constrained_layout=True,
    )

    for ax, rows, title, color in [
        (
            axes[0],
            top,
            "Top 15 evals where the SKILL helped most (ranked by Δ pp)",
            WONG["delta_pos"],
        ),
        (
            axes[1],
            bottom,
            "Evals where the SKILL scored WORSE than baseline",
            WONG["delta_neg"],
        ),
    ]:
        if not rows:
            ax.text(
                0.5,
                0.5,
                "(none — no eval where skill scored worse)",
                ha="center",
                va="center",
                fontsize=11,
                transform=ax.transAxes,
            )
            ax.axis("off")
            continue
        y = np.arange(len(rows))
        deltas = [r["delta"] for r in rows]
        labels = [
            f"#{r['eval_id']} {r['name']} ({r['stage']}/{r['difficulty']})"
            for r in rows
        ]
        ax.barh(y, deltas, color=color, edgecolor="white")
        for yi, r in enumerate(rows):
            ax.text(
                r["delta"] + (1 if r["delta"] > 0 else -1),
                yi,
                f"{r['delta']:+.0f} pp  (ws {r['ws_pct']:.0f}% vs bs {r['bs_pct']:.0f}%)",
                va="center",
                ha="left" if r["delta"] > 0 else "right",
                fontsize=8,
            )
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=9)
        ax.invert_yaxis()
        ax.axvline(0, color="black", linewidth=0.7)
        setup_axes(ax, title, xlabel="Δ expectation pass rate (pp)")
        ax.grid(axis="x", alpha=0.3, linestyle=":")

    fig.suptitle(
        "Eval-level extremes — biggest skill wins and the rare losses",
        fontsize=12,
        y=1.01,
    )
    fig.savefig(OUT / "10_top_skill_wins.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def plot_reference_utilization() -> None:
    """Per-reference utilization: % of with_skill runs that opened each reference file.

    Reads subagent transcripts from `transcripts_snapshot/` (committed under
    the workspace, ~14 MB across 267 runs). Each .jsonl file is one subagent's
    full tool-call history. We count Read tool calls into
    `skills/spyglass/references/` and group by run.

    To refresh the snapshot from a live session, see snapshot_transcripts.py
    in this directory.
    """
    snapshot_dir = OUT / "transcripts_snapshot"
    if not snapshot_dir.exists() or not any(snapshot_dir.iterdir()):
        print(
            f"Skipping reference utilization plot: snapshot dir empty at {snapshot_dir}"
        )
        print("  Run snapshot_transcripts.py first to populate it.")
        return

    agent_to_run: dict[str, tuple[int, int, str]] = {}
    for i in BATCH_ORDER:
        m_path = WORKSPACE / f"iteration-{i}" / ".agent_map.json"
        if not m_path.exists():
            continue
        m = json.loads(m_path.read_text())
        for aid, rdir in m.items():
            parts = rdir.split("/")
            eval_dir, cond = parts[-2], parts[-1]
            eid = int(eval_dir.split("-")[1])
            agent_to_run[aid] = (i, eid, cond)

    ref_calls_per_run: dict[tuple[int, int, str], Counter] = defaultdict(Counter)
    for tf in snapshot_dir.iterdir():
        if tf.suffix != ".jsonl":
            continue
        aid = tf.stem
        if aid not in agent_to_run:
            continue
        run_key = agent_to_run[aid]
        for line in tf.read_text().splitlines():
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = obj.get("message", {}).get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                    continue
                if block.get("name") != "Read":
                    continue
                path = (block.get("input") or {}).get("file_path", "")
                if "skills/spyglass/references/" in path:
                    ref = path.split("skills/spyglass/references/")[-1]
                    ref_calls_per_run[run_key][ref] += 1
                elif path.endswith("SKILL.md") and "skills/spyglass/" in path:
                    ref_calls_per_run[run_key]["SKILL.md"] += 1

    total_ws = sum(1 for v in agent_to_run.values() if v[2] == "with_skill")
    ws_keys = [k for k in ref_calls_per_run if k[2] == "with_skill"]

    ref_runs_using: Counter = Counter()
    for run_key in ws_keys:
        for ref in ref_calls_per_run[run_key]:
            ref_runs_using[ref] += 1

    # Drop SKILL.md (always read by construction); plot the references.
    refs = [(r, n) for r, n in ref_runs_using.most_common() if r != "SKILL.md"][:20]

    fig, ax = plt.subplots(figsize=(11, 8), constrained_layout=True)
    y = np.arange(len(refs))
    pcts = [100 * n / total_ws for _, n in refs]
    ax.barh(y, pcts, color=WONG["ws"], edgecolor="white")
    for yi, (_ref, n) in enumerate(refs):
        ax.text(
            pcts[yi] + 0.5,
            yi,
            f"{n}/{total_ws} runs ({pcts[yi]:.1f}%)",
            va="center",
            fontsize=9,
            color=WONG["ws"],
        )
    ax.set_yticks(y)
    ax.set_yticklabels([r for r, _ in refs], fontsize=10, family="monospace")
    ax.invert_yaxis()
    ax.set_xlim(0, max(pcts) * 1.4 if pcts else 100)
    ax.set_xlabel("% of with_skill runs that opened the reference", fontsize=10)
    setup_axes(ax, f"Reference-file utilization across {total_ws} with_skill runs")
    ax.grid(axis="x", alpha=0.3, linestyle=":")
    ax.text(
        0.99,
        0.02,
        f"SKILL.md was read in {100 * ref_runs_using.get('SKILL.md', 0) / total_ws:.0f}% of runs (omitted from plot)",
        transform=ax.transAxes,
        ha="right",
        fontsize=9,
        style="italic",
        color="#666666",
    )

    fig.suptitle("Which reference files actually got read?", fontsize=12, y=1.01)
    fig.savefig(OUT / "11_reference_utilization.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def _is_script_execution(cmd: str, script: str) -> bool:
    """Did this Bash command actually execute the script?

    Required to be preceded by python / python3 / bash / sh / ./ (or be the
    very first token, allowing for env-var prefixes). Bare mentions of the
    filename — e.g. inside a grep, cat, ls, or head argument — do NOT count
    as executions. This prevents a measurement bug where a `grep validate_skill.py
    src.py` was being recorded as an invocation of the validator.
    """
    # Allow a path prefix before the script, e.g. skills/spyglass/scripts/code_graph.py.
    pat = rf"(?:^|[\s|;&])(?:(?:python3?|bash|sh)\s+\S*{re.escape(script)}|\./\S*{re.escape(script)})\b"
    return re.search(pat, cmd) is not None


def plot_script_utilization() -> None:
    """Per-script utilization: bundled scripts under skills/spyglass/scripts/.

    Counts Bash tool calls that **executed** each script (not just mentioned its
    filename — see _is_script_execution), plus Read tool calls that opened the
    script source. Reads from transcripts_snapshot/.
    """
    snapshot_dir = OUT / "transcripts_snapshot"
    if not snapshot_dir.exists() or not any(snapshot_dir.iterdir()):
        print(f"Skipping script utilization plot: snapshot dir empty at {snapshot_dir}")
        return

    scripts = [
        "code_graph.py",  # static FK / source-walker — agent-facing
        "db_graph.py",  # live-DB introspection — agent-facing
        "scrub_dj_config.py",  # password-safe config viewer — agent-facing
        "verify_spyglass_env.py",  # config sanity-check — agent-facing
        "validate_skill.py",  # skill maintainer tool
        "validate_all.sh",  # skill maintainer tool
        "_index.py",  # skill maintainer tool
    ]
    role = {
        "code_graph.py": "agent",
        "db_graph.py": "agent",
        "scrub_dj_config.py": "agent",
        "verify_spyglass_env.py": "agent",
        "validate_skill.py": "maintainer",
        "validate_all.sh": "maintainer",
        "_index.py": "maintainer",
    }

    agent_to_run: dict[str, tuple[int, int, str]] = {}
    for i in BATCH_ORDER:
        m_path = WORKSPACE / f"iteration-{i}" / ".agent_map.json"
        if not m_path.exists():
            continue
        for aid, rdir in json.loads(m_path.read_text()).items():
            parts = rdir.split("/")
            agent_to_run[aid] = (i, int(parts[-2].split("-")[1]), parts[-1])

    bash_inv: dict[str, Counter] = defaultdict(Counter)  # script -> {cond: count}
    bash_runs: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    read_inv: dict[str, Counter] = defaultdict(Counter)
    for tf in snapshot_dir.iterdir():
        if tf.suffix != ".jsonl":
            continue
        aid = tf.stem
        if aid not in agent_to_run:
            continue
        cond = agent_to_run[aid][2]
        for line in tf.read_text().splitlines():
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            for block in obj.get("message", {}).get("content", []):
                if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                    continue
                inp = block.get("input") or {}
                if block.get("name") == "Bash":
                    cmd = inp.get("command", "") or ""
                    for s in scripts:
                        if _is_script_execution(cmd, s):
                            bash_inv[s][cond] += 1
                            bash_runs[s][cond].add(aid)
                elif block.get("name") == "Read":
                    path = inp.get("file_path", "") or ""
                    if "skills/spyglass/scripts/" in path:
                        fname = path.rsplit("/", 1)[-1]
                        if fname in scripts:
                            read_inv[fname][cond] += 1

    n_ws = sum(1 for v in agent_to_run.values() if v[2] == "with_skill")
    n_bs = sum(1 for v in agent_to_run.values() if v[2] == "without_skill")

    # Persist raw counts so the plot is reproducible without re-parsing transcripts.
    any_script_runs_ws: set[str] = set()
    for s in scripts:
        any_script_runs_ws |= bash_runs[s].get("with_skill", set())

    payload = {
        "n_with_skill_runs": n_ws,
        "n_without_skill_runs": n_bs,
        "any_script_with_skill_runs": len(any_script_runs_ws),
        "scripts": [
            {
                "name": s,
                "role": role[s],
                "with_skill": {
                    "bash_invocations": bash_inv[s].get("with_skill", 0),
                    "n_runs_invoking": len(bash_runs[s].get("with_skill", set())),
                    "source_only_reads": read_inv[s].get("with_skill", 0),
                },
                "without_skill": {
                    "bash_invocations": bash_inv[s].get("without_skill", 0),
                    "n_runs_invoking": len(bash_runs[s].get("without_skill", set())),
                    "source_only_reads": read_inv[s].get("without_skill", 0),
                },
            }
            for s in scripts
        ],
    }
    (OUT / "script_utilization.json").write_text(json.dumps(payload, indent=2) + "\n")

    fig, ax = plt.subplots(figsize=(11, 6.5), constrained_layout=True)
    y = np.arange(len(scripts))

    # Two stacked bars per script: invocations (executed) and reads (inspected source).
    invokes_ws = [bash_inv[s].get("with_skill", 0) for s in scripts]
    runs_ws = [len(bash_runs[s].get("with_skill", set())) for s in scripts]
    reads_ws = [read_inv[s].get("with_skill", 0) for s in scripts]

    width = 0.5
    ax.barh(
        y,
        invokes_ws,
        width,
        color=WONG["ws"],
        edgecolor="white",
        label="Bash invocations (executed)",
    )
    ax.barh(
        y,
        reads_ws,
        width,
        left=invokes_ws,
        color=WONG["both_pass"],
        edgecolor="white",
        label="Read calls (inspected source only)",
    )

    for yi in range(len(scripts)):
        total = invokes_ws[yi] + reads_ws[yi]
        n_runs = runs_ws[yi]
        annotation = (
            f"{invokes_ws[yi]} invocations ({n_runs}/{n_ws} ws runs)"
            if invokes_ws[yi]
            else "never invoked"
        )
        if reads_ws[yi]:
            annotation += f"  +{reads_ws[yi]} source reads"
        ax.text(total + 0.5, yi, annotation, va="center", fontsize=9, color="#333333")

    ax.set_yticks(y)
    ax.set_yticklabels(
        [f"{s}\n({role[s]}-facing)" for s in scripts], fontsize=10, family="monospace"
    )
    ax.invert_yaxis()
    ax.set_xlim(0, max(max(invokes_ws), 1) * 1.6)
    ax.set_xlabel("# of tool calls across all with_skill runs", fontsize=10)
    setup_axes(ax, f"Bundled-script utilization across {n_ws} with_skill runs")
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    ax.grid(axis="x", alpha=0.3, linestyle=":")

    any_script_runs = set()
    for s in scripts:
        any_script_runs |= bash_runs[s].get("with_skill", set())
    ax.text(
        0.99,
        0.02,
        f"{len(any_script_runs)}/{n_ws} ws runs ({100 * len(any_script_runs) / n_ws:.0f}%) invoked at least one script.\n"
        f"Baseline runs invoked 0 scripts (as expected — they have no skill exposure).",
        transform=ax.transAxes,
        ha="right",
        fontsize=9,
        style="italic",
        color="#666666",
    )

    fig.suptitle("Which bundled scripts actually got run?", fontsize=12, y=1.01)
    fig.savefig(OUT / "12_script_utilization.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def write_per_category_csv() -> None:
    """Side artifact: detailed numbers behind the category plot."""
    cats = load_eval_categories()
    per_eval = load_per_eval_results(load_benchmarks())
    out_lines = ["category_kind,category,n_evals,ws_pass,bs_pass,delta_pp"]
    for kind in ("stage", "tier", "difficulty"):
        agg: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        for r in per_eval:
            c = cats.get(r["eval_id"], {}).get(kind, "unknown")
            agg[c][0] += 1
            agg[c][1] += int(r["ws_pass"])
            agg[c][2] += int(r["bs_pass"])
        for c, (n, w, b) in sorted(agg.items(), key=lambda x: -x[1][0]):
            d = 100 * (w - b) / n
            out_lines.append(f"{kind},{c},{n},{w},{b},{d:.1f}")
    (OUT / "category_breakdown.csv").write_text("\n".join(out_lines) + "\n")


def main() -> None:
    args = parse_args()
    configure_skill_root(args.skill_root)
    benchmarks = load_benchmarks()
    plot_per_batch_pass_rate(benchmarks)
    plot_delta_per_batch(benchmarks)
    plot_per_eval_outcomes(benchmarks)
    plot_tokens_and_duration(benchmarks)
    plot_cumulative_summary(benchmarks)
    plot_by_category(benchmarks)
    plot_by_difficulty(benchmarks)
    plot_difficulty_x_stage_heatmap(benchmarks)
    plot_per_eval_scatter(benchmarks)
    plot_top_skill_wins(benchmarks)
    plot_reference_utilization()
    plot_script_utilization()
    write_per_category_csv()
    print("Wrote plots + category_breakdown.csv to", OUT)


if __name__ == "__main__":
    main()
