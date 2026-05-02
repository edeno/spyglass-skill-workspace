"""Figure generation for cross-run comparison outputs.

Each figure asks one question and reads the staged JSON/CSV the writers
produce, so layout changes don't require re-plumbing data through the
call sites.

- c01 did the headline improve?
- c02 did outcomes move per eval?
- c03 where did evals move in the 2x2 outcome space?
- c04 did targeted edits explain the movement?
- c05 did improvements cost more?
- c06 did routing change? (gated on transcripts on both sides)
- c07 where does category-level pass rate drift?
- c08 did the skill-lift change between commits?
- c09 what is the root-cause distribution of regressions?
- c10 is the eval set balanced for activation behavior, and is skill-lift the right sign per intent?
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
from _schemas import (
    ANNOTATION_FONTSIZE,
    FIGURE_DPI,
    GRID_STYLE,
    OUTCOME_BUCKETS,
    RESTRAINT_INTENTS,
    SIZE_SINGLE,
    SIZE_TALL,
    SIZE_WIDE,
    WONG,
)
from _util import read_csv as _read_csv
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

_TRANSITION_COLOR = {
    "improved": WONG["delta_pos"],
    "regressed": WONG["delta_neg"],
    "stable_pass": WONG["both_pass"],
    "stable_fail": WONG["both_fail"],
}

_OUTCOME_COLOR = {
    "both_pass": WONG["both_pass"],
    "skill_only": WONG["delta_pos"],
    "baseline_only": WONG["delta_neg"],
    "both_fail": WONG["both_fail"],
}
_OUTCOME_ORDER = list(OUTCOME_BUCKETS)
_RESTRAINT_INTENTS = RESTRAINT_INTENTS

_DIVERGING_CMAP = LinearSegmentedColormap.from_list(
    "wong_delta", [WONG["delta_neg"], "#F7F7F7", WONG["delta_pos"]]
)


def plot_headline_shift(figures_dir: Path, data_dir: Path) -> None:
    """c01: paired ws/bs full-pass bars at old vs new, with overlap-n callout.

    Reads headline_diff.json. Bars use n_with_data per condition (which can
    differ from n_overlap when one side has missing cells); the subtitle
    reports the per-condition denominator. Adds a rubric-sensitive label
    when ws_rubric_changed or bs_rubric_changed evals are present.
    """
    path = data_dir / "headline_diff.json"
    if not path.is_file():
        return
    headline = json.loads(path.read_text())
    if "ws_full_pass" not in headline or "bs_full_pass" not in headline:
        return

    ws = headline["ws_full_pass"]
    bs = headline["bs_full_pass"]
    n_overlap = headline.get("overlap_audit", {}).get("n_overlap", 0)
    rubric = headline.get("rubric_sensitive", {})
    n_rubric = headline.get("n_evals_with_rubric_change", {})

    fig, ax = plt.subplots(figsize=SIZE_SINGLE)
    x = [0, 1, 2.5, 3.5]
    heights = [ws["old_rate"], ws["new_rate"], bs["old_rate"], bs["new_rate"]]
    colors = [WONG["ws"], WONG["ws"], WONG["bs"], WONG["bs"]]
    edgecolors = ["white", "black", "white", "black"]
    bars = ax.bar(x, heights, color=colors, edgecolor=edgecolors, linewidth=1.5, width=0.8)
    for bar, value, raw, total in zip(
        bars,
        heights,
        [ws["old"], ws["new"], bs["old"], bs["new"]],
        [ws["n_with_data"], ws["n_with_data"], bs["n_with_data"], bs["n_with_data"]],
        strict=True,
    ):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 1,
            f"{value:.1f}%\n({raw}/{total})",
            ha="center",
            va="bottom",
            fontsize=ANNOTATION_FONTSIZE,
        )

    ax.set_xticks([0.5, 3.0])
    ax.set_xticklabels(["with_skill", "without_skill"])
    ax.set_xticks(x, minor=True)
    ax.set_xticklabels(["old", "new", "old", "new"], minor=True)
    ax.tick_params(axis="x", which="minor", pad=15, labelsize=ANNOTATION_FONTSIZE)
    ax.set_ylabel("full-pass rate (%)")
    ax.set_ylim(0, max(heights + [10]) * 1.25 + 5)
    ax.grid(axis="y", **GRID_STYLE)

    delta_ws = ws["delta_pp"]
    delta_bs = bs["delta_pp"]
    title = (
        f"c01: Headline full-pass shift (overlap n={n_overlap})\n"
        f"with_skill Δ={delta_ws:+.1f}pp ({ws['n_with_data']}/{n_overlap} cells), "
        f"without_skill Δ={delta_bs:+.1f}pp ({bs['n_with_data']}/{n_overlap} cells)"
    )
    ax.set_title(title, fontsize=11)

    notes = []
    if rubric.get("ws"):
        notes.append(f"ws rubric drift: {n_rubric.get('ws', 0)} eval(s)")
    if rubric.get("bs"):
        notes.append(f"bs rubric drift: {n_rubric.get('bs', 0)} eval(s)")
    if not ws.get("complete", True) or not bs.get("complete", True):
        notes.append("partial cells present (see headline_diff.json)")
    if notes:
        fig.text(
            0.5,
            0.01,
            " | ".join(notes),
            ha="center",
            fontsize=ANNOTATION_FONTSIZE,
            color=WONG["neutral"],
        )

    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(figures_dir / "c01_did_the_headline_improve.png", dpi=FIGURE_DPI)
    plt.close(fig)


def plot_outcome_flow(figures_dir: Path, data_dir: Path) -> None:
    """c03: Sankey-lite flow from old outcome buckets to new outcome buckets.

    Reads outcome_2x2_shift.json. Old buckets stack on the left, new buckets
    stack on the right, and a polygon connects each old→new pair sized by
    the flow_matrix count. Diagonal flows (stable cells) are drawn in a
    muted gray; off-diagonal flows use the destination bucket's color so
    movement direction is obvious at a glance.
    """
    path = data_dir / "outcome_2x2_shift.json"
    if not path.is_file():
        return
    data = json.loads(path.read_text())
    n = data.get("n_joint", 0)
    if n == 0:
        return

    flow = data["flow_matrix"]
    counts_old = data["counts_old"]
    counts_new = data["counts_new"]
    excluded = data.get("excluded_eval_ids", []) or []

    fig, ax = plt.subplots(figsize=SIZE_WIDE)
    bar_width = 0.18
    left_x = 0.05
    right_x = 0.95
    gap = 0.5  # between stacked buckets, in count-units
    spacing = gap

    def stack_positions(counts: dict[str, int]) -> dict[str, tuple[float, float]]:
        """Return bucket -> (top, bottom) y-positions stacked top to bottom."""
        total = sum(counts.values()) + spacing * (len(_OUTCOME_ORDER) - 1)
        positions: dict[str, tuple[float, float]] = {}
        cursor = total
        for bucket in _OUTCOME_ORDER:
            top = cursor
            bottom = cursor - counts[bucket]
            positions[bucket] = (top, bottom)
            cursor = bottom - spacing
        return positions

    old_positions = stack_positions(counts_old)
    new_positions = stack_positions(counts_new)

    # Draw the bucket bars.
    for bucket in _OUTCOME_ORDER:
        top, bottom = old_positions[bucket]
        if counts_old[bucket]:
            ax.add_patch(
                plt.Rectangle(
                    (left_x - bar_width, bottom),
                    bar_width,
                    top - bottom,
                    color=_OUTCOME_COLOR[bucket],
                )
            )
            ax.text(
                left_x - bar_width - 0.01,
                (top + bottom) / 2,
                f"{bucket}\nold n={counts_old[bucket]}",
                ha="right",
                va="center",
                fontsize=ANNOTATION_FONTSIZE,
            )
        top, bottom = new_positions[bucket]
        if counts_new[bucket]:
            ax.add_patch(
                plt.Rectangle(
                    (right_x, bottom),
                    bar_width,
                    top - bottom,
                    color=_OUTCOME_COLOR[bucket],
                )
            )
            ax.text(
                right_x + bar_width + 0.01,
                (top + bottom) / 2,
                f"{bucket}\nnew n={counts_new[bucket]}",
                ha="left",
                va="center",
                fontsize=ANNOTATION_FONTSIZE,
            )

    # Draw flow ribbons.
    old_cursor = {b: old_positions[b][0] for b in _OUTCOME_ORDER}
    new_cursor = {b: new_positions[b][0] for b in _OUTCOME_ORDER}
    for old_bucket in _OUTCOME_ORDER:
        for new_bucket in _OUTCOME_ORDER:
            count = flow[old_bucket][new_bucket]
            if not count:
                continue
            old_top = old_cursor[old_bucket]
            old_bottom = old_top - count
            old_cursor[old_bucket] = old_bottom
            new_top = new_cursor[new_bucket]
            new_bottom = new_top - count
            new_cursor[new_bucket] = new_bottom

            color = WONG["neutral"] if old_bucket == new_bucket else _OUTCOME_COLOR[new_bucket]
            alpha = 0.35 if old_bucket == new_bucket else 0.65
            polygon = plt.Polygon(
                [
                    (left_x, old_top),
                    (right_x, new_top),
                    (right_x, new_bottom),
                    (left_x, old_bottom),
                ],
                color=color,
                alpha=alpha,
                linewidth=0,
            )
            ax.add_patch(polygon)

    ax.set_xlim(-0.15, 1.15)
    ymax = max(
        old_positions[_OUTCOME_ORDER[0]][0],
        new_positions[_OUTCOME_ORDER[0]][0],
    )
    ax.set_ylim(-1, ymax + 1)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    excluded_phrase = (
        f", excluded={len(excluded)} (missing ws/bs cells)" if excluded else ""
    )
    ax.set_title(
        f"c03: Outcome-bucket flow on joint set (n={n}{excluded_phrase})\n"
        f"stable={data.get('n_stable', 0)}, changed={data.get('n_changed', 0)}; "
        f"diagonal ribbons gray, movement colored by destination",
        fontsize=11,
    )

    fig.tight_layout()
    fig.savefig(figures_dir / "c03_where_did_evals_move_in_2x2.png", dpi=FIGURE_DPI)
    plt.close(fig)


def plot_per_eval_transitions(figures_dir: Path, data_dir: Path) -> None:
    """c02: per-overlap-eval ws transition bar, hatched on ws_rubric_changed.

    Reads transitions.csv. The bar value is +1 / -1 / 0 based on transition;
    evals with ws-side rubric drift (ws_total_old != ws_total_new) get
    hatching so the eye separates content moves from rubric drift. A
    bs-only rubric change is intentionally not hatched here because it
    does not affect the ws bar's interpretation.
    """
    rows = _read_csv(data_dir / "transitions.csv")
    if not rows:
        return

    rows.sort(key=lambda r: (_transition_sort_key(r["ws_transition"]), int(r["eval_id"])))
    ids = [int(r["eval_id"]) for r in rows]
    transitions = [r["ws_transition"] for r in rows]
    # Hatch only on ws-side rubric drift; a baseline-only rubric change does not
    # affect the with-skill bar's interpretation.
    rubric_changed = [r["ws_rubric_changed"] == "true" for r in rows]
    values = [_transition_value(t) for t in transitions]
    colors = [_TRANSITION_COLOR.get(t, WONG["neutral"]) for t in transitions]

    fig_h = max(4.5, 0.28 * len(rows) + 1.5)
    fig, ax = plt.subplots(figsize=(SIZE_WIDE[0], fig_h))
    y = list(range(len(rows)))
    bars = ax.barh(y, values, color=colors, height=0.7)
    for bar, hatched in zip(bars, rubric_changed, strict=True):
        if hatched:
            bar.set_hatch("///")
            bar.set_edgecolor("white")

    ax.set_yticks(y)
    ax.set_yticklabels([f"{eid}: {r['eval_name']}" for eid, r in zip(ids, rows, strict=True)])
    ax.invert_yaxis()
    ax.axvline(0, color="black", linewidth=0.5)
    ax.set_xlim(-1.4, 1.4)
    ax.set_xticks([-1, 0, 1])
    ax.set_xticklabels(["regressed", "stable", "improved"])
    ax.grid(axis="x", **GRID_STYLE)
    ax.set_title(
        "c02: Per-eval with_skill transitions (overlap only)\n"
        "Hatched: ws_total changed between runs (ws rubric drift, not pure content)",
        fontsize=11,
    )

    counts = Counter(transitions)
    summary = (
        f"n={len(rows)} | improved={counts.get('improved', 0)} | "
        f"regressed={counts.get('regressed', 0)} | "
        f"stable_pass={counts.get('stable_pass', 0)} | "
        f"stable_fail={counts.get('stable_fail', 0)}"
    )
    fig.text(0.5, 0.01, summary, ha="center", fontsize=ANNOTATION_FONTSIZE)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(figures_dir / "c02_did_outcomes_move_per_eval.png", dpi=FIGURE_DPI)
    plt.close(fig)


def plot_targeted_edits(figures_dir: Path, data_dir: Path) -> None:
    """c04: per-edit grouped bars from targeted_edits_summary.csv.

    Skipped if the summary file does not exist (no edit_to_evals declared).
    """
    path = data_dir / "targeted_edits_summary.csv"
    if not path.is_file():
        return
    rows = _read_csv(path)
    if not rows:
        return

    rows.sort(key=lambda r: r["edit_id"])
    edit_ids = [r["edit_id"] for r in rows]
    n_improved = [int(r["n_improved"]) for r in rows]
    n_regressed = [int(r["n_regressed"]) for r in rows]
    n_stable_pass = [int(r["n_stable_pass"]) for r in rows]
    n_stable_fail = [int(r["n_stable_fail"]) for r in rows]
    # Regression count split: rubric-friction-labeled vs other; sum is n_regressed.
    n_regressed_rf = [int(r["n_regressed_rubric_friction"]) for r in rows]
    # Stable-fail rows annotated rubric_friction in the new run; not a regression
    # but a frequent pattern in targeted reruns. Plotted as a hatched overlay
    # on n_stable_fail to surface rubric friction even when nothing regressed.
    n_stable_fail_rf = [
        max(0, int(r["n_failure_type_rubric_friction"]) - int(r["n_regressed_rubric_friction"]))
        for r in rows
    ]

    fig_w = max(SIZE_TALL[0], 1.2 * len(rows) + 4)
    fig, ax = plt.subplots(figsize=(fig_w, 6.5))
    y = list(range(len(rows)))

    n_stable_fail_other = [
        sf - sf_rf for sf, sf_rf in zip(n_stable_fail, n_stable_fail_rf, strict=True)
    ]
    n_regressed_other = [
        rg - rg_rf for rg, rg_rf in zip(n_regressed, n_regressed_rf, strict=True)
    ]

    left = [0.0] * len(rows)
    segments = [
        ("improved", n_improved, _TRANSITION_COLOR["improved"], None),
        ("stable_pass", n_stable_pass, _TRANSITION_COLOR["stable_pass"], None),
        ("stable_fail (other)", n_stable_fail_other, _TRANSITION_COLOR["stable_fail"], None),
        (
            "stable_fail (rubric_friction)",
            n_stable_fail_rf,
            _TRANSITION_COLOR["stable_fail"],
            "///",
        ),
        ("regressed (rubric_friction)", n_regressed_rf, _TRANSITION_COLOR["regressed"], "///"),
        ("regressed (other)", n_regressed_other, _TRANSITION_COLOR["regressed"], None),
    ]
    for label, values, color, hatch in segments:
        bars = ax.barh(y, values, left=left, color=color, height=0.65, label=label)
        if hatch:
            for bar in bars:
                bar.set_hatch(hatch)
                bar.set_edgecolor("white")
        left = [a + b for a, b in zip(left, values, strict=True)]

    ax.set_yticks(y)
    ax.set_yticklabels(edit_ids)
    ax.invert_yaxis()
    ax.set_xlabel("evals in overlap")
    ax.set_title(
        "c04: Targeted-edit outcome counts (overlap only)\n"
        "Hatched: failure_type=rubric_friction in new run's taxonomy "
        "(stable_fail or regressed)",
        fontsize=11,
    )
    ax.grid(axis="x", **GRID_STYLE)
    ax.legend(loc="lower right", fontsize=ANNOTATION_FONTSIZE, framealpha=0.9)

    for yi, row in zip(y, rows, strict=True):
        declared = int(row["n_evals_declared"])
        in_overlap = int(row["n_evals_in_overlap"])
        if declared != in_overlap:
            ax.text(
                0,
                yi,
                f"  ({in_overlap}/{declared} in overlap)",
                va="center",
                ha="left",
                fontsize=ANNOTATION_FONTSIZE - 1,
                color=WONG["neutral"],
            )

    fig.tight_layout()
    fig.savefig(figures_dir / "c04_did_targeted_edits_explain_movement.png", dpi=FIGURE_DPI)
    plt.close(fig)


def plot_cost_shift_by_transition(figures_dir: Path, data_dir: Path) -> None:
    """c05: ws-token delta per overlap eval, split by ws_transition bucket.

    Reads cost_shift.csv. Each bucket gets a horizontal strip of per-eval
    points colored by transition; the bucket mean is drawn as a black tick
    and labeled with both mean and median. Pairs with ws_pair_complete=false
    are excluded (their token_delta_ws is empty); the title reports the
    excluded count so a partial-timing run cannot look complete.
    """
    rows = _read_csv(data_dir / "cost_shift.csv")
    if not rows:
        return
    buckets: dict[str, list[tuple[int, int]]] = {b: [] for b in _COST_BUCKET_ORDER}
    excluded_per_bucket: dict[str, int] = {b: 0 for b in _COST_BUCKET_ORDER}
    bucket_total: dict[str, int] = {b: 0 for b in _COST_BUCKET_ORDER}
    n_excluded = 0
    for row in rows:
        bucket = row["ws_transition"] or "unknown"
        bucket_total.setdefault(bucket, 0)
        bucket_total[bucket] += 1
        if row["ws_pair_complete"] != "true" or row["token_delta_ws"] == "":
            n_excluded += 1
            excluded_per_bucket.setdefault(bucket, 0)
            excluded_per_bucket[bucket] += 1
            continue
        buckets.setdefault(bucket, []).append((int(row["eval_id"]), int(row["token_delta_ws"])))
    if not any(buckets.values()):
        return

    fig, ax = plt.subplots(figsize=SIZE_WIDE)
    y_positions = list(range(len(_COST_BUCKET_ORDER)))
    rng_seed = 0  # deterministic jitter for reproducible figures
    fully_excluded_buckets: list[tuple[str, int]] = []
    empty_buckets: list[str] = []
    for y, bucket in zip(y_positions, _COST_BUCKET_ORDER, strict=True):
        deltas = [d for _, d in buckets.get(bucket, [])]
        n = len(deltas)
        color = _TRANSITION_COLOR.get(bucket, WONG["neutral"])
        if n == 0:
            total = bucket_total.get(bucket, 0)
            if total == 0:
                empty_buckets.append(bucket)
            else:
                # Whole bucket has incomplete ws timing — recorded for the
                # footer note. y-tick label already shows "(0/N timed)", and
                # an inline annotation at y collides with the plot baseline.
                fully_excluded_buckets.append((bucket, total))
            continue
        # Deterministic jitter so points don't stack visually but the figure
        # is reproducible run to run.
        jitter = [_deterministic_jitter(rng_seed, eid) for eid, _ in buckets[bucket]]
        rng_seed += n
        ax.scatter(
            deltas,
            [y + j for j in jitter],
            color=color,
            edgecolor="black",
            linewidth=0.4,
            s=42,
            alpha=0.85,
            zorder=3,
        )
        mean = sum(deltas) / n
        median = sorted(deltas)[n // 2] if n % 2 else (sorted(deltas)[n // 2 - 1] + sorted(deltas)[n // 2]) / 2
        ax.plot(
            [mean, mean],
            [y - 0.32, y + 0.32],
            color="black",
            linewidth=2,
            zorder=4,
        )
        ax.text(
            mean,
            y - 0.42,
            f"mean={int(round(mean)):+d}\nmedian={int(round(median)):+d} (n={n})",
            ha="center",
            va="top",
            fontsize=ANNOTATION_FONTSIZE,
        )

    ax.axvline(0, color="black", linewidth=0.6, alpha=0.4)
    ax.set_yticks(y_positions)
    yticklabels = []
    for bucket in _COST_BUCKET_ORDER:
        n_excl = excluded_per_bucket.get(bucket, 0)
        total = bucket_total.get(bucket, 0)
        if n_excl and total:
            yticklabels.append(f"{bucket}\n({total - n_excl}/{total} timed)")
        else:
            yticklabels.append(bucket)
    ax.set_yticklabels(yticklabels)
    ax.invert_yaxis()
    ax.set_xlabel("ws token delta (new − old, per eval)")
    ax.grid(axis="x", **GRID_STYLE)
    excluded_phrase = (
        f", excluded={n_excluded} (incomplete ws timing)" if n_excluded else ""
    )
    n_plotted = sum(len(v) for v in buckets.values())
    ax.set_title(
        f"c05: With-skill token delta by ws_transition (n={n_plotted}{excluded_phrase})\n"
        "Black tick is the bucket mean; positive = new run cost more on that eval",
        fontsize=11,
    )

    footer_lines: list[str] = []
    if fully_excluded_buckets:
        parts = ", ".join(f"{b} ({t}/{t} excluded)" for b, t in fully_excluded_buckets)
        footer_lines.append(f"No complete ws timing for: {parts}")
    if empty_buckets:
        footer_lines.append(f"No overlap evals in: {', '.join(empty_buckets)}")
    bottom_pad = 0.0
    if footer_lines:
        bottom_pad = 0.04 + 0.025 * len(footer_lines)
        fig.text(
            0.5,
            0.01,
            " | ".join(footer_lines),
            ha="center",
            fontsize=ANNOTATION_FONTSIZE,
            color=WONG["neutral"],
        )

    fig.tight_layout(rect=(0, bottom_pad, 1, 1))
    fig.savefig(figures_dir / "c05_did_improvements_cost_more.png", dpi=FIGURE_DPI)
    plt.close(fig)


_COST_BUCKET_ORDER = ["improved", "stable_pass", "stable_fail", "regressed"]


def plot_routing_shift(figures_dir: Path, data_dir: Path) -> None:
    """c06: per-eval ws required-ref recall and required-script recall deltas.

    Reads routing_shift.csv. Two stacked horizontal bar panels for the ws
    condition (the routing question is "did the skill help the ws agent
    find the right resource"), each showing per-overlap-eval deltas
    (new − old). Bars use the shared delta palette: teal when recall
    improved, magenta when it regressed, gray when stable. Sorted by delta
    within each panel.

    Filters to evals where the eval has at least one required ref/script
    AND routing_complete is true on the ws cell. Excluded counts surface
    in a footer; if a panel has no eligible evals it's labeled explicitly.
    Skipped entirely when routing_shift.csv is absent (transcripts missing
    on one or both runs).
    """
    rows = _read_csv(data_dir / "routing_shift.csv")
    if not rows:
        return
    ws_rows = [r for r in rows if r["condition"] == "with_skill"]

    fig, axes = plt.subplots(2, 1, figsize=(SIZE_WIDE[0], SIZE_WIDE[1] * 1.7))
    panels = [
        (
            axes[0],
            "ref",
            "required reference recall",
            "required_ref_recall_old",
            "required_ref_recall_new",
            "required_ref_recall_delta",
            "has_required_refs",
        ),
        (
            axes[1],
            "script",
            "required bundled-script recall",
            "required_script_recall_old",
            "required_script_recall_new",
            "required_script_recall_delta",
            "has_required_scripts",
        ),
    ]
    footer_lines: list[str] = []
    for ax, kind, ylabel_kind, _old_col, _new_col, delta_col, has_col in panels:
        eligible: list[tuple[int, str, float]] = []
        n_no_required = 0
        n_incomplete = 0
        for r in ws_rows:
            if r[has_col] != "true":
                n_no_required += 1
                continue
            if r["routing_complete"] != "true" or r[delta_col] == "":
                n_incomplete += 1
                continue
            eligible.append((int(r["eval_id"]), r["eval_name"], float(r[delta_col])))
        eligible.sort(key=lambda t: (t[2], t[0]))
        if not eligible:
            ax.text(
                0.5,
                0.5,
                f"No overlap evals with required {kind}s + complete ws transcripts",
                transform=ax.transAxes,
                ha="center",
                va="center",
                color=WONG["neutral"],
                fontsize=ANNOTATION_FONTSIZE,
            )
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_title(f"{ylabel_kind} (ws): no eligible evals", fontsize=11)
            for spine in ax.spines.values():
                spine.set_visible(False)
            if n_incomplete:
                footer_lines.append(
                    f"{kind}: {n_incomplete} eval(s) excluded (incomplete ws transcript)"
                )
            continue

        deltas = [d for _, _, d in eligible]
        labels = [f"{eid}: {name}" for eid, name, _ in eligible]
        colors = [
            WONG["delta_pos"] if d > 0 else WONG["delta_neg"] if d < 0 else WONG["neutral"]
            for d in deltas
        ]
        y = list(range(len(eligible)))
        ax.barh(y, deltas, color=colors, height=0.7)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=ANNOTATION_FONTSIZE)
        ax.invert_yaxis()
        ax.axvline(0, color="black", linewidth=0.6)
        ax.set_xlim(-1.05, 1.05)
        ax.set_xticks([-1.0, -0.5, 0, 0.5, 1.0])
        ax.set_xlabel("recall delta (new − old)")
        ax.grid(axis="x", **GRID_STYLE)
        mean_delta = sum(deltas) / len(deltas)
        n_improved = sum(1 for d in deltas if d > 0)
        n_regressed = sum(1 for d in deltas if d < 0)
        n_stable = sum(1 for d in deltas if d == 0)
        ax.set_title(
            f"{ylabel_kind} (ws): n={len(eligible)}, "
            f"mean Δ={mean_delta:+.2f}, "
            f"improved={n_improved} / stable={n_stable} / regressed={n_regressed}",
            fontsize=11,
        )
        if n_incomplete:
            footer_lines.append(
                f"{kind}: {n_incomplete} eval(s) excluded (incomplete ws transcript)"
            )

    bottom_pad = 0.0
    if footer_lines:
        bottom_pad = 0.04 + 0.025 * len(footer_lines)
        fig.text(
            0.5,
            0.01,
            " | ".join(footer_lines),
            ha="center",
            fontsize=ANNOTATION_FONTSIZE,
            color=WONG["neutral"],
        )
    fig.suptitle(
        "c06: ws routing-recall shift on overlap evals",
        fontsize=12,
    )
    fig.tight_layout(rect=(0, bottom_pad, 1, 0.97))
    fig.savefig(figures_dir / "c06_did_routing_change.png", dpi=FIGURE_DPI)
    plt.close(fig)


def _deterministic_jitter(seed: int, eval_id: int) -> float:
    """Deterministic jitter in [-0.18, 0.18] keyed on (seed, eval_id)."""
    h = (seed * 2654435761 + eval_id * 40503) & 0xFFFFFFFF
    return (h / 0xFFFFFFFF - 0.5) * 0.36


def plot_category_shift(figures_dir: Path, data_dir: Path) -> None:
    """c07: per-(stage, tier) ws full-pass rate delta heatmap.

    Reads category_shift.csv. Renders only the per-(stage, tier) cell rows
    (scope='cell') to avoid mixing rollups with cells in the heatmap.
    Color encodes ws_delta_pp; cell labels show new−old as +/-pp with the
    cell n. Cells where n_ws_with_data == 0 (no eval has both ws cells
    present) are drawn neutral with an "n/a" label so partial dispatches
    don't render as a strong negative.
    """
    rows = [r for r in _read_csv(data_dir / "category_shift.csv") if r["scope"] == "cell"]
    if not rows:
        return
    stages = sorted({r["stage"] for r in rows})
    tiers = sorted({r["tier"] for r in rows})
    if not stages or not tiers:
        return
    cell: dict[tuple[str, str], dict[str, str]] = {(r["stage"], r["tier"]): r for r in rows}

    fig, ax = plt.subplots(
        figsize=(max(SIZE_TALL[0], 1.4 * len(tiers) + 4), max(4.5, 0.7 * len(stages) + 2.5))
    )
    grid = []
    annotations: list[tuple[int, int, str]] = []
    for i, stage in enumerate(stages):
        row_vals = []
        for j, tier in enumerate(tiers):
            r = cell.get((stage, tier))
            if r is None or int(r["n_ws_with_data"]) == 0:
                row_vals.append(float("nan"))
                annotations.append((i, j, "n/a"))
                continue
            delta = float(r["ws_delta_pp"])
            row_vals.append(delta)
            n = r["n_ws_with_data"]
            annotations.append((i, j, f"{delta:+.0f}pp\nn={n}"))
        grid.append(row_vals)

    import numpy as np  # local import keeps matplotlib-free callers cheap

    arr = np.array(grid, dtype=float)
    cmap = _DIVERGING_CMAP.copy()
    cmap.set_bad(WONG["neutral"])
    masked = np.ma.masked_invalid(arr)
    abs_max = max(10.0, float(np.nanmax(np.abs(arr))) if np.isfinite(arr).any() else 10.0)
    im = ax.imshow(
        masked,
        cmap=cmap,
        norm=TwoSlopeNorm(vmin=-abs_max, vcenter=0.0, vmax=abs_max),
        aspect="auto",
    )
    ax.set_xticks(range(len(tiers)))
    ax.set_xticklabels(tiers, rotation=30, ha="right")
    ax.set_yticks(range(len(stages)))
    ax.set_yticklabels(stages)
    for i, j, label in annotations:
        value = arr[i, j] if i < arr.shape[0] and j < arr.shape[1] else float("nan")
        ax.text(
            j,
            i,
            label,
            ha="center",
            va="center",
            fontsize=ANNOTATION_FONTSIZE - 1,
            color="white" if np.isfinite(value) and abs(value) > 0.6 * abs_max else "black",
        )
    ax.set_title(
        "c07: ws full-pass rate Δ by stage × tier (overlap only)\n"
        "Teal = improved, magenta = regressed; cells with no ws data on either side are 'n/a'.",
        fontsize=11,
    )
    fig.colorbar(im, ax=ax, label="ws_delta_pp (new − old)")
    fig.tight_layout()
    fig.savefig(figures_dir / "c07_where_does_category_drift.png", dpi=FIGURE_DPI)
    plt.close(fig)


def plot_skill_lift_change(figures_dir: Path, data_dir: Path) -> None:
    """c08: skill-lift (ws_pass_rate − bs_pass_rate) at old vs new and the delta.

    Reads headline_diff.json's skill_lift block. Three bars: old skill-lift,
    new skill-lift, and delta. Each bar carries its 95% bootstrap CI as a
    black error line. The figure answers the comparison's central question:
    did the skill help differently between commits, beyond what both
    conditions moved together?
    """
    path = data_dir / "headline_diff.json"
    if not path.is_file():
        return
    payload = json.loads(path.read_text())
    lift = payload.get("skill_lift")
    if not lift or lift.get("n_joint", 0) == 0:
        return

    labels = ["old skill-lift", "new skill-lift", "delta\n(new − old)"]
    values = [lift["old_pp"], lift["new_pp"], lift["delta_pp"]]
    cis = [lift["old_pp_ci95"], lift["new_pp_ci95"], lift["delta_pp_ci95"]]
    colors = [WONG["bs"], WONG["ws"], WONG["delta_pos"] if values[2] >= 0 else WONG["delta_neg"]]
    err_low = [v - c[0] for v, c in zip(values, cis, strict=True)]
    err_high = [c[1] - v for v, c in zip(values, cis, strict=True)]

    fig, ax = plt.subplots(figsize=SIZE_SINGLE)
    x = list(range(len(labels)))
    ax.bar(x, values, color=colors, edgecolor="black", linewidth=0.8)
    ax.errorbar(
        x,
        values,
        yerr=[err_low, err_high],
        fmt="none",
        ecolor="black",
        capsize=6,
        linewidth=1.2,
    )
    for xi, value, ci in zip(x, values, cis, strict=True):
        ax.text(
            xi,
            value + (1 if value >= 0 else -1) * 1.5,
            f"{value:+.1f}pp\n[{ci[0]:+.1f}, {ci[1]:+.1f}]",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=ANNOTATION_FONTSIZE,
        )
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("skill-lift (pp)")
    ax.grid(axis="y", **GRID_STYLE)
    n_joint = lift["n_joint"]
    title = (
        f"c08: Skill-lift shift (joint set n={n_joint}); "
        f"old → new Δ = {lift['delta_pp']:+.1f}pp "
        f"[CI95 {lift['delta_pp_ci95'][0]:+.1f}, {lift['delta_pp_ci95'][1]:+.1f}]"
    )
    ax.set_title(title, fontsize=11)

    notes = []
    if lift.get("underpowered"):
        notes.append(f"underpowered (n_joint={n_joint} < 25); CIs are approximate")
    if not lift.get("complete", True):
        notes.append(
            f"joint set is {n_joint} of {lift['n_overlap']} overlap evals "
            "(missing cells excluded)"
        )
    if notes:
        fig.text(
            0.5,
            0.01,
            " | ".join(notes),
            ha="center",
            fontsize=ANNOTATION_FONTSIZE,
            color=WONG["neutral"],
        )

    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(figures_dir / "c08_did_skill_lift_change.png", dpi=FIGURE_DPI)
    plt.close(fig)


def plot_regression_root_causes(figures_dir: Path, data_dir: Path) -> None:
    """c09: bucket distribution of the regression-review queue.

    Reads regression_root_cause_summary.json. Horizontal bar chart with
    one bar per bucket (rubric / routing / source_selection / tooling /
    synthesis / unknown), ordered by priority. The denominator is the
    review queue (ws regressions + rubric_friction stable_fails), not
    strict regressions — title and footer report n_ws_regressions and
    n_rubric_friction_stable_fail separately so the rubric-friction
    contribution is never miscounted as content drift.
    """
    path = data_dir / "regression_root_cause_summary.json"
    if not path.is_file():
        return
    payload = json.loads(path.read_text())
    n_review = payload.get("n_review_items", 0)
    if n_review == 0:
        return
    n_ws_reg = payload.get("n_ws_regressions", 0)
    n_rubric_sf = payload.get("n_rubric_friction_stable_fail", 0)
    buckets = payload["buckets"]
    order = ["rubric", "routing", "source_selection", "tooling", "synthesis", "unknown"]
    counts = [buckets.get(b, 0) for b in order]

    color_map = {
        "rubric": WONG["neutral"],
        "routing": WONG["delta_neg"],
        "source_selection": WONG["bs"],
        "tooling": WONG["delta_neg"],
        "synthesis": WONG["delta_neg"],
        "unknown": WONG["both_fail"],
    }
    colors = [color_map[b] for b in order]

    fig, ax = plt.subplots(figsize=SIZE_SINGLE)
    y = list(range(len(order)))
    bars = ax.barh(y, counts, color=colors, edgecolor="black", linewidth=0.6)
    ax.set_yticks(y)
    ax.set_yticklabels(order)
    ax.invert_yaxis()
    ax.set_xlabel("review-queue items classified")
    ax.grid(axis="x", **GRID_STYLE)
    for bar, count in zip(bars, counts, strict=True):
        if count == 0:
            continue
        ax.text(
            bar.get_width(),
            bar.get_y() + bar.get_height() / 2,
            f"  {count}",
            va="center",
            ha="left",
            fontsize=ANNOTATION_FONTSIZE,
        )
    ax.set_title(
        f"c09: Review-queue root causes (n={n_review}: "
        f"{n_ws_reg} ws regression(s) + {n_rubric_sf} rubric_friction stable_fail(s))\n"
        "rubric = annotator-labeled / rubric drift; routing = required-recall "
        "drop; synthesis = same evidence, worse answer",
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(figures_dir / "c09_regression_root_causes.png", dpi=FIGURE_DPI)
    plt.close(fig)


_ENGAGEMENT_INTENTS = {
    "should_trigger",
    "destructive_operation_caution",
    "setup",
    "ingestion",
    "debugging",
    "custom_pipeline_authoring",
}

_ACTIVATION_COLUMNS = [
    ("ws_skill_md_open_rate_new", "SKILL.md"),
    ("ws_required_ref_open_rate_new", "required ref"),
    ("ws_any_spyglass_ref_open_rate_new", "any ref"),
    ("ws_script_execution_rate_new", "script"),
    ("ws_source_touch_rate_new", "source"),
]


def _is_known_intent(intent: str) -> bool:
    return intent in _RESTRAINT_INTENTS or intent in _ENGAGEMENT_INTENTS


def _intent_count_color(intent: str) -> str:
    if intent in _RESTRAINT_INTENTS:
        return WONG["delta_neg"]
    if intent in _ENGAGEMENT_INTENTS:
        return WONG["ws"]
    return WONG["neutral"]


def plot_intent_balance(figures_dir: Path, data_dir: Path) -> None:
    """c10: per-intent eval count, skill-lift, and activation on the overlap.

    Reads intent_balance.csv. Three stacked panels:

    1. **Bucket size** — n_evals_overlap per intent. Reveals balance:
       a 130-eval set with zero ``should_not_trigger`` evals can't measure
       restraint, only helpfulness.
    2. **New skill-lift per intent** — ws_pass_rate − bs_pass_rate on the
       new run, with a hatched edge on restraint intents
       (``should_not_trigger``, ``near_miss_negative``) where a *positive*
       lift may actually mean the agent is over-eager rather than helpful.
    3. **New-run activation rates** — direct transcript-derived activation
       metrics, so restraint behavior is visible directly rather than only
       inferred from pass rates.

    Skipped silently when intent_balance.csv has no rows.
    """
    rows = _read_csv(data_dir / "intent_balance.csv")
    if not rows:
        return
    intents = [r["intent"] for r in rows]
    n_evals = [int(r["n_evals_overlap"]) for r in rows]
    lift_new = [float(r["skill_lift_new_pp"]) for r in rows]
    lift_delta = [float(r["skill_lift_delta_pp"]) for r in rows]

    fig, (ax_count, ax_lift, ax_activation) = plt.subplots(
        3,
        1,
        figsize=(SIZE_WIDE[0], max(SIZE_WIDE[1] * 1.45, 1.35 * len(intents) + 5.5)),
        gridspec_kw={"height_ratios": [1.0, 1.0, 1.25]},
    )
    y = list(range(len(intents)))

    # Panel 1: bucket size
    bar_colors = [_intent_count_color(intent) for intent in intents]
    bars = ax_count.barh(y, n_evals, color=bar_colors, edgecolor="black", linewidth=0.5)
    ax_count.set_yticks(y)
    ax_count.set_yticklabels(intents)
    ax_count.invert_yaxis()
    ax_count.set_xlabel("evals on overlap")
    ax_count.grid(axis="x", **GRID_STYLE)
    for bar, count in zip(bars, n_evals, strict=True):
        ax_count.text(
            bar.get_width(),
            bar.get_y() + bar.get_height() / 2,
            f"  {count}",
            va="center",
            ha="left",
            fontsize=ANNOTATION_FONTSIZE,
        )
    ax_count.set_title(
        "c10a: Eval-set balance by intent\n"
        "Blue = intended skill engagement; magenta = restraint; gray = unknown / other",
        fontsize=11,
    )

    # Panel 2: new skill-lift per intent
    lift_colors = [
        WONG["neutral"]
        if not _is_known_intent(intent)
        else WONG["delta_pos"]
        if val >= 0
        else WONG["delta_neg"]
        for intent, val in zip(intents, lift_new, strict=True)
    ]
    lift_bars = ax_lift.barh(y, lift_new, color=lift_colors, edgecolor="black", linewidth=0.5)
    for bar, intent in zip(lift_bars, intents, strict=True):
        if intent in _RESTRAINT_INTENTS:
            bar.set_hatch("///")
            bar.set_edgecolor("white")
    ax_lift.axvline(0, color="black", linewidth=0.6)
    ax_lift.set_yticks(y)
    ax_lift.set_yticklabels(intents)
    ax_lift.invert_yaxis()
    ax_lift.set_xlabel("new-run skill_lift_pp (ws − bs)")
    ax_lift.grid(axis="x", **GRID_STYLE)
    for bar, value, delta in zip(lift_bars, lift_new, lift_delta, strict=True):
        ax_lift.text(
            bar.get_width(),
            bar.get_y() + bar.get_height() / 2,
            f"  {value:+.1f}pp (Δ {delta:+.1f}pp)",
            va="center",
            ha="left" if value >= 0 else "right",
            fontsize=ANNOTATION_FONTSIZE,
        )
    ax_lift.set_title(
        "c10b: New-run skill-lift by intent\n"
        "Hatched bars = restraint intents — positive lift can mean over-eager, not helpful",
        fontsize=11,
    )

    # Panel 3: activation rates from new-run ws transcripts.
    import numpy as np  # local import keeps non-plot callers cheap

    activation = np.full((len(intents), len(_ACTIVATION_COLUMNS)), np.nan, dtype=float)
    for i, row in enumerate(rows):
        for j, (column, _label) in enumerate(_ACTIVATION_COLUMNS):
            raw = row.get(column, "")
            if raw != "":
                activation[i, j] = float(raw)
    cmap = plt.cm.get_cmap("cividis").copy()
    cmap.set_bad("#E6E6E6")
    im = ax_activation.imshow(activation, cmap=cmap, vmin=0, vmax=100, aspect="auto")
    ax_activation.set_xticks(range(len(_ACTIVATION_COLUMNS)))
    ax_activation.set_xticklabels([label for _column, label in _ACTIVATION_COLUMNS])
    ax_activation.set_yticks(y)
    ax_activation.set_yticklabels(intents)
    for i in range(len(intents)):
        for j in range(len(_ACTIVATION_COLUMNS)):
            value = activation[i, j]
            if np.isfinite(value):
                text = f"{value:.0f}%"
                color = "white" if value >= 60 else "black"
            else:
                text = "n/a"
                color = WONG["neutral"]
            ax_activation.text(
                j,
                i,
                text,
                ha="center",
                va="center",
                fontsize=ANNOTATION_FONTSIZE - 1,
                color=color,
            )
    ax_activation.set_title(
        "c10c: New-run with_skill activation rates by intent\n"
        "Direct transcript signals; for restraint intents lower is usually better",
        fontsize=11,
    )
    fig.colorbar(im, ax=ax_activation, label="activation rate (%)", shrink=0.75, pad=0.02)

    total_overlap = sum(n_evals)
    n_unknown = next(
        (int(r["n_evals_overlap"]) for r in rows if r["intent"] == "unknown"),
        0,
    )
    notes: list[str] = []
    if total_overlap and n_unknown / total_overlap >= 0.5:
        notes.append(
            f"⚠ {n_unknown}/{total_overlap} overlap evals have intent='unknown'; "
            "annotate `intent` in evals.json to use this view"
        )
    # Sum any activation rate columns that are present (rate columns are
    # blank when no transcripts) to give a one-line "did anything fire" cue.
    has_activation = any(
        r.get("ws_with_transcript_new") and r["ws_with_transcript_new"] != "0"
        for r in rows
    )
    if not has_activation:
        notes.append("activation columns blank: no new-run ws transcripts available")
    bottom_pad = 0.0
    if notes:
        bottom_pad = 0.04 + 0.025 * len(notes)
        fig.text(
            0.5,
            0.01,
            "  |  ".join(notes),
            ha="center",
            fontsize=ANNOTATION_FONTSIZE,
            color=WONG["neutral"],
        )
    fig.tight_layout(rect=(0, bottom_pad, 1, 1))
    fig.savefig(figures_dir / "c10_is_intent_balanced.png", dpi=FIGURE_DPI)
    plt.close(fig)


def _transition_value(transition: str) -> int:
    return {"improved": 1, "regressed": -1}.get(transition, 0)


def _transition_sort_key(transition: str) -> int:
    return {"improved": 0, "stable_pass": 1, "stable_fail": 2, "regressed": 3}.get(transition, 4)
