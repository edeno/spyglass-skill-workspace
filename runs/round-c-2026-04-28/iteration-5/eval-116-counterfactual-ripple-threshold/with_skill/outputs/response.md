# Counterfactual: raising `ripple_params.zscore_threshold` from 2 to 3

Short answer: **the question is asking about the wrong shape of change.** Don't mutate the existing parameter row — insert a new `RippleParameters` row under a new `ripple_param_name` and populate `RippleTimesV1` against the new name. Then "which rows differ" becomes a clean side-by-side comparison instead of a provenance-corrupting mutation.

Here is the full reasoning.

## Don't `update1()` the existing row — it silently corrupts provenance

`RippleParameters` is a Lookup table whose PK is `ripple_param_name` and whose only non-PK field is `ripple_param_dict` (a blob). `RippleTimesV1` carries `ripple_param_name` in its PK, **not** the blob contents. So if you do:

```python
# WRONG
RippleParameters().update1({
    "ripple_param_name": "default",
    "ripple_param_dict": {
        "speed_name": "head_speed",
        "ripple_detection_algorithm": "Kay_ripple_detector",
        "ripple_detection_params": {
            "speed_threshold": 4.0,
            "minimum_duration": 0.015,
            "zscore_threshold": 3.0,   # was 2.0
            "smoothing_sigma": 0.004,
            "close_ripple_threshold": 0.0,
        },
    },
})
```

…then **every existing `RippleTimesV1` row** still keyed by `ripple_param_name="default"` keeps pointing at this row by name, but the row's blob no longer reflects the parameters those events were actually computed under. From the database's point of view nothing looks wrong; from a science / reproducibility point of view the analysis is now silently lying about its own history. (See `references/destructive_operations.md` § "`update1` on params with downstream rows" — same shape, with `speed_threshold` as the example.) Note also: `zscore_threshold` lives **nested under `ripple_detection_params`**, not at the top of `ripple_param_dict` — easy to get wrong (`references/ripple_pipeline.md` Key Tables, blob shape).

## Correct shape: insert a new params row, then populate

```python
from spyglass.ripple.v1 import RippleParameters, RippleTimesV1

RippleParameters().insert1({
    "ripple_param_name": "zscore3",   # NEW name
    "ripple_param_dict": {
        "speed_name": "head_speed",
        "ripple_detection_algorithm": "Kay_ripple_detector",
        "ripple_detection_params": {
            "speed_threshold": 4.0,
            "minimum_duration": 0.015,
            "zscore_threshold": 3.0,   # the only change vs. "default"
            "smoothing_sigma": 0.004,
            "close_ripple_threshold": 0.0,
        },
    },
})

# No new RippleLFPSelection row is needed. Selection rows are keyed by
# (LFPBandV1 PK + group_name) — unchanged by a parameters change.
# Build a fully scoped populate key: RippleTimesV1's PK pulls from
# RippleLFPSelection, RippleParameters, AND
# PositionOutput.proj(pos_merge_id='merge_id') (`ripple/v1/ripple.py:182-186`).
populate_key = {
    **rip_sel_key,                    # existing RippleLFPSelection PK
    "ripple_param_name": "zscore3",
    "pos_merge_id": pos_merge_id,     # existing PositionOutput merge_id
}
RippleTimesV1.populate(populate_key, display_progress=True)
```

This produces a **new** `RippleTimesV1` row alongside the existing one. Old rows under `ripple_param_name="default"` are untouched and still interpretable; the new rows under `"zscore3"` are independently queryable. The two sets coexist, which is exactly what you want for a counterfactual comparison.

## Which rows differ — answered three ways

### 1. Direct downstream rows in the database

In current Spyglass, **`RippleTimesV1` has no merge table and no Computed table directly takes it as a foreign key.** It is the terminal output of the ripple pipeline (`references/ripple_pipeline.md` overview: "No merge table — outputs directly from `RippleTimesV1`"; the FK list at `ripple/v1/ripple.py:184-186` shows `RippleTimesV1` consumes `RippleLFPSelection`, `RippleParameters`, and `PositionOutput.proj(...)`, but no Spyglass-managed Computed table is downstream of it). So the literal answer to "which downstream rows will differ" is: **none — there are no descendant tables to differ.** The new `RippleTimesV1` rows themselves are the differing artifact.

To verify on your install, run:

```bash
python skills/spyglass/scripts/code_graph.py path --down RippleTimesV1
```

(source-graph view) or `db_graph.py path --down RippleTimesV1` for the runtime topology of your DB, in case a custom downstream table exists outside the main Spyglass tree.

### 2. The new `RippleTimesV1` rows themselves — qualitative content

- **Direction:** `zscore_threshold` is the per-bin envelope cutoff (in standard deviations of the ripple-band envelope) the detector requires for an event to fire. Raising it from 2 → 3 is **stricter**, so you should expect **fewer detected ripple events** in the new rows than in the matched `"default"` rows over the same interval. Events that survive will tend to be the larger-amplitude ones; small-but-real ripples that crossed 2σ but not 3σ are dropped.
- Event durations may also shrink slightly, because event boundaries are usually anchored to a lower envelope crossing while the threshold gates which bumps qualify as events at all (the exact boundary rule lives in `ripple_detection`'s detector — `Kay_ripple_detector` / `Karlsson_ripple_detector`, `ripple/v1/ripple.py:9, 23`).
- The `(start_time, end_time)` dataframe (`(RippleTimesV1 & key).fetch1_dataframe()`) is the right fetch surface for diffing — see `references/workflows.md` § Interval Arithmetic for `interval_list_intersect` if you want to know how many old events survive into the stricter set.

### 3. Anything you compute *from* `RippleTimesV1` will of course differ

These analyses aren't auto-cascaded by Spyglass — they're whatever you do downstream by hand or in your own custom tables: ripple-triggered LFP averages, replay decoding restricted to ripple windows, ripple rate vs. behavior, etc. None of those re-run automatically; you'd re-run them against `(RippleTimesV1 & {"ripple_param_name": "zscore3", ...})` to see the counterfactual.

## Summary of what changes vs. what doesn't

| Object | Differs? |
| --- | --- |
| `RippleParameters` row `"default"` | **No** — leave unchanged |
| `RippleParameters` row `"zscore3"` | **New row** (the insert) |
| `RippleLFPSelection` rows | **No** — same selection (LFP band + electrode group + `group_name`) |
| `RippleTimesV1` rows under `"default"` | **No** — intact provenance |
| `RippleTimesV1` rows under `"zscore3"` | **New** — fewer events (typically), tighter set, same intervals/electrodes |
| Any Spyglass-managed table downstream of `RippleTimesV1` | **None exist** in the current pipeline; nothing to cascade |
| Your own analyses that consume `RippleTimesV1.fetch1_dataframe()` | Will differ when re-run against the new param name; not auto-recomputed |

The mental model worth holding: a parameter change is a **new branch in provenance**, not an edit. Insert, populate, compare. Don't `update1()`.
