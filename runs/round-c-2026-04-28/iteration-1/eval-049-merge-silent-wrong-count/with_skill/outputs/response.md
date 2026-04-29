Your DB isn't really that full — your count is wrong, in a particularly nasty way. The 2735 is the entire `DecodingOutput` table; DataJoint silently dropped your restriction.

## What's actually happening

`DecodingOutput` is one of the five Spyglass merge **masters** (along with `SpikeSortingOutput`, `LFPOutput`, `PositionOutput`, `LinearizedPositionOutput`). The defining trait of a merge master is that its only primary-key field is `merge_id` — the master's heading is just `(merge_id, source)`. Upstream attributes like `nwb_file_name` live on the **part tables** (`DecodingOutput.SortedSpikesDecodingV1`, `DecodingOutput.ClusterlessDecodingV1`, etc.), not on the master.

When you write:

```python
DecodingOutput & {'nwb_file_name': f}
```

DataJoint sees that `nwb_file_name` is not in the master's heading and **silently drops the restriction**. No error, no warning, no zero-row hint — the `&` returns the entire master. Same thing for the list-of-dicts shape you used (`& [{'nwb_file_name': f} for f in files]`); each dict references a field the master doesn't have, so the whole `OR`-combined restriction collapses.

You can confirm this is what's happening with one quick check — these should both print 2735:

```python
print(len(DecodingOutput))
print(len(DecodingOutput & {'nwb_file_name': 'j1620210710_.nwb'}))  # single file, also 2735
```

## The fix: `merge_restrict` per file, then sum

`merge_restrict` is the merge-aware sibling of `&` — it walks the part tables to resolve attributes that aren't on the master, so it actually applies your `nwb_file_name` filter:

```python
files = ['j1620210710_.nwb', 'j1620210711_.nwb', 'j1620210712_.nwb', 'j1620210713_.nwb']

total = sum(
    len(DecodingOutput.merge_restrict({'nwb_file_name': f}))
    for f in files
)
print(total)
```

This is the canonical "count rows across a set of sessions" shape for any merge master. (Don't use `merge_get_part` here — it raises if the matching rows span more than one part/source, which is fine for loading a single result but wrong for a counting task that may legitimately mix sources across sessions.)

## Why this matters beyond counting

The same silent no-op affects every operation that consumes the `&`-restricted relation: `.fetch()`, `.fetch1()`, `.fetch_nwb()`, `.delete()`. The failure shape is uniform — a plausibly sized result, no exception. So whenever you're restricting one of the five merge masters by an upstream attribute (`nwb_file_name`, `interval_list_name`, anything that lives on a part table), reach for `merge_restrict({...})` (or `merge_get_part({...})` when you want a single resolved part). Restricting by `merge_id` or by `source` directly is fine, since both are on the master's heading.
