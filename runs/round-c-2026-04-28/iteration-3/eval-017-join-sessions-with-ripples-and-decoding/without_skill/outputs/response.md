# Sessions with both `RippleTimesV1` and `ClusterlessDecodingV1` populated

In Spyglass / DataJoint, "populated" means a row exists in the table. To get
sessions that appear in **both** computed tables, take the intersection on
`nwb_file_name` (the session key inherited from `Session`).

## Recommended approach: natural join with `*`

DataJoint's `*` operator is a natural join — it joins on every attribute the
two tables share. Both `RippleTimesV1` and `ClusterlessDecodingV1` carry
`nwb_file_name` (directly or via foreign-key chains back to `Session`), so
`*` will only keep rows that exist in both.

```python
from spyglass.lfp.analysis.v1.lfp_band import LFPBandV1  # not needed, just illustrative
from spyglass.ripple.v1.ripple import RippleTimesV1
from spyglass.decoding.v1.clusterless import ClusterlessDecodingV1

# Natural join on shared attributes (includes nwb_file_name).
joined = RippleTimesV1 * ClusterlessDecodingV1

# A given session can produce many rows (multiple ripple parameter sets,
# multiple decoding intervals/encoding intervals, etc.), so deduplicate
# on nwb_file_name.
sessions = set(joined.fetch("nwb_file_name"))

print(f"{len(sessions)} sessions have both populated:")
for s in sorted(sessions):
    print(" ", s)
```

### Why `*` and not nested restrictions?

You might be tempted to write something like
`RippleTimesV1 & ClusterlessDecodingV1.fetch("KEY")`, but that only works
cleanly if the two tables share the same primary key — they don't here
(ripple has its own param/interval keys, decoding has its own selection key).
The natural join `*` matches on whatever attributes they *do* share
(notably `nwb_file_name`) and produces the intersection at the session
level once you deduplicate.

### Why deduplicate?

The join multiplies rows: one session can have

- multiple `RippleTimesV1` entries (different ripple parameter sets,
  different LFP electrode groups, different interval lists), and
- multiple `ClusterlessDecodingV1` entries (different encoding intervals,
  decoding intervals, parameter sets, position groups).

So the cartesian product within a session can produce dozens of rows.
Wrapping in `set(...)` (or using `dj.U("nwb_file_name") & joined` as the
DataJoint-native equivalent) collapses to one entry per session.

### Alternative: distinct projection

If you'd rather keep this in DataJoint expressions:

```python
import datajoint as dj

q = dj.U("nwb_file_name") & (RippleTimesV1 * ClusterlessDecodingV1)
print(q)                       # nicely formatted table
session_names = q.fetch("nwb_file_name")
```

`dj.U("nwb_file_name")` is the universal set on that attribute and acts as
a "select distinct nwb_file_name" when intersected with the join.

### If you also want the count per session

```python
import pandas as pd

df = pd.DataFrame(
    (RippleTimesV1 * ClusterlessDecodingV1).fetch(
        "nwb_file_name", "interval_list_name", as_dict=True
    )
)
print(df.groupby("nwb_file_name").size().sort_values(ascending=False))
```

## Sanity checks before trusting the list

1. Spot-check one session: restrict each table individually
   (`RippleTimesV1 & {"nwb_file_name": "<name>"}` and the same for
   `ClusterlessDecodingV1`) and confirm both return non-empty.
2. Confirm the join didn't drop rows because of a *different* shared
   attribute — `print((RippleTimesV1 * ClusterlessDecodingV1).heading)` shows
   exactly which attributes the natural join is matching on. If something
   like `position_group_name` appears unintentionally, you may want to
   project it away first (`.proj()`) so the join is only on session-level
   keys.
3. Compare counts:
   `len(set(RippleTimesV1.fetch('nwb_file_name')))` and
   `len(set(ClusterlessDecodingV1.fetch('nwb_file_name')))` — the
   intersection should be no larger than either.

## TL;DR

```python
sessions = set((RippleTimesV1 * ClusterlessDecodingV1).fetch("nwb_file_name"))
```

That single line gives you the unique set of `nwb_file_name`s for which
both `RippleTimesV1` and `ClusterlessDecodingV1` are populated.
