# Finding the `DecodingOutput.merge_id` for a clusterless decoding run

You can't name the params for me — `decoding_param_name` is just a `varchar(80)` primary key in the `DecodingParameters` lookup table, and which entries actually exist depends on what your lab inserted. So this is a two-step task: (1) discover the param name, then (2) restrict the merge table.

## 1. Discover the params name

`DecodingParameters` (in `spyglass.decoding.v1.core`) is a single `dj.Lookup` table that holds **both** clusterless and sorted-spikes parameter sets. There is no separate "clusterless decoding parameters" table — the only thing distinguishing the two is the convention in the name string. The defaults shipped in Spyglass are e.g.

- `contfrag_clusterless_<non_local_detector_version>`
- `nonlocal_clusterless_<non_local_detector_version>`
- `contfrag_sorted_<non_local_detector_version>`
- `nonlocal_sorted_<non_local_detector_version>`

…but each lab typically inserts its own variants with custom suffixes. So pull the registered names first and pick the clusterless one:

```python
from spyglass.decoding.v1.core import DecodingParameters

# See everything that's registered
DecodingParameters().fetch("decoding_param_name")

# Or filter to clusterless variants only
clusterless_params = (
    DecodingParameters
    & "decoding_param_name LIKE '%clusterless%'"
).fetch("decoding_param_name")
print(clusterless_params)
```

Pick the one that matches what your lab refers to as "the standard clusterless params" — for many Frank-lab installs that's `contfrag_clusterless_<version>`, but **don't take my word for it**; the version suffix and any local naming convention will only show up in the fetch above. Assigning a value like `'default_clusterless'` without checking will fail silently (no row matches) and waste your afternoon.

## 2. Get the `merge_id`

`DecodingOutput` (in `spyglass.decoding.decoding_merge`) is a `_Merge` table with two part tables: `ClusterlessDecodingV1` and `SortedSpikesDecodingV1`. Each part inherits the full upstream key from `ClusterlessDecodingSelection`, which has primary keys roughly:

- `nwb_file_name`
- everything from `UnitWaveformFeaturesGroup` (e.g. `waveform_features_group_name`)
- everything from `PositionGroup` (e.g. `position_group_name`)
- `decoding_param_name`
- `encoding_interval` (a `proj` of `IntervalList.interval_list_name`)
- `decoding_interval` (another `proj` of `IntervalList.interval_list_name`)
- `estimate_decoding_params`

The session id `j1620210710_` is the Spyglass `nwb_file_name` (note the trailing underscore — that's the Spyglass convention for the ingested NWB filename, not a typo). So:

```python
from spyglass.decoding.decoding_merge import DecodingOutput

restriction = {
    "nwb_file_name":       "j1620210710_.nwb",   # confirm exact value below
    "encoding_interval":   "02_r1",
    "decoding_interval":   "02_r1",
    "decoding_param_name": <the name you picked in step 1>,
}

merge_key = (DecodingOutput.merge_get_part(restriction)).fetch1("KEY")
print(merge_key["merge_id"])
```

A couple of practical notes:

- The `nwb_file_name` in Spyglass usually includes the `.nwb` suffix; verify with
  `(Session & "nwb_file_name LIKE 'j1620210710%'").fetch("nwb_file_name")` so you copy the literal value.
- `merge_get_part` is the right helper here — it figures out which part table (`ClusterlessDecodingV1` vs `SortedSpikesDecodingV1`) the key belongs to and returns that restricted part.
- `.fetch1("KEY")` will raise if your restriction matches zero or multiple rows. If you have left out a primary-key attribute (e.g. you ran the same intervals/params against two different `position_group_name`s or `waveform_features_group_name`s), you'll need to disambiguate.

## 3. Fallback if step 2 is empty or ambiguous

If `merge_get_part` raises because nothing matches, the row probably doesn't exist (the populate hasn't been run, or your `decoding_param_name` guess was wrong). Inspect the part directly to see what *is* there for this session:

```python
DecodingOutput.ClusterlessDecodingV1 & {"nwb_file_name": "j1620210710_.nwb"}
```

That gives you every clusterless decoding run registered for this session, with the `encoding_interval`, `decoding_interval`, `decoding_param_name`, and `merge_id` columns visible — pick the row whose intervals/params actually match what you meant and read the `merge_id` off directly.

## tl;dr

1. `DecodingParameters().fetch("decoding_param_name")` to see what's actually registered (it's one table for both clusterless and sorted; the `_clusterless_` substring is the only marker).
2. Build a key with `nwb_file_name`, both intervals, and the chosen `decoding_param_name`, then `DecodingOutput.merge_get_part(key).fetch1("KEY")["merge_id"]`.
3. If that comes up empty, list `DecodingOutput.ClusterlessDecodingV1 & {"nwb_file_name": ...}` and pick the right row by eye.

I can't give you the literal UUID without DB access — these steps are what produce it.
