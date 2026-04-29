# What rows change if you bump `position_bin_size` from 2 cm to 5 cm?

Short version: **a new `DecodingParameters` row is created, and you must `populate` new rows in the decoding tables you care about. Existing rows do not mutate — `position_bin_size` is part of the primary key chain via the parameter hash, so a different value produces a parallel row, not an in-place update.** Below is the breakdown for the posterior-only scope you asked about.

## 1. The parameter row itself

`DecodingParameters` (in `spyglass.decoding.decoding_merge` / `v1.SortedSpikesDecodingParameters` / `v1.ClusterlessDecodingParameters`, depending on which decoder you use) is keyed by `decoding_param_name` (and, for the v1 tables, the param dict is hashed into the primary key). So:

- If you `insert` with the **same `decoding_param_name`** but a different `position_bin_size`, DataJoint will reject the insert (duplicate primary key) unless you delete the old row first. Deleting the old parameter row will cascade-delete every downstream row that referenced it — that is the destructive path.
- The non-destructive path is to **insert a new parameter row with a new name** (e.g. `decoding_param_name="my_params_5cm"`). The 2 cm row stays. Any prior posteriors keyed to the 2 cm row are preserved.

Recommendation: use a new name. Don't delete the 2 cm row unless you genuinely want the cascade.

## 2. Downstream tables that re-populate (posterior-only scope)

The decoding pipeline below `DecodingParameters`, restricted to what produces or stores the posterior, is:

| Table | What changes |
|---|---|
| `SortedSpikesDecodingSelection` **or** `ClusterlessDecodingSelection` | You insert a new selection row pairing your existing upstream keys (nwb file, interval, position group, sorted-spikes group / waveform features, encoding interval, etc.) with the **new** `decoding_param_name`. |
| `SortedSpikesDecodingV1` **or** `ClusterlessDecodingV1` | `populate()` on the new selection key fits a fresh decoder with the 5 cm bins and writes a new analysis NWB file containing the posterior, ML state, acausal/causal state probabilities, and the discretized environment. This is the row that holds the posterior you care about. |
| `DecodingOutput` (merge table) | A new merge entry is inserted pointing at the new `*DecodingV1` row. Existing 2 cm merge entries are untouched. |

Everything **above** the selection table is reused — your spike/waveform groups, position group, encoding/decoding intervals, environment definition, and the source NWB file all stay the same. You explicitly said you don't care about upstream, so you don't need to touch them.

## 3. What does *not* change

- `IntervalPositionInfo` / `TrodesPosV1` / `DLCPosV1` rows — `position_bin_size` is a **decoder-internal** discretization parameter for the latent state space; it does not rebin the input position timeseries. Position samples are still delivered at their native sampling rate and binned internally by `non_local_detector` when the decoder is constructed.
- `PositionGroup` / `UnitWaveformFeaturesGroup` / `SortedSpikesGroup` — all upstream of `*DecodingSelection`, so untouched.
- The encoding model fit object inside the prior 2 cm `*DecodingV1` row — it lives on disk in its own analysis NWB file, keyed by the 2 cm parameter hash. Not modified.

## 4. What to actually do

```python
from spyglass.decoding.v1.sorted_spikes import (
    SortedSpikesDecodingSelection,
    SortedSpikesDecodingV1,
)
from spyglass.decoding.decoding_merge import DecodingOutput
from spyglass.decoding.v1.core import DecodingParameters  # or the v1-specific one you use

# 1. New parameter row (don't overwrite the 2 cm one)
new_params = existing_params_dict.copy()
new_params["environments"][0]["position_bin_size"] = 5.0  # cm; check the exact key path for your decoder
DecodingParameters.insert1(
    {"decoding_param_name": "my_params_5cm", "decoding_params": new_params, ...},
    skip_duplicates=True,
)

# 2. New selection row (same upstream keys, new param name)
sel_key = {**existing_selection_key, "decoding_param_name": "my_params_5cm"}
SortedSpikesDecodingSelection.insert1(sel_key, skip_duplicates=True)

# 3. Populate -> new posterior
SortedSpikesDecodingV1.populate(sel_key, display_progress=True)

# 4. Confirm a new merge entry exists
DecodingOutput.SortedSpikesDecodingV1 & sel_key
```

Swap `SortedSpikes…` for `Clusterless…` if you're on the clusterless decoder.

## 5. Caveats worth knowing

- The exact key path for `position_bin_size` inside `decoding_params` depends on your decoder version. In `non_local_detector`-backed v1 decoders it lives under `environments[i]["position_bin_size"]` (1D track) or `environments[i]["position_bin_size"]` as a scalar / per-axis tuple for 2D. Print the existing 2 cm dict and edit only that field — don't reconstruct the dict from scratch.
- 5 cm bins shrink the state space substantially. The posterior `place_bins` axis will change length; any downstream code that hard-codes a bin count needs updating. Visualization, decode-error metrics, and replay detection thresholds (e.g. spatial-coverage criteria) often need re-tuning.
- If you also want the encoding model itself to use 5 cm tuning curves, that's already implied — `position_bin_size` is shared between the encoding model's place fields and the decoding state space in the v1 decoders. So this single change cascades to both, but only inside the new `*DecodingV1` row.
- Don't `delete()` the old `DecodingParameters` row casually — it will cascade through `*DecodingSelection`, `*DecodingV1`, and the corresponding `DecodingOutput` merge entries. If you want to keep the 2 cm posterior for comparison, leave the old row alone.

## Confidence and unknowns

- Confirmed from the public Spyglass code structure: the merge table is `DecodingOutput`, the v1 tables are `SortedSpikesDecodingV1` / `ClusterlessDecodingV1`, and `DecodingParameters` is hashed into the primary key chain.
- Less certain without checking your specific Spyglass version: the exact dict path for `position_bin_size` (top-level vs. nested under `environments`) and whether your install uses `decoding.v1.core.DecodingParameters` or a per-decoder parameter table. Print your existing 2 cm row and inspect before editing.
- Unknown to me: whether you have a custom downstream table (e.g. a replay-classifier or decode-error table) that consumes `DecodingOutput`. Those would also need a new populate, but you said posterior-only, so I'm scoping to the merge table.
