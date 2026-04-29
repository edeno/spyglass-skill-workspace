# Why you got 2735 — you're counting wrong, not your DB

Short answer: 2735 is almost certainly the **entire `DecodingOutput` master table**, not the 4 sessions you asked for. The restriction silently did nothing.

## What's going on

`DecodingOutput` is a Spyglass **merge table**. The "master" half of a merge has a very minimal heading — basically just `merge_id` (a UUID primary key) and a `source` column pointing to which part table holds the actual entry. The per-recording metadata you care about (`nwb_file_name`, `interval_list_name`, the decoding params, etc.) lives **on the part tables**, not on the master.

When you do:

```python
DecodingOutput & [{'nwb_file_name': f} for f in files]
```

DataJoint resolves the restriction against the master's heading. `nwb_file_name` is **not** in that heading, so DataJoint applies a no-op restriction (it has nothing to filter against) and `&` returns the full master table. No error, no warning — you just get the whole thing back. That's your 2735.

You can confirm this in one line:

```python
len(DecodingOutput) == len(DecodingOutput & {'nwb_file_name': 'j1620210710_.nwb'})
# True — both are 2735
```

If those two are equal, the restriction is being dropped.

## The fix: `merge_restrict`

Spyglass's `SpyglassMixin` (the base class for merge masters) provides `merge_restrict`, which walks the part tables, applies your restriction there, and joins the matching `merge_id`s back to the master. That's the right tool when you want to filter a merge by an attribute that only exists downstream.

For your counting task:

```python
files = ['j1620210710_.nwb', 'j1620210711_.nwb',
         'j1620210712_.nwb', 'j1620210713_.nwb']

# count rows of DecodingOutput restricted to those 4 nwb files
total = sum(len(DecodingOutput.merge_restrict({'nwb_file_name': f})) for f in files)
print(total)
```

Why per-file and `sum`, not one OR'd restriction? `merge_restrict` takes a single restriction (dict / AndList / query expression) and resolves it against part tables. Looping per file and summing is the simplest robust shape and avoids any ambiguity about how a list-of-dicts is interpreted across parts. If you do want it in one query, you can pass an `OR` form:

```python
from datajoint import OrList  # or build a single dj.AndList / SQL-style restriction
restr = [{'nwb_file_name': f} for f in files]
n = len(DecodingOutput.merge_restrict(restr))
```

…but the per-file `sum` is the version that's hardest to get wrong.

## Important: don't reach for `merge_get_part` here

`merge_get_part` is for **fetching the actual part-table rows** for a single merge entry (or a single source). For a counting query that spans multiple sessions — which may live in different part tables (different decoding source pipelines, e.g. `ClusterlessDecodingV1` vs `SortedSpikesDecodingV1`) — `merge_get_part` will either raise (multiple sources) or only count one source. Use `merge_restrict` for "filter the master by a downstream attribute"; reserve `merge_get_part` for "I have a `merge_id` and I want the row in its native part table."

## This footgun applies to every Spyglass merge master

The same silent no-op happens on **any** table whose only PK is `merge_id`. In Spyglass that's the five merge masters:

- `SpikeSortingOutput` (spikesorting.spikesorting_merge)
- `LFPOutput` (lfp.lfp_merge)
- `PositionOutput` (position.position_merge)
- `LinearizedPositionOutput` (linearization.linearization_merge)
- `DecodingOutput` (decoding.decoding_merge)

For all of these, `& {'nwb_file_name': ...}` (or any other upstream attribute) silently returns the full table. The same trap also bites `.fetch()`, `.fetch1()`, and `.fetch_nwb()` if you restrict the master by an attribute it doesn't have — you'll get *all* rows back rather than an empty result, which is the dangerous direction of the failure.

Rule of thumb: **if the column you're restricting by isn't in `Table.heading`, use `merge_restrict`** (for filtering) or go through the part table directly (for fetching).

## Sanity-check checklist

1. `len(DecodingOutput)` — does it equal 2735? If yes, your "filtered" count is just the whole table.
2. `DecodingOutput.heading.names` — confirm `nwb_file_name` is not there; only `merge_id` (and `source`) should be.
3. Re-run with `merge_restrict` per file and sum — that's your real count.
