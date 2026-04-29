# Effect of changing `ripple_params.zscore_threshold` from 2 → 3 on `RippleTimesV1` and downstream

## TL;DR

Changing `zscore_threshold` from 2 to 3 means **only events whose ripple-band z-score crosses 3** get kept (a stricter threshold). You will get **fewer, on-average shorter** ripple events. But here is the important DataJoint subtlety:

- **You cannot just "re-populate" `RippleTimesV1` with a changed `ripple_params` row in place.** `RippleParameters` is upstream of `RippleTimesV1` via the primary key `ripple_param_name`. If you mutate the row, downstream rows become inconsistent with the params hash they were computed under. The correct workflow is either (a) insert a **new** `ripple_param_name` (e.g. `default_zscore_3`) and populate a new `RippleTimesV1` entry under that key, or (b) delete the old downstream rows first, update the parameter dict, then re-populate.
- Assuming you do this correctly, the rows that change are: **the matching `RippleTimesV1` row itself, plus everything in its DataJoint descendant subtree** that was computed for that `(nwb_file_name, interval_list_name, …, ripple_param_name)` key.

## What the parameter actually controls

`ripple_params` is a `blob` attribute on `RippleParameters` (`spyglass.ripple.v1.ripple.RippleParameters`). The dict is consumed by `RippleTimesV1.make()` and dispatched to one of the detectors in `ripple_detection` (Kay/Karlsson). `zscore_threshold` is the **z-scored ripple-band power threshold** that defines candidate event boundaries in `Karlsson_ripple_detector` / `Kay_ripple_detector`. Raising 2 → 3 means:

- Fewer detected events (events whose peak power never exceeds 3 SD are dropped entirely).
- Existing kept events generally have **slightly later start times and earlier end times** (the threshold-crossing boundaries move inward), so durations shrink.
- Event count, mean duration, and inter-event interval distributions all shift.

`minimum_duration` and `speed_threshold` are separate keys; only `zscore_threshold` changes here.

## Direct downstream of `RippleTimesV1`

The ripple v1 module exposes (from training knowledge of `spyglass.ripple.v1.ripple`):

- `RippleParameters` (lookup) — holds `ripple_param_name` → `ripple_params` blob.
- `RippleLFPSelection` / `RippleLFPElectrode` — selects which LFP electrodes feed the detector.
- `RippleTimesV1` (computed) — the table you are repopulating. Stores per-event start/end times (plus a stored analysis NWB file with the ripple-band traces and consensus trace).

Anything that takes ripple events as a key flows through the **`RippleTimesOutput` merge table** (the standard Spyglass v1 pattern). Concretely:

1. **`RippleTimesOutput`** (merge): a new merge entry referencing the new `RippleTimesV1` primary key has to be inserted. Old merge rows pointing at the previous `(ripple_param_name, …)` key are not automatically updated — they continue to reference the old row. If you deleted the old `RippleTimesV1` row, the `RippleTimesOutput` part-table row referencing it must be deleted first (DataJoint will refuse otherwise).

2. **Anything restricted via `RippleTimesOutput.merge_restrict(...)`** for that session/interval will return different events. In a typical Frank-lab analysis stack that includes:
   - **Decoding interval selection** — `ClusterlessDecodingV1` / `SortedSpikesDecodingV1` are commonly run *on ripple intervals* fetched from `RippleTimesOutput`. If a decoding selection (`...DecodingSelection`) keys off ripple times, the populated decoding posteriors change because the time windows being decoded change.
   - **Replay / trajectory classification** built on top of decoding posteriors (e.g. anything downstream that pulls posteriors per ripple).
   - **Any user-defined analysis tables** (e.g. ripple-triggered firing rate, ripple participation, SWR-MUA) that take a `RippleTimesOutput` merge_id as part of their primary key.

The exact set of *named* downstream tables in the public Spyglass repo that key off `RippleTimesOutput` is small — primarily it is decoding-interval selection plus user code. There is no single `Spike-Ripple-Coactivation` table in core Spyglass v1 that you would need to also re-populate; that lives in user notebooks.

## What does *not* change

- Upstream tables: `LFPV1` / `LFPBandV1` (the ripple-band-filtered LFP), `IntervalList`, `ElectrodeGroup`, position/`PositionOutput`, spike sorting outputs. None of these depend on `ripple_params`.
- Other `RippleTimesV1` rows that use a different `ripple_param_name`. The change is scoped to the param-name you altered.

## How to find the exact downstream set on your DB

Run this against your own Spyglass instance — it is the authoritative answer for *your* database, since "downstream" depends on which user tables exist:

```python
from spyglass.ripple.v1.ripple import RippleTimesV1
from spyglass.ripple.ripple_merge import RippleTimesOutput  # name may vary

# 1. Direct DataJoint descendants of RippleTimesV1
print(RippleTimesV1().descendants())

# 2. Descendants of the merge table — these are the analyses that
#    actually consume ripple events.
print(RippleTimesOutput().descendants())

# 3. For a specific param change, see what would be deleted:
key = {"ripple_param_name": "default", "nwb_file_name": "...", ...}
(RippleTimesV1 & key).delete(safemode=True)   # prints the cascade, asks before deleting
```

`(table & key).delete(safemode=True)` will print every dependent row across the cascade before doing anything — that is the most reliable way to enumerate "which downstream rows will differ" for your specific session and key.

## Recommended workflow for the threshold change

1. Insert a new params row instead of mutating the old one:
   ```python
   from spyglass.ripple.v1.ripple import RippleParameters
   params = (RippleParameters & {"ripple_param_name": "default"}).fetch1("ripple_params")
   params["zscore_threshold"] = 3.0
   RippleParameters.insert1(
       {"ripple_param_name": "default_zscore_3", "ripple_params": params},
       skip_duplicates=True,
   )
   ```
2. Re-create the `RippleLFPSelection` (or equivalent) entry pointing at `default_zscore_3` and `populate()` `RippleTimesV1` for it.
3. Insert the new `RippleTimesV1` key into `RippleTimesOutput`.
4. Re-run any decoding-interval / replay analyses against the new merge_id. Old analyses keyed on the old merge_id remain valid as a comparison baseline — this is one of the reasons the merge-table pattern exists.

## Confidence / unknowns

- **Confirmed from the Spyglass v1 design pattern**: `RippleParameters` → `RippleTimesV1` → `RippleTimesOutput` (merge) → user analyses; merge tables decouple parameter sweeps from downstream consumers.
- **Confirmed semantically**: raising `zscore_threshold` strictly subsets and shortens detected events (this is just how `ripple_detection`'s threshold-crossing detector works).
- **Not directly verified in this session** (network access was unavailable): the precise list of tables in the current `master` branch whose primary key includes a `RippleTimesOutput` merge_id. Run `RippleTimesOutput().descendants()` on your DB to enumerate them authoritatively.
- **Verify on your data** by comparing the new vs. old `RippleTimesV1` row counts and `start_time`/`end_time` arrays for the same `(nwb_file_name, interval_list_name)`; expect strictly fewer events with thresh=3.
