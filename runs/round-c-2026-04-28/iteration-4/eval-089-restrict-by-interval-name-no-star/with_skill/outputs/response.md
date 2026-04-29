# Restrict `Session` by `SpikeSortingRecording` populated for an interval — no `*` join

Use **DataJoint restriction-by-subquery**: `&` between two relations restricts the left side to rows whose primary-key fields appear in the right side. No `*` (join), no extra columns, no dependent-attribute pitfalls.

`SpikeSortingRecording` inherits its PK from `SpikeSortingRecordingSelection`, which carries `nwb_file_name` and `interval_list_name` (see `spyglass/spikesorting/v1/recording.py` and the canonical example in `references/spikesorting_v1_pipeline.md`). So the populated rows for a given interval name are simply:

```python
from spyglass.common import Session
from spyglass.spikesorting.v1 import SpikeSortingRecording

interval_name = "02_r1"   # whatever you're filtering by

# Sessions whose SpikeSortingRecording was populated for this interval
sessions = Session & (SpikeSortingRecording
                      & {"interval_list_name": interval_name})
```

Why this works:

- The right-hand side, `SpikeSortingRecording & {"interval_list_name": ...}`, is the set of populated recording rows for that interval. It carries `nwb_file_name` (PK) plus `sort_group_id`, `interval_list_name`, `preproc_param_name`, and `recording_id`.
- The outer `Session & (...)` restricts on the *shared* primary-key field — `nwb_file_name`. DataJoint's `&` between relations is a semi-join: it does not bring extra columns over, so you keep `Session`'s heading exactly. That's the no-star property you want.
- It de-duplicates automatically: even if a session has many recording rows (multiple sort groups, parameter sets), the session appears once.

Variants you may want:

```python
# Only nwb_file_names (lightweight) — fetch primary keys
nwb_files = (Session & (SpikeSortingRecording
                        & {"interval_list_name": interval_name})).fetch("nwb_file_name")

# As a list of session keys for downstream restrictions
session_keys = (Session & (SpikeSortingRecording
                           & {"interval_list_name": interval_name})).fetch("KEY")

# Pattern match instead of exact (e.g. all run intervals)
sessions = Session & (SpikeSortingRecording
                      & 'interval_list_name LIKE "%_r%"')

# Negation — sessions that DO NOT have a SpikeSortingRecording for that interval
missing = Session - (SpikeSortingRecording
                     & {"interval_list_name": interval_name})
```

Notes / gotchas:

- This restriction returns sessions where `SpikeSortingRecording` was actually **populated** (rows exist in the Computed table), not just selected. If you want sessions that were merely *queued* (selection inserted but not yet populated), restrict `SpikeSortingRecordingSelection` instead.
- Avoid `Session * SpikeSortingRecording` here — beyond being heavier, it would multiply session rows by the number of matching recordings and risks the dependent-attribute join refusal called out in `references/datajoint_api.md` ("Footgun — dependent-attribute refusal").
- `interval_list_name` is unique only per `nwb_file_name`. Across the database, two different sessions can both have an interval called `"02_r1"`. The query above is correct under that ambiguity (it returns *any* session where some `SpikeSortingRecording` row used that interval name); if you want a specific session's interval, also restrict by `nwb_file_name`:

  ```python
  Session & (SpikeSortingRecording & {
      "nwb_file_name": "j1620210710_.nwb",
      "interval_list_name": "02_r1",
  })
  ```

- Verify the result is what you expect with a cardinality check before any disk reads:

  ```python
  rel = Session & (SpikeSortingRecording & {"interval_list_name": interval_name})
  print(len(rel))
  rel.fetch("nwb_file_name", limit=5)
  ```

Sources:
- DataJoint restriction-by-relation pattern: `references/datajoint_api.md` ("Restriction (`&`)" and the dependent-attribute footgun under "Join (`*`)").
- `SpikeSortingRecording` PK origin (inherits `interval_list_name` from `SpikeSortingRecordingSelection`): `references/spikesorting_v1_pipeline.md` step 1, lines ~283-290.
