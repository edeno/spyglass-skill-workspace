# From `SpikeSorting.populate()` to `ClusterlessDecodingV1`

You finished `SpikeSorting.populate()`, so you have rows in `SpikeSortingSelection` / `SpikeSorting` (and presumably also upstream `SpikeSortingRecording`, `SortGroup`, etc.). Clusterless decoding does **not** consume sorted units directly; it consumes **waveform features** computed per spike. So the path forward is:

```
SpikeSorting  →  CurationV1 (initial)  →  SpikeSortingOutput.CurationV1
                                                     ↓
                                  UnitWaveformFeaturesSelection  →  UnitWaveformFeatures
                                                     ↓
                                          UnitWaveformFeaturesGroup
                                                     ↓
                                      ClusterlessDecodingSelection  ──┐
                                                                      │   (also needs)
                                              PositionGroup ──────────┤
                                              DecodingParameters ─────┤
                                              IntervalList rows ──────┘
                                                     ↓
                                          ClusterlessDecodingV1.populate()
                                                     ↓
                                          DecodingOutput.ClusterlessDecodingV1
```

Below is the workflow, in the order you'd run it.

---

## Step 0 — Confirm what you have

```python
from spyglass.spikesorting.v1 import SpikeSorting, SpikeSortingSelection
nwb_file = "your_session_.nwb"
print(SpikeSorting & {"nwb_file_name": nwb_file})
```

You should see one row per `(sort_group_id, sorter, sorter_param_name, ...)` combination you populated. Note the `sorting_id`(s) — you'll need them.

---

## Step 1 — Register an initial `CurationV1` row for each sorting

`SpikeSortingOutput` accepts entries from `CurationV1`, not `SpikeSorting`. An "initial curation" with no edits just anchors the `sorting_id` so it can be published.

```python
from spyglass.spikesorting.v1 import CurationV1

def _one(result):
    """insert_curation returns dict on fresh insert, list[dict] on rerun
    of an initial curation (parent_curation_id == -1 already exists).
    Normalize to a single dict."""
    if not isinstance(result, list):
        return result
    if len(result) != 1:
        raise ValueError(f"Expected one matching row, got {len(result)}")
    return result[0]

sorting_ids = (SpikeSorting & {"nwb_file_name": nwb_file}).fetch("sorting_id")

curation_keys = []
for sid in sorting_ids:
    ck = _one(CurationV1.insert_curation(
        sorting_id=sid,
        description="initial",
    ))
    curation_keys.append(ck)
```

Note: an initial curation has `parent_curation_id == -1` and stores the units exactly as the sorter produced them. If you plan to filter by quality metrics or hand-curate, you'd insert downstream `MetricCuration` / `FigURLCuration` rows and then a *child* `CurationV1` row referencing the parent. For decoding, the **waveform features themselves** are what feed the model — clusterless decoding does **not** filter by accept/reject labels — so an initial curation is sufficient.

---

## Step 2 — Publish each curation to `SpikeSortingOutput`

```python
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput

# insert() takes a list of dicts (a bare dict raises TypeError)
merge_insert_keys = (
    CurationV1 & curation_keys
).fetch("KEY", as_dict=True)

SpikeSortingOutput.insert(merge_insert_keys, part_name="CurationV1")
```

Confirm:

```python
SpikeSortingOutput.CurationV1 & {"nwb_file_name": nwb_file}
```

Each row gets a fresh `merge_id` (UUID).

---

## Step 3 — Compute waveform features per spike

This is the clusterless-specific step. `UnitWaveformFeaturesSelection` FKs to `SpikeSortingOutput` (via `spikesorting_merge_id`) and `WaveformFeaturesParams`.

