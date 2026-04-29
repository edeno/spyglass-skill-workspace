# Yes — your restriction silently failed (no-op)

`DecodingOutput` is a **merge table master**, and a merge master's heading
deliberately exposes only the merge bookkeeping columns — for `DecodingOutput`
that is just:

```
merge_id : uuid          # primary key
---
source   : varchar(32)   # name of the part table holding the real entry
```

It does **not** carry `nwb_file_name` (or any other upstream attribute)
in its own heading. The actual `nwb_file_name` lives several joins
upstream, on each part table's parent (`ClusterlessDecodingV1`,
`SortedSpikesDecodingV1`, …).

## Why you got 2735 instead of an error

DataJoint's behavior when you restrict by a dict is: for every key in
the dict, if the key matches an attribute in the table's heading, apply
that equality condition; **if the key does not match any attribute, it
is silently ignored.** It does *not* raise.

So:

```python
DecodingOutput & {"nwb_file_name": "j1620210710_.nwb"}
```

reduces to

```python
DecodingOutput & {}     # i.e. no restriction at all
```

and `len(...)` returns the full master row count (2735 in your case).
That is the entire `DecodingOutput` master, **not** the rows belonging
to your NWB file.

You can verify the heading yourself in the same Python session:

```python
DecodingOutput.heading.primary_key   # -> ['merge_id']
list(DecodingOutput.heading.attributes)  # -> ['merge_id', 'source']
```

If `nwb_file_name` is not in that list, any restriction keyed on it is
a no-op on the master.

## How to actually restrict by `nwb_file_name`

You need to push the restriction down to the part table (or its parent),
because that is where `nwb_file_name` is reachable through the foreign
key chain. Spyglass ships a helper on the merge mixin for exactly this:

```python
from spyglass.decoding.decoding_merge import DecodingOutput

restr = {"nwb_file_name": "j1620210710_.nwb"}

# Returns a dj.U-style view restricted across all part-table parents
view = DecodingOutput.merge_restrict(restr)
len(view)
```

`merge_restrict` walks each part table, joins to its parent (where
`nwb_file_name` actually lives), applies your restriction there, and
unions the results back up to merge-master keys. This is the
intended way to ask "which `DecodingOutput` rows belong to NWB
file X?".

If you want the underlying part-table rows themselves (with all the
upstream attributes), use `merge_get_part`:

```python
parts = DecodingOutput.merge_get_part(restr)   # list of restricted part tables
for p in parts:
    print(p, len(p))
```

You can also do it manually by restricting each part-table's parent and
then mapping back through the part:

```python
from spyglass.decoding.v1.clusterless import ClusterlessDecodingV1
from spyglass.decoding.v1.sorted_spikes import SortedSpikesDecodingV1

clusterless_keys = (DecodingOutput.ClusterlessDecodingV1
                    * ClusterlessDecodingV1
                    & restr).fetch("KEY")

sorted_keys      = (DecodingOutput.SortedSpikesDecodingV1
                    * SortedSpikesDecodingV1
                    & restr).fetch("KEY")

len(DecodingOutput & (clusterless_keys + sorted_keys))
```

…but `merge_restrict` is the one-liner.

## The general lesson (so this does not bite you again)

Whenever you restrict any DataJoint table, especially a merge master:

1. **Print the heading first** — `Tbl.heading` or
   `Tbl.heading.primary_key` — and confirm the attribute you are
   restricting on actually exists there.
2. If it does not, you are either restricting on the wrong table or
   you need a join / merge helper to reach an upstream table that
   *does* carry the attribute.
3. A row count equal to `len(Tbl)` (the whole table) after a
   restriction is a strong tell that the restriction was a silent
   no-op. Sanity-check restrictions by also computing
   `len(Tbl) - len(Tbl & restr)` — if it equals zero, nothing was
   filtered.
4. To address an existing merge entry, restrict by `merge_id`
   (the only real PK on the master), e.g.
   `DecodingOutput & {"merge_id": some_uuid}`.

So: no, the restriction did not "fail" loudly — it was silently
dropped, which is worse. Re-run with `DecodingOutput.merge_restrict({"nwb_file_name": "j1620210710_.nwb"})`
and you should get the count you expected.
