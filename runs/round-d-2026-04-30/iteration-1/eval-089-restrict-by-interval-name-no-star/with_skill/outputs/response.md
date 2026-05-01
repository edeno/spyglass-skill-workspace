# Sessions whose `SpikeSortingRecording` ran for `interval_list_name='02_r1'`

## Key fact

`interval_list_name` lives on `SpikeSortingRecordingSelection` (via its FK to
`IntervalList`), not on `SpikeSortingRecording` itself. `SpikeSortingRecording`
inherits the selection's primary key (`recording_id`), so to filter by
interval you join the two tables and restrict on the selection. `nwb_file_name`
likewise lives on the selection (via its FK to `Raw`).

Source: `src/spyglass/spikesorting/v1/recording.py` — `SpikeSortingRecordingSelection`
definition shows `-> Raw`, `-> SortGroup`, `-> IntervalList`, etc., and
`SpikeSortingRecording` is `-> SpikeSortingRecordingSelection`.

## Query

```python
from spyglass.spikesorting.v1 import (
    SpikeSortingRecording,
    SpikeSortingRecordingSelection,
)

# Rows of SpikeSortingRecording (i.e. populated recordings) whose paired
# selection row had interval_list_name == '02_r1'.
recordings = (
    SpikeSortingRecording
    * SpikeSortingRecordingSelection
    & {"interval_list_name": "02_r1"}
)

# Distinct sessions (nwb_file_name is the session PK) — projection collapses
# duplicates from multiple sort_group_id / preproc_param_name / team_name rows.
sessions = recordings.proj("nwb_file_name").fetch("nwb_file_name")
sessions = sorted(set(sessions))   # de-duplicate
print(sessions)
```

If you'd rather work with a query object than a numpy array of names, replace
the `fetch` line with:

```python
session_query = dj.U("nwb_file_name") & recordings   # one row per session
session_query.fetch("nwb_file_name")
```

`dj.U("nwb_file_name")` projects onto the `nwb_file_name` attribute and
de-duplicates in the database, which is cleaner than fetching then
`set()`-ing in Python when the result set is large.

## Why the join (and not just `& {...}` on `SpikeSortingRecording`)

`SpikeSortingRecording.heading` exposes only the inherited PK
(`recording_id`) plus the analysis-file payload — it does **not** carry
`interval_list_name` or `nwb_file_name`. Restricting `SpikeSortingRecording`
directly with `{"interval_list_name": "02_r1"}` would silently match every
row, because DataJoint drops restriction keys that aren't in the heading
on a plain `Manual`/`Computed` table. (This is the same footgun as
restricting a merge master by `nwb_file_name`.) Joining with
`SpikeSortingRecordingSelection` brings the selection's secondary
attributes into scope so the restriction actually filters.

## Sanity check before relying on the result

```python
# How many populated recordings match this interval?
print(len(recordings))

# Spot-check one row to confirm interval and session look right:
recordings.fetch("nwb_file_name", "interval_list_name",
                 "sort_group_id", limit=5, as_dict=True)
```

If `len(recordings) == 0`, either no session used that interval name, or
the selection rows exist but `SpikeSortingRecording.populate(...)` hasn't
been run for them yet — check
`SpikeSortingRecordingSelection & {"interval_list_name": "02_r1"}` to
distinguish those two cases.
