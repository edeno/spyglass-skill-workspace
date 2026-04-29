# Sessions with both `RippleTimesV1` and `ClusterlessDecodingV1` populated

## TL;DR

```python
from spyglass.ripple.v1 import RippleTimesV1
from spyglass.decoding.v1.clusterless import ClusterlessDecodingV1

sessions = set((RippleTimesV1 * ClusterlessDecodingV1).fetch("nwb_file_name"))
print(len(sessions), "sessions have both populated")
for nwb in sorted(sessions):
    print(nwb)
```

`*` is DataJoint's natural join, and `set(...)` collapses duplicate
`nwb_file_name` values that the join inevitably produces.

## Why `*` works here (and why no explicit `nwb_file_name=` is needed)

DataJoint's `*` joins on **every shared attribute name**, not just on
fields that one table directly inherits from the other. Even though
neither `RippleTimesV1` nor `ClusterlessDecodingV1` declares
`nwb_file_name` in its own `definition`, both inherit it through their
FK chains back to `common.Session`:

`RippleTimesV1` definition (verified at
`src/spyglass/ripple/v1/ripple.py:182`):

```
-> RippleLFPSelection           # -> LFPBandV1 -> ... -> Session  (nwb_file_name)
-> RippleParameters             # Lookup, no session key
-> PositionOutput.proj(pos_merge_id='merge_id')
---
-> AnalysisNwbfile
ripple_times_object_id : varchar(40)
```

`ClusterlessDecodingV1` -> `ClusterlessDecodingSelection`
(`src/spyglass/decoding/v1/clusterless.py:83`):

```
-> UnitWaveformFeaturesGroup    # -> Session  (nwb_file_name)
-> PositionGroup                # -> Session  (nwb_file_name)
-> DecodingParameters
-> IntervalList.proj(encoding_interval='interval_list_name')
-> IntervalList.proj(decoding_interval='interval_list_name')
estimate_decoding_params = 1 : bool
```

Both sides therefore carry `nwb_file_name` (and other Session-derived
attributes) in their headings, so `*` intersects on them. The join
contains exactly those sessions for which there is at least one ripple
row AND at least one clusterless-decoding row that agree on every
shared attribute — i.e., sessions that have both pipelines populated.

## Why you need `set(...)` (or `dj.U`)

`*` multiplies rows. A single session typically has many ripple-pipeline
rows (per-interval `LFPBandV1`/`RippleLFPSelection` × `pos_merge_id` ×
`ripple_param_name`) and many decoding rows (`PositionGroup` ×
`UnitWaveformFeaturesGroup` × `decoding_param_name` × encoding-interval ×
decoding-interval). The cross-product can balloon, and the same
`nwb_file_name` will appear repeatedly. Three equivalent
deduplication options:

```python
# (a) Python set on the fetched array — simplest
sessions = set((RippleTimesV1 * ClusterlessDecodingV1).fetch("nwb_file_name"))

# (b) dj.U — DataJoint-native, no fetch needed to count
import datajoint as dj
unique = dj.U("nwb_file_name") & (RippleTimesV1 * ClusterlessDecodingV1)
print(len(unique))               # number of distinct sessions
print(unique.fetch("nwb_file_name"))

# (c) DISTINCT via a fetch flag (returns a numpy array, not a set)
import numpy as np
sessions = np.unique(
    (RippleTimesV1 * ClusterlessDecodingV1).fetch("nwb_file_name")
)
```

Option (b) is the cleanest if you also want to chain it back into
another DataJoint query (e.g., `Session & unique`).

## Footgun watch

- Don't write `RippleTimesV1 & ClusterlessDecodingV1` — restriction
  `&` between two unrelated computed tables doesn't do what you want
  here. Use `*` for the natural join.
- Don't try `RippleTimesV1 * ClusterlessDecodingV1.fetch1(...)` — the
  join is the relation, the fetch comes after.
- The join can refuse with `DataJointError: Cannot join query
  expressions on dependent attribute '<name>'` if some shared
  attribute is *secondary* on both sides. If that fires, project one
  side down to its primary key first, e.g.
  `(RippleTimesV1.proj() * ClusterlessDecodingV1.proj()).fetch("nwb_file_name")`.
  In current Spyglass `nwb_file_name` is part of the primary key on
  both sides (inherited via Session FKs), so the plain `*` should
  succeed — but if you've added secondary attributes on a custom
  child table, `.proj()` is the escape hatch.

## Sanity-checking the answer

```python
n_ripple_sessions   = len(dj.U("nwb_file_name") & RippleTimesV1)
n_decode_sessions   = len(dj.U("nwb_file_name") & ClusterlessDecodingV1)
n_both              = len(dj.U("nwb_file_name") &
                          (RippleTimesV1 * ClusterlessDecodingV1))
print(n_ripple_sessions, n_decode_sessions, n_both)
# n_both <= min(n_ripple_sessions, n_decode_sessions)
```

If `n_both` exceeds either single-pipeline count, something is wrong
(most likely a shared-attribute name collision producing spurious
join keys) — re-inspect with
`set(RippleTimesV1.heading.names) & set(ClusterlessDecodingV1.heading.names)`
to see exactly what `*` is matching on.
