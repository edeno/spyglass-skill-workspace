"""Figure generation for eval summary outputs."""

from __future__ import annotations

import csv
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from _aggregations import collect_behavioral, delta_color, summarize_benchmarks
from _schemas import (
    ANNOTATION_FONTSIZE,
    FIGURE_DPI,
    GRID_STYLE,
    SIZE_COMPACT,
    SIZE_SINGLE,
    SIZE_SQUARE,
    SIZE_TALL,
    SIZE_WIDE,
    WONG,
    EvalCategories,
    PerEvalResult,
    TranscriptRecord,
)
from _transcripts import TRACKED_SCRIPT_ROLES, TRACKED_SCRIPTS, write_transcript_stats

_UNCONFIGURED = Path("/__not_configured__")
OUT: Path = _UNCONFIGURED
FIGURES: Path = _UNCONFIGURED
DATA: Path = _UNCONFIGURED
WORKSPACE: Path = _UNCONFIGURED
BATCH_ORDER: list[int] = []
BATCH_LABELS: dict[int, str] = {}


def configure_figures(
    out: Path, workspace: Path, batch_order: list[int], batch_labels: dict[int, str]
) -> None:
    """Set run-scoped figure globals."""
    global OUT, FIGURES, DATA, WORKSPACE, BATCH_ORDER, BATCH_LABELS
    OUT = out
    FIGURES = OUT / "figures"
    DATA = OUT / "data"
    FIGURES.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    for stale_png in FIGURES.glob("*.png"):
        stale_png.unlink()
    for stale_dir in (FIGURES / "presentation", FIGURES / "analyst", FIGURES / "appendix"):
        if stale_dir.exists():
            shutil.rmtree(stale_dir)
    WORKSPACE = workspace
    BATCH_ORDER = batch_order
    BATCH_LABELS = batch_labels


