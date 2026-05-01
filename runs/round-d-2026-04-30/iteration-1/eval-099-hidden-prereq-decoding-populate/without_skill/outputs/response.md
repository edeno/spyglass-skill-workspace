# Why `ClusterlessDecodingV1.populate(key)` is a silent no-op

## Short answer

`populate()` is **not silent because something is wrong with your decoder** — it's silent because **there is nothing in the upstream `Selection` table that matches your `key`**, so DataJoint correctly decides there are zero jobs to run and returns immediately.

In DataJoint, a `dj.Computed` table only computes rows for keys that already exist in its `key_source` (which, for `ClusterlessDecodingV1`, is essentially `ClusterlessDecodingSelection`). If `ClusterlessDecodingSelection & key` is empty, then `(key_source & key) - target` is empty, `populate` has no work to do, and it returns without printing anything. There is no "I had nothing to populate" log line by default.

So the very first thing to check is:

```python
from spyglass.decoding.v1.clusterless import (
    ClusterlessDecodingSelection,
    ClusterlessDecodingV1,
    UnitWaveformFeaturesGroup,
)
from spyglass.decoding.v1.core import DecodingParameters, PositionGroup
from spyglass.common import IntervalList

len(ClusterlessDecodingSelection & key)   # is this 0?
```

If that count is 0, you never inserted the selection row, and `populate` has nothing to do. That is by far the most common cause of this exact symptom.

## Why this happens — the pipeline shape

`ClusterlessDecodingV1` is the *computed* leaf at the bottom of a chain. It does **not** auto-discover what to compute. You have to insert a row into `ClusterlessDecodingSelection` first, and that row's primary key has to be fully resolvable from upstream tables. Looking at the definition in `/Users/edeno/Documents/GitHub/spyglass/src/spyglass/decoding/v1/clusterless.py`:

```python
@schema
class ClusterlessDecodingSelection(SpyglassMixin, dj.Manual):
    definition = """
    -> UnitWaveformFeaturesGroup
    -> PositionGroup
    -> DecodingParameters
    -> IntervalList.proj(encoding_interval='interval_list_name')
    -> IntervalList.proj(decoding_interval='interval_list_name')
    estimate_decoding_params = 1 : bool
    """

@schema
class ClusterlessDecodingV1(SpyglassMixin, dj.Computed):
    definition = """
    -> ClusterlessDecodingSelection
    ---
    results_path: filepath@analysis
    classifier_path: filepath@analysis
    """
```

So before `populate` can do anything, every one of these prerequisites must exist for your session:

1. **`UnitWaveformFeaturesGroup`** for this `nwb_file_name` — created via `UnitWaveformFeaturesGroup().create_group(nwb_file_name, group_name, keys=[...])`, where the inner `keys` are rows of `UnitWaveformFeatures` (which itself depends on a curated `SpikeSortingOutput` merge entry whose waveforms have been extracted).
2. **`PositionGroup`** for this `nwb_file_name` — populated from `PositionOutput` merge entries (your processed Trodes/DLC position must already be in `PositionOutput`).
3. **`DecodingParameters`** with the exact `decoding_param_name` you're referencing.
4. **Two `IntervalList` rows** for this `nwb_file_name`, one whose `interval_list_name` matches `encoding_interval`, and one matching `decoding_interval`. These are renamed projections, so the names must literally exist in `IntervalList & {"nwb_file_name": ...}`.
5. **A row in `ClusterlessDecodingSelection`** with a complete primary key combining all of the above.

Any one of those missing in a way that's consistent with `key` will cause `ClusterlessDecodingSelection & key` to be empty. `populate` then does nothing and stays quiet.

## Mechanism: why no log is emitted

`SpyglassMixin.populate` (in `/Users/edeno/Documents/GitHub/spyglass/src/spyglass/utils/mixins/populate.py`) ultimately delegates to DataJoint's `super().populate(*restrictions, **kwargs)` for the standard transactional path. DataJoint computes the work list as `(key_source & restrictions) - target` and iterates. If that set is empty, the loop body never executes — no `make()`, no insert, and no warning. From the user side this looks identical to "ran successfully with nothing to do."

There are also a couple of related quiet failure modes worth knowing:

- If a `Selection` row exists *and* the result is already in the target table, `populate` is also a no-op (already done). Check `len(ClusterlessDecodingV1 & key)` — if you're truly seeing 0, you've ruled this one out.
- If `key` over-specifies fields that don't exist in `ClusterlessDecodingSelection`'s heading, DataJoint is generally permissive about ignoring extra keys, but a typo in a name that *does* exist (e.g. `encoding_interval` vs `interval_list_name`) will silently filter to zero rows.

