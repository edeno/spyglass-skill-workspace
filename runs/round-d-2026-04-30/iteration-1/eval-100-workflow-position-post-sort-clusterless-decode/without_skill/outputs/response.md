# From `SpikeSorting.populate()` to `ClusterlessDecodingV1` — full v1 workflow

Nice — having `SpikeSorting.populate()` finished is roughly the halfway point. From there, the v1 clusterless pipeline has three parallel "lanes" that all need to be ready before you can populate `ClusterlessDecodingV1`:

1. **Spikes lane** — promote your sortings into `SpikeSortingOutput` (the merge), compute waveform features, and bundle them into a `UnitWaveformFeaturesGroup`.
2. **Position lane** — get position into `PositionOutput` (the merge) and bundle one or more entries into a `PositionGroup`.
3. **Params lane** — make sure `DecodingParameters` has the entry you want, and define the encoding/decoding intervals in `IntervalList`.

Then you tie them together in `ClusterlessDecodingSelection` and call `.populate()` on `ClusterlessDecodingV1`.

The relevant tables live in:

- `spyglass.spikesorting.v1` (`SpikeSorting`, `CurationV1`, …)
- `spyglass.spikesorting.spikesorting_merge.SpikeSortingOutput` (the merge)
- `spyglass.decoding.v1.waveform_features` (`WaveformFeaturesParams`, `UnitWaveformFeaturesSelection`, `UnitWaveformFeatures`)
- `spyglass.decoding.v1.clusterless` (`UnitWaveformFeaturesGroup`, `ClusterlessDecodingSelection`, `ClusterlessDecodingV1`)
- `spyglass.decoding.v1.core` (`DecodingParameters`, `PositionGroup`)
- `spyglass.position.position_merge.PositionOutput`
- `spyglass.common.common_interval.IntervalList`

Below is the end-to-end recipe.

---

## 0. Imports and a session key

```python
import datajoint as dj
import numpy as np

from spyglass.spikesorting.v1 import (
    SpikeSorting,
    SpikeSortingSelection,
    CurationV1,
)
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput

from spyglass.decoding.v1.waveform_features import (
    WaveformFeaturesParams,
    UnitWaveformFeaturesSelection,
    UnitWaveformFeatures,
)
from spyglass.decoding.v1.clusterless import (
    UnitWaveformFeaturesGroup,
    ClusterlessDecodingSelection,
    ClusterlessDecodingV1,
)
from spyglass.decoding.v1.core import DecodingParameters, PositionGroup

from spyglass.position.position_merge import PositionOutput
from spyglass.common import IntervalList

nwb_file_name = "minirec20230622_.nwb"   # whatever your session is
```

You probably already know which `sorting_id`s you ran. If not:

```python
sortings = (SpikeSorting & {"nwb_file_name": nwb_file_name}).fetch("KEY")
```

---

## 1. Spikes lane

### 1a. Promote each sorting through `CurationV1` into the merge

`UnitWaveformFeaturesSelection` is keyed off `SpikeSortingOutput`'s `merge_id`, not off `SpikeSorting` directly. So each `sorting_id` needs:

