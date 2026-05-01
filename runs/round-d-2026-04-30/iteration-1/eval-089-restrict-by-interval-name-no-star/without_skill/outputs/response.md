# Sessions whose `SpikeSortingRecording` was populated for `interval_list_name='02_r1'`

Short version: `SpikeSortingRecording` doesn't carry `interval_list_name` directly — it inherits its primary key from `SpikeSortingRecordingSelection`, and the Selection is what foreign-keys `IntervalList`. So you restrict on the Selection (joined to the populated Recording) and project down to the session key.

Below I give you the answer for both the v1 and v0 spike-sorting pipelines, because both still ship in Spyglass and the table layout differs slightly. Pick the one that matches your pipeline.

---

## v1 (current — `spyglass.spikesorting.v1`)

```python
import datajoint as dj
from spyglass.spikesorting.v1.recording import (
    SpikeSortingRecording,
    SpikeSortingRecordingSelection,
)
from spyglass.common import Session

# Sessions whose SpikeSortingRecording was populated using interval '02_r1'
sessions = (
    Session
    & (
        SpikeSortingRecordingSelection
        & SpikeSortingRecording          # only Selections that have actually been populated
        & {"interval_list_name": "02_r1"}
    ).proj("nwb_file_name")              # carry the Session PK across the restriction
)

sessions  # display
# or:
session_keys = sessions.fetch("KEY")
nwb_files    = sessions.fetch("nwb_file_name")
```

Why this works (v1 schema, from `spyglass/spikesorting/v1/recording.py`):

- `SpikeSortingRecordingSelection` has primary key `recording_id: uuid`, with secondary FKs to `Raw`, `SortGroup`, `IntervalList`, `SpikeSortingPreprocessingParameters`, `LabTeam`. The `IntervalList` FK contributes the `nwb_file_name` and `interval_list_name` attributes to the Selection row.
- `SpikeSortingRecording` is `dj.Computed` with `-> SpikeSortingRecordingSelection` as its sole primary dependency, so `SpikeSortingRecordingSelection & SpikeSortingRecording` gives you the Selection rows that have been populated.
- Restricting that intersection by `{"interval_list_name": "02_r1"}` narrows to the interval you care about. Projecting to `nwb_file_name` lets the outer restriction match `Session`'s primary key.

If you want the recording rows themselves (not just the sessions), restrict the Recording table directly:

```python
populated_for_02r1 = (
    SpikeSortingRecording
    * SpikeSortingRecordingSelection
    & {"interval_list_name": "02_r1"}
)
```

---

## v0 (legacy — `spyglass.spikesorting.v0`)

In v0, `SpikeSortingRecordingSelection` foreign-keys `IntervalList` as a *secondary* attribute (so `interval_list_name` is in the Selection, but not part of its primary key — the PK is `nwb_file_name`, `sort_group_id`, `sort_interval_name`, ...). The pattern is the same:

```python
from spyglass.spikesorting.v0.spikesorting_recording import (
    SpikeSortingRecording,
    SpikeSortingRecordingSelection,
)
from spyglass.common import Session

sessions = (
    Session
    & (
        SpikeSortingRecordingSelection
        & SpikeSortingRecording
        & {"interval_list_name": "02_r1"}
    ).proj("nwb_file_name")
)
```

Note: in v0, `SpikeSortingRecording` itself also carries an `IntervalList` reference via `-> IntervalList.proj(sort_interval_list_name='interval_list_name')`. That attribute is renamed to `sort_interval_list_name`, so it will *not* match a `interval_list_name='02_r1'` restriction directly — restrict via the Selection, as above.

---

## Sanity checks before trusting the result

A few things worth verifying in your DB, in increasing order of paranoia:

1. **The interval name is exact.** `interval_list_name` is a `varchar(170)`; spelling/casing must match. Confirm with:
   ```python
   from spyglass.common import IntervalList
   IntervalList & {"interval_list_name": "02_r1"}
   ```
   If this is empty, no session has that interval defined and the outer query will be empty for trivial reasons.

2. **You are looking at populated rows, not just queued Selection rows.** The `& SpikeSortingRecording` clause is what enforces "has been populated" — without it, you'd also catch Selections that exist but were never run.

3. **Multiple Selections per (session, interval).** A single session can have many Selections for `02_r1` — different sort groups, different preproc params, different lab teams. The `Session` restriction collapses those down to distinct sessions, which is what you asked for. If you instead want a row per (session, sort_group, params), drop the outer `Session &` and fetch from the inner expression directly.

4. **Pipeline version.** If your lab is on v1, the v0 tables may exist but be empty (or stale). Run both queries if you're unsure which pipeline populated the recordings you care about.
