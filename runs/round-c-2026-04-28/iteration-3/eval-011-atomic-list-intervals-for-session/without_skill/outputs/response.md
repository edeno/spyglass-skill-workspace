# Listing `interval_list_name` values for `j1620210710_`

In Spyglass, intervals are stored in the `IntervalList` table (in
`spyglass.common`, typically aliased as `sgc.IntervalList`). Each row has a
primary key of `(nwb_file_name, interval_list_name)`, so to get every interval
name for a given session NWB file you restrict on `nwb_file_name` and then
project / fetch the `interval_list_name` column.

Spyglass stores `nwb_file_name` with the `.nwb` suffix, so for the session
prefix `j1620210710_` the full file name is `j1620210710_.nwb`.

## One-liner

```python
from spyglass.common import IntervalList

interval_names = (
    IntervalList & {"nwb_file_name": "j1620210710_.nwb"}
).fetch("interval_list_name")

print(interval_names)
```

- Use `.fetch("interval_list_name")` (not `.fetch1(...)`) because a session
  normally has many interval lists (run epochs, sleep epochs, position valid
  times, etc.) and `.fetch1()` would raise if more than one row is returned.
- The restriction dict `{"nwb_file_name": "j1620210710_.nwb"}` is applied
  first so the fetch only returns this session's intervals.
- `fetch("interval_list_name")` returns a NumPy array of strings; wrap in
  `list(...)` if you want a plain Python list.

## If you'd like to see them as a table instead

```python
(IntervalList & {"nwb_file_name": "j1620210710_.nwb"}).proj()
```

This shows the primary-key columns (including `interval_list_name`) for that
session in the DataJoint table preview, which is handy in a notebook before
you commit to fetching.

## Sanity checks

- If `interval_names` comes back empty, the NWB file probably hasn't been
  inserted yet — check `Nwbfile() & {"nwb_file_name": "j1620210710_.nwb"}`
  and re-run your insertion / `populate` step for `IntervalList`.
- If you only know the session prefix and want to confirm the exact file
  name, you can use a LIKE-style restriction:

  ```python
  (IntervalList & 'nwb_file_name LIKE "j1620210710_%"').fetch(
      "nwb_file_name", "interval_list_name", as_dict=True
  )
  ```