1. an "initial" curation row in `CurationV1` (this is the no-op curation #0 you create right after sorting), and
2. an entry in the merge table.

```python
for s in sortings:
    # 1) seed a curation row (curation_id=0, no merges, no labels)
    CurationV1.insert_curation(s)

    # 2) push that curation into the merge table
    cur_key = (CurationV1 & s).fetch1("KEY")
    SpikeSortingOutput.insert([cur_key], part_name="CurationV1")
```

If you have already curated (re-merged / relabeled units), insert the *curated* `CurationV1` key into the merge instead — `SpikeSortingOutput` accepts any `CurationV1` row, not just curation 0. For a first decoding run, curation 0 is fine; clusterless decoding uses *all* spikes regardless of unit labels, so curation labels mostly don't matter here.

### 1b. Configure waveform-features parameters

Defaults are pre-loaded if you call `WaveformFeaturesParams.insert_default()`; the standard one is `"amplitude"` (peak amplitude per spike, neg-going).

```python
WaveformFeaturesParams.insert_default()
features_param_name = "amplitude"     # or "amplitude, spike_location"
```

If you want non-default params (e.g. different `ms_before`/`ms_after`, more spikes per unit, multi-feature combos), insert your own row into `WaveformFeaturesParams` with a unique `features_param_name` and the nested `params` dict shown in the source — `waveform_features_params` for which features and `waveform_extraction_params` for the spikeinterface waveform extractor.

### 1c. Select + populate `UnitWaveformFeatures`

```python
merge_keys = (
    SpikeSortingOutput.CurationV1
    & [(CurationV1 & s).fetch1("KEY") for s in sortings]
).fetch("KEY")   # has "merge_id"

# UnitWaveformFeaturesSelection wants spikesorting_merge_id, not merge_id
selection_keys = [
    {"spikesorting_merge_id": k["merge_id"],
     "features_param_name": features_param_name}
    for k in merge_keys
]
UnitWaveformFeaturesSelection.insert(selection_keys, skip_duplicates=True)

UnitWaveformFeatures.populate(selection_keys)
```

This is the slow step — it pulls each waveform out via spikeinterface, computes features, and writes an analysis NWB file per (sorting, params) combo. Run it under a `tmux` session if you have many tetrodes.

### 1d. Bundle into a `UnitWaveformFeaturesGroup`

`ClusterlessDecodingSelection` joins on a *group* of feature entries, not individual ones. This is how you get cross-tetrode pooling.

```python
feat_keys = (UnitWaveformFeatures & selection_keys).fetch("KEY")

UnitWaveformFeaturesGroup().create_group(
    nwb_file_name=nwb_file_name,
    group_name="all_tetrodes",
    keys=feat_keys,
)
```

After this you should see one `UnitWaveformFeaturesGroup` row and N `UnitWaveformFeaturesGroup.UnitFeatures` part rows.

---

## 2. Position lane

### 2a. Get position into `PositionOutput`

`PositionOutput` is a merge over `TrodesPosV1`, `DLCPosV1`, `CommonPos`, and `ImportedPose`. Whichever pipeline you ran, populate it as usual and then insert the resulting key into `PositionOutput`. For Trodes:

```python
from spyglass.position.v1 import (
    TrodesPosSelection, TrodesPosV1, TrodesPosParams,
)

# … (insert TrodesPosSelection, populate TrodesPosV1) …

trodes_keys = (TrodesPosV1 & {"nwb_file_name": nwb_file_name}).fetch("KEY")
PositionOutput.insert(trodes_keys, part_name="TrodesPosV1")
```

Same pattern with `part_name="DLCPosV1"` if you used DLC.

### 2b. Bundle into a `PositionGroup`

```python
pos_merge_keys = (
    PositionOutput.TrodesPosV1 & trodes_keys
).fetch("KEY")     # contains merge_id

PositionGroup().create_group(
    nwb_file_name=nwb_file_name,
    group_name="default",
    keys=pos_merge_keys,
    position_variables=["position_x", "position_y"],   # 2D open field
    # upsample_rate=500.0,   # optional; leave NaN to skip upsampling
)
```

For 1D linearized decoding the `position_variables` list is typically `["linear_position"]` and you'd use a linearized position upstream.

---

## 3. Params lane

### 3a. `DecodingParameters`

```python
DecodingParameters.insert_default()   # idempotent; populates the 4 stock entries

# pick one — these names embed the non_local_detector version:
print(DecodingParameters.fetch("decoding_param_name"))
decoding_param_name = "contfrag_clusterless_<version>"   # the contfrag clusterless one
```

The four stock entries are `contfrag_clusterless_*`, `nonlocal_clusterless_*`, `contfrag_sorted_*`, `nonlocal_sorted_*`. For clusterless, use one of the `*_clusterless_*` entries.

If you need custom decoding params (different state transitions, environments, sampling frequency, observation model …), instantiate the appropriate `non_local_detector` classifier with your kwargs and insert it as a new `DecodingParameters` row — the table's overridden `insert` handles class-to-dict conversion for you.

### 3b. Encoding and decoding intervals

`ClusterlessDecodingSelection` references `IntervalList` *twice* — once projected as `encoding_interval` and once as `decoding_interval`. They can be the same interval (decode the data you encoded on) or different (e.g. encode on run epochs, decode on sleep / SWRs).

You usually already have the run-epoch intervals from session ingestion (`<epoch>_pos valid times`, `raw data valid times`, etc.). If you want a custom one (e.g. ripple times, a specific time window), insert it:

```python
IntervalList.insert1(
    {
        "nwb_file_name": nwb_file_name,
        "interval_list_name": "encode_run_02",
        "valid_times": np.array([[t_start, t_end]]),   # shape (n_intervals, 2)
        "pipeline": "decoding",
    },
    skip_duplicates=True,
)
```

Pick names that exist in `IntervalList & {"nwb_file_name": nwb_file_name}`.

---

## 4. Tie it together: `ClusterlessDecodingSelection`

The selection-table primary key is the cross of:
- `UnitWaveformFeaturesGroup` (so: `nwb_file_name`, `waveform_features_group_name`)
- `PositionGroup` (so: `position_group_name`)
- `DecodingParameters` (`decoding_param_name`)
- `IntervalList` projected twice (`encoding_interval`, `decoding_interval`)
- plus a flag `estimate_decoding_params` (default `True`)

```python
selection_key = {
    "nwb_file_name": nwb_file_name,
    "waveform_features_group_name": "all_tetrodes",
    "position_group_name": "default",
    "decoding_param_name": decoding_param_name,
    "encoding_interval": "encode_run_02",
    "decoding_interval": "encode_run_02",      # or a different interval
    "estimate_decoding_params": False,         # set True only for first-pass tuning; see note
}

ClusterlessDecodingSelection.insert1(selection_key, skip_duplicates=True)
```

A note on `estimate_decoding_params`: when this is `True`, the `make()` runs `classifier.estimate_parameters` on the encoding interval to learn discrete-state transitions (and similar) before the actual decode. That's useful early on, but it changes what's saved and is slower; many users set it to `False` once they've settled on parameters.

Also note: encoding and decoding intervals **must not overlap** if you set `estimate_decoding_params=True` — the detector will refuse to fit and predict on the same data. For a sanity-check decode-on-encoding-data run, leave it `False`.

---

## 5. Populate `ClusterlessDecodingV1`

```python
ClusterlessDecodingV1.populate(selection_key, display_progress=True)
```

The `make()` will:
1. Fetch position from `PositionGroup.fetch_position_info`.
2. Fetch spike times + per-spike waveform features from each `UnitWaveformFeatures` row in the group.
3. Restrict to `encoding_interval` for fit and `decoding_interval` for predict.
4. Run `ClusterlessDetector.fit(...).predict(...)` from `non_local_detector`.
5. Save `results` (a NetCDF/xarray file) and the fitted `classifier` (`.pkl`) into the analysis filepath store, and insert the row.

To inspect afterward:

```python
row = (ClusterlessDecodingV1 & selection_key).fetch1()
results = ClusterlessDecodingV1().fetch_results()       # xarray.Dataset
classifier = (ClusterlessDecodingV1 & selection_key).fetch_model()
```

There are also classmethod plot helpers on `ClusterlessDecodingV1` (`get_orientation_col`, posterior plotting, etc. — see `clusterless.py`).

---

## TL;DR insert/populate order

1. `CurationV1.insert_curation(...)` for each sorting key
2. `SpikeSortingOutput.insert([...], part_name="CurationV1")`
3. `WaveformFeaturesParams.insert_default()`
4. `UnitWaveformFeaturesSelection.insert(...)` then `UnitWaveformFeatures.populate(...)`
5. `UnitWaveformFeaturesGroup().create_group(...)`
6. `PositionOutput.insert([...], part_name="TrodesPosV1" | "DLCPosV1")`
7. `PositionGroup().create_group(...)`
8. `DecodingParameters.insert_default()` (or your own)
9. `IntervalList.insert1(...)` for encoding/decoding intervals if not already there
10. `ClusterlessDecodingSelection.insert1(...)`
11. `ClusterlessDecodingV1.populate(...)`

Common gotchas:

- `UnitWaveformFeaturesSelection` uses `spikesorting_merge_id`, not `merge_id`. Easy to miss when copying merge keys.
- The selection table requires the spikes side to be promoted into `SpikeSortingOutput`; it does **not** read from `SpikeSorting`/`CurationV1` directly.
- Both `UnitWaveformFeaturesGroup` and `PositionGroup` are *manual* tables; nothing populates them automatically — you have to call `create_group(...)`.
- `encoding_interval` and `decoding_interval` must both exist in `IntervalList` for that `nwb_file_name`.
- Clusterless decoding ignores curation labels (`accept`/`mua`/`noise`) — it uses all spikes from the units in the merge entry. If you want to exclude noise tetrodes, do it by *not* including those sortings in the `UnitWaveformFeaturesGroup`.
- `UnitWaveformFeatures.populate` is the heavy step; budget for it on real data and run under tmux.