```python
from spyglass.decoding.v1.waveform_features import (
    WaveformFeaturesParams,
    UnitWaveformFeaturesSelection,
    UnitWaveformFeatures,
)

# (a) Make sure stock feature-params rows exist (not auto-loaded at import)
WaveformFeaturesParams().insert_default()
# Stock names: "amplitude", "amplitude, spike_location"

# (b) Get the merge_ids you just published
merge_keys = (
    SpikeSortingOutput.CurationV1 & {"nwb_file_name": nwb_file}
).fetch("KEY", as_dict=True)

# (c) Insert one selection row per (merge_id, features_param_name).
#     Note the projection: SpikeSortingOutput's merge_id is renamed
#     to spikesorting_merge_id on UnitWaveformFeaturesSelection.
features_param_name = "amplitude, spike_location"  # or "amplitude"
selection_rows = [
    {"spikesorting_merge_id": mk["merge_id"],
     "features_param_name": features_param_name}
    for mk in merge_keys
]
UnitWaveformFeaturesSelection.insert(selection_rows, skip_duplicates=True)

# (d) Populate
UnitWaveformFeatures.populate(
    {"features_param_name": features_param_name}
)
```

This step extracts waveforms per spike and computes amplitude (and optionally spike location) features, written to a new analysis NWB.

---

## Step 4 — Group the waveform-feature rows for decoding

`ClusterlessDecodingSelection` FKs `UnitWaveformFeaturesGroup`, not `UnitWaveformFeatures` directly. The group lets you decode jointly across multiple sort groups (e.g., all tetrodes from one region).

```python
from spyglass.decoding.v1.clusterless import UnitWaveformFeaturesGroup

# Collect the UnitWaveformFeatures rows you want to include
unit_feature_keys = (
    UnitWaveformFeatures
    & {"features_param_name": features_param_name}
    # Filter to this session via the merge — UnitWaveformFeatures
    # itself doesn't carry nwb_file_name directly; restrict via the
    # merge-id list you computed above:
    & [{"spikesorting_merge_id": mk["merge_id"]} for mk in merge_keys]
).fetch("KEY", as_dict=True)

UnitWaveformFeaturesGroup().create_group(
    nwb_file_name=nwb_file,
    group_name="all_tetrodes",
    keys=unit_feature_keys,
)
```

`create_group` warns and is a no-op if the group name already exists for that session — pick a fresh name or delete the group first.

---

## Step 5 — Build a `PositionGroup`

Decoding needs animal position. Whichever upstream source you used (`TrodesPosV1`, `DLCPosV1`, etc.), it should already be in `PositionOutput`.

```python
from spyglass.position import PositionOutput
from spyglass.decoding import PositionGroup

# Find the relevant PositionOutput merge entries for this session
pos_keys = PositionOutput.merge_get_part(
    {"nwb_file_name": nwb_file},
    multi_source=True,
).fetch("KEY", as_dict=True)
# Pick the one(s) you want — typically a single TrodesPosV1 / DLCPosV1
# merge entry. Inspect first.

PositionGroup().create_group(
    nwb_file_name=nwb_file,
    group_name="default_position",
    keys=pos_keys,                   # list of PositionOutput KEY dicts
    position_variables=["position_x", "position_y"],   # default; matches Trodes/DLC
    upsample_rate=None,
)
```

Gotcha: `position_variables` must literally match column names emitted by `PositionOutput.fetch1_dataframe()`. For Trodes and DLC the columns are bare `position_x`, `position_y` — the defaults work. The legacy `CommonPos` (`IntervalPositionInfo`) source emits `head_position_x` / `head_position_y` instead; if you happen to be decoding from that source you'd need to pass those names explicitly.

---

## Step 6 — Confirm `DecodingParameters` has the row you want

Stock defaults are version-suffixed by the installed `non_local_detector` version, e.g. `contfrag_clusterless_v1.2.0`. They are **not** auto-inserted at import — call `insert_default()` once.

```python
from spyglass.decoding import DecodingParameters
from non_local_detector import __version__ as non_local_detector_version

DecodingParameters().insert_default()

decoding_param_name = f"contfrag_clusterless_{non_local_detector_version}"
assert DecodingParameters & {"decoding_param_name": decoding_param_name}
```

(If you need a custom variant — e.g. for OOM tuning — insert your own row with `decoding_params` and `decoding_kwargs` as **sibling** top-level attrs, not nested.)