def figure_path(name: str) -> Path:
    """Return the path for a generated figure."""
    path = FIGURES / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def data_path(name: str) -> Path:
    """Return the path for generated machine-readable data."""
    return DATA / name


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
    fig, ax = plt.subplots(figsize=SIZE_SINGLE, constrained_layout=True)
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
    for i, (ws_r, bs_r) in enumerate(zip(ws_rates, bs_rates, strict=True)):
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
    setup_axes(ax, f"Full-eval pass rate per batch ({sum(n_evals)} evals x 2 conditions)", ylabel="evals fully passing (%)")
    ax.legend(loc="upper right", frameon=False, fontsize=10)
    ax.grid(axis="y", alpha=0.3, linestyle=":")
    fig.savefig(figure_path("appendix_per_batch_pass_rate.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)

def plot_delta_per_batch(benchmarks: dict[int, dict]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=SIZE_WIDE, constrained_layout=True)
    y = np.arange(len(BATCH_ORDER))
    labels = [BATCH_LABELS[b] for b in BATCH_ORDER]
    behavioral_deltas = []
    for b in BATCH_ORDER:
        ws_p, ws_t, bs_p, bs_b_t = collect_behavioral(WORKSPACE, b)
        ws_pp = 100 * ws_p / ws_t if ws_t else 0
        bs_pp = 100 * bs_p / bs_b_t if bs_b_t else 0
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
    x_max = max(max(behavioral_deltas), max(expectation_deltas)) + 5
    for ax, deltas, title in [
        (axes[0], behavioral_deltas, "Behavioral-check delta"),
        (axes[1], expectation_deltas, "Total expectation delta"),
    ]:
        colors = [delta_color(d) for d in deltas]
        bars = ax.barh(y, deltas, color=colors, height=0.7)
        for bar, delta in zip(bars, deltas, strict=True):
            ax.text(
                delta + (0.35 if delta >= 0 else -0.35),
                bar.get_y() + bar.get_height() / 2,
                f"{delta:+.1f}",
                va="center",
                ha="left" if delta >= 0 else "right",
                fontsize=9,
                fontweight="bold",
            )
        ax.axvline(0, color="black", linewidth=0.7)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=9)
        ax.invert_yaxis()
        ax.set_xlim(-3, x_max)
        setup_axes(ax, f"{title} (with_skill - baseline)", xlabel="percentage points (pp)")
        ax.grid(axis="x", alpha=0.3, linestyle=":")
    fig.savefig(figure_path("appendix_delta_per_batch.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)

def plot_per_eval_outcomes(benchmarks: dict[int, dict]) -> None:
    fig, ax = plt.subplots(figsize=SIZE_SINGLE, constrained_layout=True)
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
    setup_axes(ax, "Per-eval outcomes by batch: skill-only vs baseline-only wins", ylabel="number of evals")
    ax.legend(
        loc="upper left",
        bbox_to_anchor=(1.01, 1),
        frameon=False,
        fontsize=9,
        borderaxespad=0,
    )
    ax.grid(axis="y", alpha=0.3, linestyle=":")
    fig.savefig(figure_path("appendix_per_eval_outcomes_by_batch.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)

def plot_tokens_and_duration(benchmarks: dict[int, dict]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=SIZE_WIDE, constrained_layout=True)
    y = np.arange(len(BATCH_ORDER))
    labels = [BATCH_LABELS[b] for b in BATCH_ORDER]
    height = 0.38
    cfgs = [benchmarks[b]["configurations"] for b in BATCH_ORDER]
    ws_tokens = [c["with_skill"]["tokens_mean"] / 1000 for c in cfgs]
    bs_tokens = [c["without_skill"]["tokens_mean"] / 1000 for c in cfgs]
    ws_dur = [c["with_skill"]["duration_mean_s"] for c in cfgs]
    bs_dur = [c["without_skill"]["duration_mean_s"] for c in cfgs]

    for ax, ws_vals, bs_vals, title, xlabel in [
        (axes[0], ws_tokens, bs_tokens, "Mean tokens per run", "tokens (thousands)"),
        (axes[1], ws_dur, bs_dur, "Mean wall-clock duration per run", "seconds"),
    ]:
        ax.barh(y - height / 2, ws_vals, height, label="with skill", color=WONG["ws"])
        ax.barh(y + height / 2, bs_vals, height, label="baseline", color=WONG["bs"])
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=9)
        ax.invert_yaxis()
        setup_axes(ax, title, xlabel=xlabel)
        ax.legend(loc="lower right", frameon=False, fontsize=9)
        ax.grid(axis="x", alpha=0.3, linestyle=":")
    fig.savefig(figure_path("appendix_cost_per_batch.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)

def plot_cumulative_summary(benchmarks: dict[int, dict]) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.5), constrained_layout=True)
    totals = summarize_benchmarks(benchmarks)
    ws, bs = totals["ws"], totals["bs"]
    n_evals = ws["n_runs"]
    rows = [
        ("Evals fully pass", ws["full_pass"], n_evals, bs["full_pass"], n_evals),
        ("Expectations", ws["exp_p"], ws["exp_t"], bs["exp_p"], bs["exp_t"]),
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
    setup_axes(ax, f"Final cumulative result — all {len(BATCH_ORDER)} batches, {n_evals} evals")
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=WONG["ws"], label="with skill"),
        plt.Rectangle((0, 0), 1, 1, color=WONG["bs"], label="baseline"),
    ]
    ax.legend(handles=handles, loc="lower right", frameon=False, fontsize=10)
    ax.grid(axis="x", alpha=0.3, linestyle=":")
    fig.savefig(figure_path("q01_how_much_does_the_skill_help.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)

def plot_by_category(
    cats: EvalCategories, per_eval: list[PerEvalResult]
) -> None:
    """Two-panel: per-eval pass rates grouped by stage and by tier."""

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
        deltas = [w - b for w, b in zip(ws_rates, bs_rates, strict=True)]
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
            ax.text(
                108,
                y[i],
                f"Δ {d:+.0f}pp",
                va="center",
                fontsize=9,
                color=delta_color(d),
                fontweight="bold",
            )

        ax.set_yticks(y)
        ax.set_yticklabels(
            [f"{lab}  (n={n})" for lab, n in zip(labels, counts, strict=True)], fontsize=10
        )
        ax.set_xlim(0, 130)
        ax.set_xticks([0, 25, 50, 75, 100])
        ax.invert_yaxis()
        setup_axes(ax, title, xlabel="% of evals fully passing")
        ax.legend(loc="lower right", frameon=False, fontsize=10)
        ax.grid(axis="x", alpha=0.3, linestyle=":")

    fig.savefig(figure_path("appendix_dense_pass_rate_by_category.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)

def plot_by_difficulty(
    cats: EvalCategories, per_eval: list[PerEvalResult]
) -> None:
    """Per-difficulty pass rate (easy / medium / hard) and outcome breakdown."""
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

    fig, axes = plt.subplots(1, 2, figsize=SIZE_WIDE, constrained_layout=True)

    x = np.arange(len(diff_order))
    width = 0.38
    ws_rates = [100 * agg[d][0] / agg[d][1] if agg[d][1] else 0 for d in diff_order]
    bs_rates = [100 * agg[d][2] / agg[d][1] if agg[d][1] else 0 for d in diff_order]
    counts = [agg[d][1] for d in diff_order]
    axes[0].bar(x - width / 2, ws_rates, width, label="with skill", color=WONG["ws"])
    axes[0].bar(x + width / 2, bs_rates, width, label="baseline", color=WONG["bs"])
    for i, (ws_r, bs_r) in enumerate(zip(ws_rates, bs_rates, strict=True)):
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
        [f"{d}\n(n={n})" for d, n in zip(diff_order, counts, strict=True)], fontsize=10
    )
    axes[0].set_ylim(-15, 115)
    axes[0].set_yticks(np.arange(0, 101, 20))
    setup_axes(axes[0], "Full-eval pass rate by difficulty", ylabel="% passing")
    axes[0].legend(
        loc="lower left",
        bbox_to_anchor=(1.01, 0),
        frameon=False,
        fontsize=9,
        borderaxespad=0,
    )
    axes[0].grid(axis="y", alpha=0.3, linestyle=":")

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
        [f"{d}\n(n={n})" for d, n in zip(diff_order, counts, strict=True)], fontsize=10
    )
    setup_axes(axes[1], "Outcome breakdown by difficulty", ylabel="number of evals")
    axes[1].legend(
        loc="upper left",
        bbox_to_anchor=(1.01, 1),
        frameon=False,
        fontsize=9,
        borderaxespad=0,
    )
    axes[1].grid(axis="y", alpha=0.3, linestyle=":")

    fig.savefig(figure_path("q03_does_it_help_on_harder_evals.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)

def plot_difficulty_x_stage_heatmap(
    cats: EvalCategories, per_eval: list[PerEvalResult]
) -> None:
    """Heatmap: skill delta (pp) by difficulty × stage. Reveals where the skill helps on hard prompts."""
    diff_order = ["easy", "medium", "hard"]

    # Single pass: bucket every per_eval row into both stage_lift (for stage
    # ordering) and cell (stage, difficulty) totals.
    stage_lift: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    cell: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    for r in per_eval:
        cat = cats.get(r["eval_id"], {})
        s = cat.get("stage", "unknown")
        d = cat.get("difficulty", "unknown")
        ws_p, bs_p = int(r["ws_pass"]), int(r["bs_pass"])
        stage_lift[s][0] += ws_p
        stage_lift[s][1] += bs_p
        stage_lift[s][2] += 1
        cell[(s, d)][0] += ws_p
        cell[(s, d)][1] += bs_p
        cell[(s, d)][2] += 1

    stage_order = sorted(
        stage_lift.keys(),
        key=lambda s: -100 * (stage_lift[s][0] - stage_lift[s][1]) / stage_lift[s][2],
    )

    delta = np.full((len(stage_order), len(diff_order)), np.nan)
    counts = np.zeros((len(stage_order), len(diff_order)), dtype=int)
    for i, s in enumerate(stage_order):
        for j, d in enumerate(diff_order):
            ws_p, bs_p, n = cell.get((s, d), [0, 0, 0])
            counts[i, j] = n
            if n > 0:
                delta[i, j] = 100 * (ws_p - bs_p) / n

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
    setup_axes(ax, "Skill delta by stage x difficulty: hard vs easy prompts", xlabel="difficulty")
    fig.savefig(figure_path("appendix_difficulty_x_stage_heatmap.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)

def plot_per_eval_scatter(
    cats: EvalCategories, per_eval: list[PerEvalResult]
) -> None:
    """Per-eval scatter: skill expectation pass rate vs baseline. Each dot is one eval."""

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

    fig, ax = plt.subplots(figsize=SIZE_SQUARE, constrained_layout=True)

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
    n_total = len(ws_rates)
    setup_axes(ax, f"Per-eval scatter: skill vs baseline expectation rate (n={n_total})")

    # Per-difficulty legend uses live counts from this run.
    diff_counts = Counter()
    for r in per_eval:
        if r["ws_exp_t"] == 0:
            continue
        diff_counts[cats.get(r["eval_id"], {}).get("difficulty", "unknown")] += 1
    handles = [
        plt.Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor=diff_color[d],
            markersize=10,
            label=f"{d} (n={diff_counts.get(d, 0)})",
        )
        for d in ("easy", "medium", "hard")
    ] + [plt.Line2D([0], [0], linestyle="--", color="#333333", label="parity (y=x)")]
    ax.legend(handles=handles, loc="lower right", frameon=False, fontsize=9)
    ax.text(
        2, 95, "skill helps\n(above line)", fontsize=9, color="#666666", style="italic"
    )
    ax.text(
        75, 5, "skill hurts\n(below line)", fontsize=9, color="#666666", style="italic"
    )

    fig.savefig(figure_path("appendix_per_eval_expectation_scatter.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)

def plot_top_skill_wins(
    cats: EvalCategories, per_eval: list[PerEvalResult]
) -> None:
    """Write separate figures for largest skill wins and skill regressions."""

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
    regressions = [r for r in sorted(items, key=lambda x: x["delta"]) if r["delta"] < 0]

    def labels(rows: list[dict]) -> list[str]:
        return [
            f"#{r['eval_id']} {r['name']} ({r['stage']}/{r['difficulty']})"
            for r in rows
        ]

    fig, ax = plt.subplots(figsize=SIZE_TALL, constrained_layout=True)
    y = np.arange(len(top))
    deltas = [r["delta"] for r in top]
    ax.barh(y, deltas, color=WONG["delta_pos"], edgecolor="white")
    for yi, r in enumerate(top):
        ax.text(
            r["delta"] + 1,
            yi,
            f"+{r['delta']:.0f} pp  (ws {r['ws_pct']:.0f}% vs bs {r['bs_pct']:.0f}%)",
            va="center",
            ha="left",
            fontsize=8,
        )
    ax.set_yticks(y)
    ax.set_yticklabels(labels(top), fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, max(deltas) + 22 if deltas else 100)
    setup_axes(ax, "Top 15 evals where the skill helped most", xlabel="delta in expectation pass rate (pp)")
    ax.grid(axis="x", **GRID_STYLE)
    fig.savefig(figure_path("appendix_top_skill_wins.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)

    fig_height = max(3.5, 1.0 + 0.8 * max(len(regressions), 1))
    fig, ax = plt.subplots(figsize=(12, fig_height), constrained_layout=True)
    if not regressions:
        ax.text(
            0.5,
            0.5,
            "No evals where the skill scored below baseline",
            ha="center",
            va="center",
            fontsize=12,
            transform=ax.transAxes,
        )
        ax.axis("off")
    else:
        y = np.arange(len(regressions))
        deltas = [r["delta"] for r in regressions]
        ax.barh(y, deltas, color=WONG["delta_neg"], edgecolor="white")
        for yi, r in enumerate(regressions):
            ax.text(
                -0.8,
                yi,
                f"{r['delta']:.0f} pp  (ws {r['ws_pct']:.0f}% vs bs {r['bs_pct']:.0f}%)",
                va="center",
                ha="right",
                fontsize=8,
            )
        ax.set_yticks(y)
        ax.set_yticklabels(labels(regressions), fontsize=9)
        ax.invert_yaxis()
        ax.axvline(0, color="black", linewidth=0.7)
        ax.set_xlim(min(deltas) - 5, 2)
        setup_axes(ax, "Evals where the skill scored worse than baseline", xlabel="delta in expectation pass rate (pp)")
        ax.grid(axis="x", **GRID_STYLE)
    fig.savefig(figure_path("q11_where_are_skill_regressions.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)


def plot_reference_utilization(
    agent_to_run: dict[str, tuple[int, int, str]],
    records: list[TranscriptRecord],
    per_eval: list[PerEvalResult] | None = None,
) -> None:
    """Per-reference utilization plot + ref_utilization.json + transcript_stats.json."""
    total_ws = sum(1 for v in agent_to_run.values() if v[2] == "with_skill")
    total_bs = sum(1 for v in agent_to_run.values() if v[2] == "without_skill")

    ref_runs_using: Counter = Counter()
    for r in records:
        if r["condition"] != "with_skill":
            continue
        for ref in r["ref_opens"]:
            ref_runs_using[ref] += 1

    payload = {
        "total_ws_runs": total_ws,
        "ref_runs_using": dict(ref_runs_using.most_common()),
    }
    (data_path("ref_utilization.json")).write_text(json.dumps(payload, indent=2) + "\n")
    write_transcript_stats(records, total_ws, total_bs, per_eval)

    # SKILL.md is always read by construction — show it in the footer text only.
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
    setup_axes(ax, f"Which reference files got read? Utilization across {total_ws} with_skill runs")
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

    fig.savefig(figure_path("appendix_raw_reference_utilization.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)

def plot_script_utilization(
    agent_to_run: dict[str, tuple[int, int, str]], records: list[TranscriptRecord]
) -> None:
    """Per-script utilization: bundled scripts under skills/spyglass/scripts/.

    Counts Bash tool calls that **executed** each script (not just mentioned its
    filename — see _is_script_execution), plus Read tool calls that opened the
    script source.
    """
    scripts = TRACKED_SCRIPTS
    role = TRACKED_SCRIPT_ROLES

    bash_inv: dict[str, Counter] = defaultdict(Counter)  # script -> {cond: count}
    bash_runs: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    read_inv: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        cond = r["condition"]
        for s, n in r["script_executions"].items():
            bash_inv[s][cond] += n
            bash_runs[s][cond].add(r["agent_id"])
        for s, n in r["script_source_reads"].items():
            read_inv[s][cond] += n

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
    (data_path("script_utilization.json")).write_text(json.dumps(payload, indent=2) + "\n")

    fig, ax = plt.subplots(figsize=(11, 6.5), constrained_layout=True)
    y = np.arange(len(scripts))

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
    setup_axes(ax, f"Which bundled scripts got run? Utilization across {n_ws} with_skill runs")
    ax.legend(
        loc="upper left",
        bbox_to_anchor=(1.01, 1),
        frameon=False,
        fontsize=9,
        borderaxespad=0,
    )
    ax.grid(axis="x", alpha=0.3, linestyle=":")

    any_script_runs = set()
    for s in scripts:
        any_script_runs |= bash_runs[s].get("with_skill", set())
    ax.text(
        0.99,
        -0.12,
        f"{len(any_script_runs)}/{n_ws} ws runs ({100 * len(any_script_runs) / n_ws:.0f}%) invoked at least one script. "
        f"Baseline runs invoked 0 scripts.",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=9,
        style="italic",
        color="#666666",
    )

    fig.savefig(figure_path("appendix_raw_script_utilization.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)



def unlink_figure(name: str) -> None:
    """Remove a generated figure that is invalid for current inputs."""
    try:
        figure_path(name).unlink()
    except FileNotFoundError:
        pass


def _read_csv(name: str) -> list[dict[str, str]]:
    path = data_path(name)
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def plot_reference_effectiveness() -> None:
    """Plot reference load count colored by pass-rate-when-loaded."""
    rows = [r for r in _read_csv("reference_effectiveness.csv") if r["reference"] != "SKILL.md"]
    if not rows:
        unlink_figure("appendix_reference_effectiveness_when_loaded.png")
        return
    rows.sort(key=lambda r: -int(r["ws_evals_loaded"]))
    rows = rows[:25]
    refs = [r["reference"] for r in rows]
    loads = [int(r["ws_evals_loaded"]) for r in rows]
    rates = [float(r["pass_rate_when_loaded"]) for r in rows]
    passed = [int(r["ws_pass_when_loaded"]) for r in rows]
    failed = [int(r["ws_fail_when_loaded"]) for r in rows]

    fig, ax = plt.subplots(figsize=(11, 9), constrained_layout=True)
    y = np.arange(len(refs))
    cmap = plt.cm.RdYlGn
    bars = ax.barh(y, loads, color=[cmap(r / 100) for r in rates], edgecolor="white")
    for i, (bar, rate, n_pass, n_fail) in enumerate(
        zip(bars, rates, passed, failed, strict=True)
    ):
        ax.text(
            bar.get_width() + 0.4,
            i,
            f"{n_pass}/{n_pass + n_fail} pass ({rate:.0f}%)",
            va="center",
            fontsize=ANNOTATION_FONTSIZE,
        )
    ax.set_yticks(y)
    ax.set_yticklabels(refs, fontsize=10, family="monospace")
    ax.invert_yaxis()
    ax.set_xlim(0, max(loads) * 1.5 if loads else 10)
    ax.set_xlabel("# of distinct ws evals that opened the reference", fontsize=10)
    setup_axes(ax, "Appendix diagnostic: reference loads vs pass rate when loaded")
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(0, 100))
    cbar = fig.colorbar(sm, ax=ax, shrink=0.5, pad=0.02)
    cbar.set_label("ws full-pass rate when loaded (%)", fontsize=9)
    ax.grid(axis="x", **GRID_STYLE)
    fig.savefig(figure_path("appendix_reference_effectiveness_when_loaded.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)


def _outcome_from_cost_row(row: dict[str, str]) -> str:
    if int(row["skill_only"]):
        return "skill_only"
    if int(row["baseline_only"]):
        return "baseline_only"
    if int(row["both_fail"]):
        return "both_fail"
    return "both_pass"


def plot_cost_effectiveness_scatter() -> None:
    """Plot extra tokens against expectation delta, colored by outcome."""
    rows = _read_csv("cost_effectiveness_per_eval.csv")
    if not rows:
        unlink_figure("q04_what_does_the_extra_cost_buy.png")
        return
    outcome_colors = {
        "both_pass": WONG["both_pass"],
        "skill_only": WONG["delta_pos"],
        "baseline_only": WONG["delta_neg"],
        "both_fail": WONG["both_fail"],
    }
    outcome_labels = {
        "both_pass": "both pass",
        "skill_only": "skill only",
        "baseline_only": "baseline only",
        "both_fail": "both fail",
    }
    fig, ax = plt.subplots(figsize=(10, 7), constrained_layout=True)
    for outcome in ("skill_only", "baseline_only", "both_fail", "both_pass"):
        subset = [r for r in rows if _outcome_from_cost_row(r) == outcome]
        if not subset:
            continue
        xs = [int(r["extra_tokens"]) / 1000 for r in subset]
        ys = [float(r["delta_expectation_pp"]) for r in subset]
        ax.scatter(
            xs,
            ys,
            label=f"{outcome_labels[outcome]} (n={len(subset)})",
            color=outcome_colors[outcome],
            s=55,
            alpha=0.75,
            edgecolors="white",
            linewidths=0.5,
        )
    ax.axhline(0, color="black", linewidth=0.7, linestyle="--")
    ax.axvline(0, color="black", linewidth=0.7, linestyle="--")

    def row_point(row: dict[str, str]) -> tuple[int, float, int]:
        return int(row["extra_tokens"]), float(row["delta_expectation_pp"]), int(row["eval_id"])

    cheap_wins = sorted(
        (row_point(r) for r in rows if float(r["delta_expectation_pp"]) >= 30 and int(r["extra_tokens"]) < 30000),
        key=lambda p: -p[1],
    )[:5]
    regressions = sorted(
        (row_point(r) for r in rows if int(r["baseline_only"]) or float(r["delta_expectation_pp"]) < 0),
        key=lambda p: p[1],
    )[:5]
    expensive_flat = sorted(
        (row_point(r) for r in rows if float(r["delta_expectation_pp"]) <= 0 and int(r["extra_tokens"]) > 30000),
        key=lambda p: p[1],
    )[:5]
    seen = set()
    for x, y, eid in cheap_wins + regressions + expensive_flat:
        if eid in seen:
            continue
        seen.add(eid)
        ax.annotate(
            f"#{eid}",
            (x / 1000, y),
            fontsize=8,
            ha="left",
            va="bottom" if y >= 0 else "top",
            xytext=(3, 3 if y >= 0 else -3),
            textcoords="offset points",
        )
    ax.set_xlabel("extra tokens (ws − bs), thousands", fontsize=10)
    ax.set_ylabel("expectation delta (pp)", fontsize=10)
    setup_axes(ax, "Cost-effectiveness per eval")
    ax.legend(
        loc="lower left",
        bbox_to_anchor=(1.01, 0),
        frameon=False,
        fontsize=8,
        borderaxespad=0,
    )
    ax.grid(**GRID_STYLE)
    ax.text(
        0.02,
        0.98,
        "higher = skill helps\nright = more extra tokens",
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=9,
        style="italic",
        color="#666666",
    )
    fig.savefig(figure_path("q04_what_does_the_extra_cost_buy.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)


def plot_outcome_by_category() -> None:
    """Plot stage-level outcome split from outcome_by_category.csv."""
    rows = [r for r in _read_csv("outcome_by_category.csv") if r["category_kind"] == "stage"]
    if not rows:
        unlink_figure("q02_where_does_the_skill_help.png")
        return
    rows.sort(key=lambda r: -int(r["skill_only"]))
    labels = [r["category"] for r in rows]
    series = [
        ("both_pass", "both pass", WONG["both_pass"]),
        ("skill_only", "skill only (skill earned its keep)", WONG["delta_pos"]),
        ("baseline_only", "baseline only (skill regression)", WONG["delta_neg"]),
        ("both_fail", "both fail (still hard)", WONG["both_fail"]),
    ]
    fig, ax = plt.subplots(figsize=(11, 6), constrained_layout=True)
    y = np.arange(len(labels))
    bottom = np.zeros(len(labels))
    for field, label, color in series:
        vals = [int(r[field]) for r in rows]
        ax.barh(y, vals, left=bottom, label=label, color=color, edgecolor="white")
        for i, value in enumerate(vals):
            if value > 0:
                ax.text(
                    bottom[i] + value / 2,
                    i,
                    str(value),
                    ha="center",
                    va="center",
                    fontsize=ANNOTATION_FONTSIZE,
                    color="white" if field != "both_pass" else "black",
                    fontweight="bold",
                )
        bottom = bottom + np.array(vals)
    ax.set_yticks(y)
    ax.set_yticklabels(
        [f"{r['category']}  (n={r['n_evals']})" for r in rows], fontsize=10
    )
    ax.invert_yaxis()
    ax.set_xlabel("number of evals", fontsize=10)
    setup_axes(ax, "Outcome by stage: skill-only wins show where the skill matters")
    ax.legend(
        loc="upper left",
        bbox_to_anchor=(1.01, 1),
        frameon=False,
        fontsize=9,
        borderaxespad=0,
    )
    ax.grid(axis="x", **GRID_STYLE)
    fig.savefig(figure_path("q02_where_does_the_skill_help.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)


def plot_baseline_source_split() -> None:
    path = data_path("baseline_source_split.json")
    if not path.exists():
        unlink_figure("q05_is_value_more_than_source_access.png")
        return
    payload = json.loads(path.read_text())
    groups = [
        ("baseline\nno source", payload["baseline_no_source_touched"]),
        ("baseline\nsource touched", payload["baseline_source_touched"]),
        ("with skill\n(all)", payload["with_skill_all"]),
    ]
    fig, ax = plt.subplots(figsize=(8, 5.5), constrained_layout=True)
    x = np.arange(len(groups))
    rates = [g[1]["full_pass_rate"] for g in groups]
    bars = ax.bar(
        x,
        rates,
        color=[WONG["bs"], WONG["neutral"], WONG["ws"]],
        edgecolor="white",
        width=0.6,
    )
    for bar, (_, group) in zip(bars, groups, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            group["full_pass_rate"] + 1.5,
            f"{group['full_pass']}/{group['n']}\n({group['full_pass_rate']:.1f}%)",
            ha="center",
            fontsize=10,
            fontweight="bold",
        )
    ax.set_xticks(x)
    ax.set_xticklabels([g[0] for g in groups], fontsize=10)
    ax.set_ylim(0, 110)
    ax.set_yticks([0, 25, 50, 75, 100])
    setup_axes(
        ax,
        "Three-way split: skill value beyond baseline source access",
        ylabel="full-eval pass rate (%)",
    )
    ax.grid(axis="y", **GRID_STYLE)
    fig.savefig(figure_path("q05_is_value_more_than_source_access.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)


def plot_eval_coverage_map() -> None:
    rows = _read_csv("eval_coverage.csv")
    if not rows:
        unlink_figure("q10_where_are_eval_coverage_gaps.png")
        return
    stages = sorted({r["stage"] for r in rows})
    tiers = sorted({r["tier"] for r in rows})
    matrix = np.zeros((len(stages), len(tiers)), dtype=int)
    for row in rows:
        matrix[stages.index(row["stage"]), tiers.index(row["tier"])] = int(row["n_evals"])
    fig, ax = plt.subplots(
        figsize=(max(8, len(tiers) * 0.7), max(6, len(stages) * 0.5)),
        constrained_layout=True,
    )
    masked = np.ma.masked_equal(matrix, 0)
    im = ax.imshow(masked, cmap="Blues", aspect="auto")
    ax.set_xticks(np.arange(len(tiers)))
    ax.set_xticklabels(tiers, rotation=40, ha="right", fontsize=9)
    ax.set_yticks(np.arange(len(stages)))
    ax.set_yticklabels(stages, fontsize=10)
    for i in range(len(stages)):
        for j in range(len(tiers)):
            count = matrix[i, j]
            if count > 0:
                ax.text(
                    j,
                    i,
                    str(count),
                    ha="center",
                    va="center",
                    fontsize=10,
                    color="white" if count > matrix.max() / 2 else "black",
                )
    fig.colorbar(im, ax=ax, shrink=0.6, label="eval count")
    setup_axes(ax, "Eval coverage by stage x tier: under- and over-tested cells")
    fig.savefig(figure_path("q10_where_are_eval_coverage_gaps.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)


def plot_failure_taxonomy() -> None:
    rows = _read_csv("failure_taxonomy.csv")
    if not rows:
        unlink_figure("appendix_failure_taxonomy_placeholder.png")
        return
    annotated = [r for r in rows if r["failure_type"]]
    if not annotated:
        fig, ax = plt.subplots(figsize=SIZE_COMPACT, constrained_layout=True)
        ax.axis("off")
        ax.text(
            0.5,
            0.58,
            "No failure taxonomy annotations yet",
            ha="center",
            va="center",
            fontsize=14,
            fontweight="bold",
            transform=ax.transAxes,
        )
        ax.text(
            0.5,
            0.42,
            "Fill failure_taxonomy.csv and rerun make_plots.py.",
            ha="center",
            va="center",
            fontsize=11,
            transform=ax.transAxes,
        )
        fig.savefig(figure_path("appendix_failure_taxonomy_placeholder.png"), dpi=FIGURE_DPI, bbox_inches="tight")
        plt.close(fig)
        return
    type_counts = Counter(r["failure_type"] for r in annotated)
    fig, ax = plt.subplots(figsize=SIZE_COMPACT, constrained_layout=True)
    sorted_types = type_counts.most_common()
    labels = [t for t, _ in sorted_types]
    counts = [n for _, n in sorted_types]
    bars = ax.barh(np.arange(len(labels)), counts, color=WONG["delta_neg"], edgecolor="white")
    for bar, count in zip(bars, counts, strict=True):
        ax.text(
            bar.get_width() + 0.2,
            bar.get_y() + bar.get_height() / 2,
            str(count),
            va="center",
            fontsize=10,
            fontweight="bold",
        )
    ax.set_yticks(np.arange(len(labels)))
    ax.set_yticklabels(labels, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel("# of with_skill failures", fontsize=10)
    setup_axes(ax, f"Failure taxonomy: {sum(counts)} of {len(rows)} with-skill failures annotated")
    ax.grid(axis="x", **GRID_STYLE)
    fig.savefig(figure_path("appendix_failure_taxonomy_placeholder.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)


def plot_reference_expected_used() -> None:
    rows = _read_csv("reference_expected_used.csv")
    if not rows:
        unlink_figure("q09_how_well_are_expected_references_used.png")
        return
    refs = sorted({r["reference"] for r in rows})
    statuses = ["required", "optional", "distractor"]
    by_key = {(r["reference"], r["status"]): r for r in rows}
    fig, axes = plt.subplots(1, 2, figsize=(13, max(4, len(refs) * 0.4)), constrained_layout=True)
    for ax, metric, title, cmap in [
        (axes[0], "discoverability", "discoverability (used / expected)", "Greens"),
        (axes[1], "effectiveness", "pass rate when expected ref was used", "RdYlGn"),
    ]:
        matrix = np.full((len(refs), len(statuses)), np.nan)
        sizes = np.zeros((len(refs), len(statuses)), dtype=int)
        for i, ref in enumerate(refs):
            for j, status in enumerate(statuses):
                row = by_key.get((ref, status))
                if not row:
                    continue
                expected = int(row["expected_count"])
                used = int(row["used_count"])
                if metric == "discoverability" and expected:
                    matrix[i, j] = 100 * used / expected
                    sizes[i, j] = expected
                elif metric == "effectiveness" and used:
                    matrix[i, j] = float(row["used_pass_rate"])
                    sizes[i, j] = used
        im = ax.imshow(matrix, cmap=cmap, vmin=0, vmax=100, aspect="auto")
        ax.set_xticks(np.arange(len(statuses)))
        ax.set_xticklabels(statuses, fontsize=10)
        ax.set_yticks(np.arange(len(refs)))
        ax.set_yticklabels(refs, fontsize=8, family="monospace")
        for i in range(len(refs)):
            for j in range(len(statuses)):
                if np.isnan(matrix[i, j]):
                    continue
                n = sizes[i, j]
                alpha = 0.35 if n < 3 else 1.0
                ax.text(
                    j,
                    i,
                    f"{matrix[i, j]:.0f}\nn={n}",
                    ha="center",
                    va="center",
                    fontsize=7,
                    color="black",
                    alpha=alpha,
                )
                if n < 3:
                    ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, edgecolor="#999999", linewidth=0.6, alpha=0.5))
        fig.colorbar(im, ax=ax, shrink=0.5, label="%")
        setup_axes(ax, title)
    fig.savefig(figure_path("q09_how_well_are_expected_references_used.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)


def plot_expected_call_confusion(kind: str) -> None:
    rows = _read_csv(f"{kind}_call_confusion.csv")
    figure_name = (
        "q06_are_reference_routes_working.png"
        if kind == "reference"
        else "q07_are_script_routes_working.png"
    )
    if not rows:
        unlink_figure(figure_name)
        return
    totals = Counter()
    for row in rows:
        for field in (
            "expected_called",
            "expected_not_called",
            "unexpected_called",
            "unexpected_not_called",
        ):
            totals[field] += int(row[field])
    counts = np.array(
        [
            [totals["expected_called"], totals["expected_not_called"]],
            [totals["unexpected_called"], totals["unexpected_not_called"]],
        ],
        dtype=float,
    )
    row_sums = counts.sum(axis=1, keepdims=True)
    pct = np.divide(counts, row_sums, out=np.zeros_like(counts), where=row_sums != 0) * 100
    fig, ax = plt.subplots(figsize=(6.5, 5.5), constrained_layout=True)
    im = ax.imshow(pct, cmap="Blues", vmin=0, vmax=100, aspect="auto")
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["called", "not called"], fontsize=10)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["expected", "not expected"], fontsize=10)
    for i in range(2):
        for j in range(2):
            ax.text(
                j,
                i,
                f"{int(counts[i, j])}\n{pct[i, j]:.1f}%",
                ha="center",
                va="center",
                fontsize=12,
                color="white" if pct[i, j] > 60 else "black",
            )
    fig.colorbar(im, ax=ax, shrink=0.7, label="row-normalized %")
    setup_axes(
        ax,
        f"{kind.title()} called-vs-expected confusion matrix",
        xlabel="Observed in with_skill transcript",
        ylabel="Eval annotation",
    )
    recall = (
        100
        * totals["expected_called"]
        / (totals["expected_called"] + totals["expected_not_called"])
        if totals["expected_called"] + totals["expected_not_called"]
        else 0.0
    )
    precision = (
        100
        * totals["expected_called"]
        / (totals["expected_called"] + totals["unexpected_called"])
        if totals["expected_called"] + totals["unexpected_called"]
        else 0.0
    )
    n_labeled = max((int(row["n_labeled_evals"]) for row in rows), default=0)
    ax.text(
        0.5,
        -0.24,
        f"{n_labeled} labeled evals; recall={recall:.1f}%, precision={precision:.1f}%",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=9,
    )
    fig.savefig(figure_path(figure_name), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)


def plot_fix_priority_actions() -> None:
    rows = [r for r in _read_csv("fix_priority.csv") if r["likely_action"]]
    if not rows:
        unlink_figure("q08_what_should_we_fix_next.png")
        return
    order = {
        "investigate_regression": 0,
        "inspect_transcripts": 1,
        "fix_script_routing": 2,
        "fix_reference_routing": 3,
        "fix_template_or_reference_content": 4,
        "expensive_both_pass": 5,
    }
    counts = Counter(r["likely_action"] for r in rows)
    labels = sorted(counts, key=lambda action: order.get(action, 99))
    values = [counts[label] for label in labels]
    colors = [
        WONG["delta_neg"] if label == "investigate_regression"
        else WONG["delta_pos"] if label.startswith("fix_")
        else WONG["neutral"]
        for label in labels
    ]
    fig, ax = plt.subplots(figsize=(9, 4.8), constrained_layout=True)
    bars = ax.barh(np.arange(len(labels)), values, color=colors, edgecolor="white")
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            bar.get_width() + 0.2,
            bar.get_y() + bar.get_height() / 2,
            str(value),
            va="center",
            fontsize=10,
        )
    ax.set_yticks(np.arange(len(labels)))
    ax.set_yticklabels(labels, fontsize=10, family="monospace")
    ax.invert_yaxis()
    ax.set_xlabel("# evals", fontsize=10)
    setup_axes(ax, "Fix-priority actions — what should the next refactor inspect first?")
    ax.grid(axis="x", **GRID_STYLE)
    fig.savefig(figure_path("q08_what_should_we_fix_next.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)


def plot_extra_tokens_by_outcome() -> None:
    """Show where the skill's extra token spend goes."""
    rows = _read_csv("cost_by_outcome.csv")
    if not rows:
        unlink_figure("q12_where_are_extra_tokens_spent.png")
        return
    order = ["both_pass", "skill_only", "both_fail", "baseline_only"]
    rows_by_outcome = {r["outcome"]: r for r in rows}
    rows = [rows_by_outcome[outcome] for outcome in order if outcome in rows_by_outcome]
    labels = [r["outcome"] for r in rows]
    totals = [int(float(r["total_extra_tokens"])) for r in rows]
    totals_k = [total / 1000 for total in totals]
    shares = [float(r["share_of_total_extra"]) for r in rows]
    ns = [int(r["n"]) for r in rows]
    colors = {
        "both_pass": WONG["both_pass"],
        "skill_only": WONG["delta_pos"],
        "baseline_only": WONG["delta_neg"],
        "both_fail": WONG["both_fail"],
    }

    fig, ax = plt.subplots(figsize=SIZE_SINGLE, constrained_layout=True)
    y = np.arange(len(rows))
    bars = ax.barh(y, totals_k, color=[colors[label] for label in labels])
    for bar, total_k, share, n in zip(bars, totals_k, shares, ns, strict=True):
        ax.text(
            total_k + max(totals_k) * 0.015,
            bar.get_y() + bar.get_height() / 2,
            f"{total_k:.0f}k tokens\n{share:.1f}%, n={n}",
            va="center",
            fontsize=9,
        )
    ax.set_yticks(y)
    ax.set_yticklabels([label.replace("_", " ") for label in labels], fontsize=10)
    ax.invert_yaxis()
    ax.set_xlim(0, max(totals_k) * 1.25 if totals_k else 1)
    ax.set_xlabel("extra with-skill tokens (thousands)", fontsize=10)
    setup_axes(ax, "Where are the extra tokens spent?")
    ax.grid(axis="x", **GRID_STYLE)
    fig.savefig(figure_path("q12_where_are_extra_tokens_spent.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)


def plot_cost_reduction_candidates() -> None:
    """Show high-cost categories where baseline already performs strongly."""
    rows = [r for r in _read_csv("skip_gate_candidates.csv") if r["candidate_reason"]]
    if not rows:
        unlink_figure("q13_where_can_cost_be_reduced.png")
        return
    rows.sort(key=lambda r: -int(float(r["total_extra_tokens"])))
    rows = rows[:10]
    labels = [f"{r['category_kind']}: {r['category']}" for r in rows]
    totals = [int(float(r["total_extra_tokens"])) for r in rows]
    totals_k = [total / 1000 for total in totals]
    reasons = [r["candidate_reason"] for r in rows]
    bs_rates = [float(r["bs_pass_rate"]) for r in rows]
    rescue_rates = [float(r["rescue_rate"]) for r in rows]

    fig, ax = plt.subplots(figsize=SIZE_SINGLE, constrained_layout=True)
    y = np.arange(len(rows))
    bars = ax.barh(y, totals_k, color=WONG["neutral"], edgecolor="white")
    for bar, total_k, bs_rate, rescue_rate, reason in zip(
        bars, totals_k, bs_rates, rescue_rates, reasons, strict=True
    ):
        ax.text(
            total_k + max(totals_k) * 0.015,
            bar.get_y() + bar.get_height() / 2,
            f"{total_k:.0f}k; bs={bs_rate:.0f}%; rescue={rescue_rate:.0f}%\n"
            f"{reason.replace('_', ' ')}",
            va="center",
            fontsize=8,
        )
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, max(totals_k) * 1.45 if totals_k else 1)
    ax.set_xlabel("extra with-skill tokens (thousands)", fontsize=10)
    setup_axes(ax, "Where can skill cost be reduced?")
    ax.grid(axis="x", **GRID_STYLE)
    fig.savefig(figure_path("q13_where_can_cost_be_reduced.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)


def plot_failure_routing_vs_synthesis() -> None:
    """Show whether ws failures are routing misses or loaded-context failures."""
    rows = _read_csv("routing_diagnosis.csv")
    if not rows:
        unlink_figure("q14_are_failures_routing_or_synthesis.png")
        return
    diagnoses = sorted({r["diagnosis"] for r in rows})
    outcomes = ["both_fail", "baseline_only"]
    counts = {
        diagnosis: Counter(r["outcome"] for r in rows if r["diagnosis"] == diagnosis)
        for diagnosis in diagnoses
    }
    colors = {"both_fail": WONG["both_fail"], "baseline_only": WONG["delta_neg"]}

    fig, ax = plt.subplots(figsize=SIZE_SINGLE, constrained_layout=True)
    x = np.arange(len(diagnoses))
    bottom = np.zeros(len(diagnoses))
    for outcome in outcomes:
        values = np.array([counts[diagnosis][outcome] for diagnosis in diagnoses])
        ax.bar(
            x,
            values,
            bottom=bottom,
            label=outcome.replace("_", " "),
            color=colors[outcome],
        )
        bottom += values
    for i, total in enumerate(bottom):
        ax.text(i, total + 0.25, str(int(total)), ha="center", fontsize=10)
    ax.set_xticks(x)
    ax.set_xticklabels(
        [diagnosis.replace("_", " ") for diagnosis in diagnoses],
        rotation=20,
        ha="right",
        fontsize=9,
    )
    ax.set_ylim(0, max(bottom) * 1.25 if len(bottom) else 1)
    ax.set_ylabel("# ws-failed evals", fontsize=10)
    setup_axes(ax, "Are failures routing misses or synthesis/content failures?")
    ax.legend(loc="upper right", frameon=False, fontsize=9)
    ax.grid(axis="y", **GRID_STYLE)
    fig.savefig(figure_path("q14_are_failures_routing_or_synthesis.png"), dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)