## A debugging checklist

Run these in order. The first one that returns 0 tells you exactly where the chain is broken.

```python
# 0. Sanity: is the selection populated for this key?
print("Selection rows:", len(ClusterlessDecodingSelection & key))
print("Computed rows: ", len(ClusterlessDecodingV1 & key))

# 1. Print key fields and the heading expected
print("Your key:", key)
print("Selection PK:", ClusterlessDecodingSelection.primary_key)
# Make sure every primary key field is present in `key` and spelled correctly.

# 2. Walk each upstream table with the relevant slice of key.
nwb = {"nwb_file_name": key["nwb_file_name"]}

print(len(UnitWaveformFeaturesGroup & {
    **nwb,
    "waveform_features_group_name": key["waveform_features_group_name"],
}))

print(len(PositionGroup & {
    **nwb,
    "position_group_name": key["position_group_name"],
}))

print(len(DecodingParameters & {
    "decoding_param_name": key["decoding_param_name"],
}))

print(len(IntervalList & {
    **nwb, "interval_list_name": key["encoding_interval"],
}))
print(len(IntervalList & {
    **nwb, "interval_list_name": key["decoding_interval"],
}))
```

Any zero in step 2 is your culprit. Common patterns:

- **`IntervalList` returns 0** — you used a name that doesn't exist for that NWB file. Run `IntervalList & nwb` and look at the available `interval_list_name` values; you may need to insert a custom interval (or use `IntervalList().insert1({...})` with the times you want for encoding vs decoding).
- **`UnitWaveformFeaturesGroup` returns 0** — you skipped the step of grouping curated units. The inner part table `UnitWaveformFeaturesGroup.UnitFeatures` must have entries pointing to populated `UnitWaveformFeatures` rows. Those in turn require a curated `SpikeSortingOutput` (merge) entry whose waveform features have been computed. Walk back up that chain the same way.
- **`PositionGroup` returns 0** — same deal: you need to have inserted a `PositionGroup` row that references already-populated `PositionOutput` merge entries.
- **`DecodingParameters` returns 0** — the param name is mistyped, or you never inserted a custom param set and you're not using one of the defaults (e.g. `contfrag_clusterless_<version>`, `nonlocal_clusterless_<version>`).

## A more direct way to surface the problem

DataJoint's `populate` accepts `display_progress=True` and `reserve_jobs=True` for diagnostics, but the cleanest way to *see* the empty work list is to compute it yourself before calling populate:

```python
to_do = (ClusterlessDecodingSelection & key) - ClusterlessDecodingV1
print(f"{len(to_do)} jobs queued; {len(ClusterlessDecodingSelection & key)} selection matches")
to_do  # show the actual rows
```

If `to_do` is empty *and* `ClusterlessDecodingSelection & key` is also empty, you have your answer: nothing was queued because the selection is missing.

You can also temporarily call `make` directly to force an error if the row exists but you suspect something else is going on:

```python
sel_keys = (ClusterlessDecodingSelection & key).fetch("KEY")
ClusterlessDecodingV1().make(sel_keys[0])   # will raise if something is actually broken
```

Note that `make` will raise on a key that's not in the selection, and it bypasses transaction protection — only use it as a diagnostic, not as your normal workflow.

## Once you find the gap

Insert the missing row(s) bottom-up until `ClusterlessDecodingSelection & key` has 1 entry, then re-run:

```python
ClusterlessDecodingSelection().insert1({
    "nwb_file_name": ...,
    "waveform_features_group_name": ...,
    "position_group_name": ...,
    "decoding_param_name": ...,
    "encoding_interval": ...,   # must exist in IntervalList
    "decoding_interval": ...,   # must exist in IntervalList
    "estimate_decoding_params": 1,
})

ClusterlessDecodingV1.populate(key, display_progress=True)
```

`display_progress=True` will at least give you a tqdm bar, which immediately distinguishes "0 jobs" from "1 job that errored quietly."

## Summary

- A silent return from `populate(key)` with `len(target & key) == 0` almost always means the **selection table for that key is empty**.
- DataJoint computes its work list as `key_source & restrictions`; an empty restriction set yields zero jobs and no log.
- Walk every upstream dependency of `ClusterlessDecodingSelection` (`UnitWaveformFeaturesGroup`, `PositionGroup`, `DecodingParameters`, two `IntervalList` rows) restricted by the relevant fields of `key` — the first one that's empty is the missing prerequisite.
- The selection itself must finally be `insert1`'d before `populate` can do anything.