---

## Step 7 — Confirm `encoding_interval` and `decoding_interval` exist

Both are names in `IntervalList` for this `nwb_file_name`. They can be the same row (typical for a single behavioral session), or different rows if you want to fit on one epoch and decode another.

```python
from spyglass.common import IntervalList
print((IntervalList & {"nwb_file_name": nwb_file}).fetch("interval_list_name"))
```

Pick (or insert) the names you'll use as `encoding_interval_name` and `decoding_interval_name`.

---

## Step 8 — Insert the `ClusterlessDecodingSelection` row and populate

```python
from spyglass.decoding.v1.clusterless import (
    ClusterlessDecodingSelection,
    ClusterlessDecodingV1,
)

selection_key = {
    "nwb_file_name": nwb_file,                 # required — inherited via the groups
    "waveform_features_group_name": "all_tetrodes",
    "position_group_name": "default_position",
    "decoding_param_name": decoding_param_name,
    "encoding_interval": encoding_interval_name,
    "decoding_interval": decoding_interval_name,
    "estimate_decoding_params": 0,             # 0 = fixed params from DecodingParameters
                                                # 1 = re-fit via Baum-Welch (different code path)
}
ClusterlessDecodingSelection.insert1(selection_key, skip_duplicates=True)
ClusterlessDecodingV1.populate(selection_key)
```

`nwb_file_name` is required even though you might think it's redundant with the group names — it is inherited transitively through both `UnitWaveformFeaturesGroup` and `PositionGroup`, and omitting it under-specifies the FK.

`estimate_decoding_params` default in the table is `1`. Set it to `0` explicitly if you want the fixed-parameter (no-EM) inference path — the two branches inside `make()` are scientifically different.

---

## Step 9 — Fetch results

`ClusterlessDecodingV1` auto-publishes to `DecodingOutput.ClusterlessDecodingV1`. Use the merge-table fetchers:

```python
from spyglass.decoding import DecodingOutput

results = DecodingOutput.fetch_results(selection_key)        # xarray.Dataset
model = DecodingOutput.fetch_model(selection_key)            # non_local_detector classifier
position_df, var_names = DecodingOutput.fetch_position_info(selection_key)
```

`selection_key` must resolve to exactly one parent-table row, or `fetch_results` raises `ValueError: Ambiguous entry` (it dispatches through `merge_restrict_class`). The full `selection_key` you used at populate is the safest restriction.

When working with `results.acausal_posterior`, remember the `state_bins` coordinate is a **stacked (state, position) index** — to get a (time, position) MAP estimate, unstack first:

```python
posterior = (
    results.acausal_posterior.unstack("state_bins")
    .drop_sel(state=["Local", "No-Spike"], errors="ignore")
    .sum("state")
)
decoded_pos = posterior.idxmax(dim="position")
```

---

## Quick checklist

Before running `ClusterlessDecodingV1.populate(...)`, you should have created/populated:

1. `CurationV1` initial row(s) for each `sorting_id`
2. `SpikeSortingOutput.CurationV1` (via `SpikeSortingOutput.insert(..., part_name="CurationV1")`)
3. `WaveformFeaturesParams` defaults inserted (one-time)
4. `UnitWaveformFeaturesSelection` row(s) and `UnitWaveformFeatures.populate()`
5. `UnitWaveformFeaturesGroup` group containing those `UnitWaveformFeatures` keys
6. `PositionOutput` already populated (Trodes / DLC) for this session
7. `PositionGroup` row pointing at the position-merge entry (or entries)
8. `DecodingParameters` defaults inserted; pick the version-suffixed `contfrag_clusterless_{ver}` name
9. `IntervalList` entries for your `encoding_interval` and `decoding_interval`
10. `ClusterlessDecodingSelection` row → `ClusterlessDecodingV1.populate(key)`

If position is **not** yet populated for this session, that's a separate pipeline run (Trodes or DLC) before Step 5; the spike-sort side and the position side are independent until they meet at the decoding selection table.
