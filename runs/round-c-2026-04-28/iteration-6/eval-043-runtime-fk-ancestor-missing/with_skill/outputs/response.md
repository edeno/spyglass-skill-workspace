# IntegrityError on `SpikeSortingRecordingSelection` insert — an upstream row is missing

**Symptom.** MySQL `IntegrityError (1452, 'Cannot add or update a child row: a foreign key constraint fails ...')` when you try to insert a `SpikeSortingRecordingSelection` row.

**Most likely root cause.** Despite the message reading "child row", the FK violation isn't in the table you're inserting into — it's in **one of its parents**. One of the PK fields in your insert dict has no matching row in an ancestor table. This is signature H in `runtime_debugging.md`, and it's almost never a Spyglass bug — it's almost always "the upstream row I assumed was there isn't."

**Why that explanation fits.** `SpikeSortingRecordingSelection` (v1, `src/spyglass/spikesorting/v1/recording.py:147-156`) is defined with five FKs:

```
recording_id: uuid
---
-> Raw
-> SortGroup
-> IntervalList
-> SpikeSortingPreprocessingParameters
-> LabTeam
```

So the fields in your key flow to these parents:

| Field in your key | Parent table that owns it |
|---|---|
| `nwb_file_name='j1620210710_.nwb'` | `Raw` (and transitively `Session`) |
| `nwb_file_name` + `sort_group_id=0` | `SortGroup` |
| `nwb_file_name` + `interval_list_name='sort_02_r1'` | `IntervalList` |
| `preproc_param_name='default'` | `SpikeSortingPreprocessingParameters` |
| `team_name='my_team'` | `LabTeam` |

If the row keyed by any of those sub-keys isn't in its parent table, MySQL rejects the child insert. Don't guess which one — ask the table.

## Fastest confirmation check — use the SpyglassMixin diagnostic

`SpyglassMixin` ships `find_insert_fail()` exactly for this case (`src/spyglass/utils/mixins/helpers.py:68-80`). It walks every parent, projects your key down to that parent's heading, and prints `MISSING` for any parent that has no matching row:

```python
from spyglass.spikesorting.v1 import SpikeSortingRecordingSelection

key = {
    'nwb_file_name': 'j1620210710_.nwb',
    'sort_group_id': 0,
    'interval_list_name': 'sort_02_r1',
    'preproc_param_name': 'default',
    'team_name': 'my_team',
}

# find_insert_fail RETURNS the diagnostic string — wrap in print() to see it.
print(SpikeSortingRecordingSelection().find_insert_fail(key))
```

You'll get something like:

```
Raw:
<row found>
SortGroup:
<rows found>
IntervalList: MISSING
SpikeSortingPreprocessingParameters:
<row found>
LabTeam:
<row found>
```

The `MISSING` line names the offending parent. Run this **before** anything else.

### Fallback if `find_insert_fail` isn't available

Same idea, manual walk over `parents(as_objects=True)`:

```python
for p in SpikeSortingRecordingSelection.parents(as_objects=True):
    sub = {k: key[k] for k in p.primary_key if k in key}
    if sub and not (p & sub):
        print('MISSING:', p.table_name, 'for', sub)
```

## Hypothesis to confirm with the diagnostic

The single most likely culprit, given your key, is **`IntervalList`** for `'sort_02_r1'`. That name doesn't match the standard `02_r1` epoch shape — the `sort_` prefix suggests a custom sort interval that should have been inserted into `IntervalList` first (typically via `IntervalList.insert1({'nwb_file_name': ..., 'interval_list_name': 'sort_02_r1', 'valid_times': ...})` or by trimming the raw interval). It's easy to forget that step because the rest of the key looks standard.

Confirm with one query:

```python
from spyglass.common import IntervalList
(IntervalList & {'nwb_file_name': 'j1620210710_.nwb',
                 'interval_list_name': 'sort_02_r1'})
# 0 rows -> this is your missing parent
# Compare with the full list for that session:
(IntervalList & {'nwb_file_name': 'j1620210710_.nwb'}).fetch('interval_list_name')
```

Second-likeliest candidate is `SortGroup` — if you haven't run `SortGroup.set_group_by_shank(nwb_file_name=...)` (or equivalent) for this session, `sort_group_id=0` won't exist for `j1620210710_.nwb` even though the integer `0` is a perfectly normal `sort_group_id` for *other* sessions. `Raw`, `SpikeSortingPreprocessingParameters('default')`, and `LabTeam('my_team')` are usually present from earlier ingest / lab setup, but the diagnostic will tell you definitively rather than relying on "usually."

Don't try to guess from the key alone — `find_insert_fail` is more reliable than reading the field names.

## Minimal fix

1. Run `print(SpikeSortingRecordingSelection().find_insert_fail(key))` and read which parent says `MISSING`.
2. Populate / insert that one ancestor row:
   - **`IntervalList: MISSING`** → insert the sort interval (`IntervalList.insert1({...})` with `valid_times` as an `(N, 2)` float64 array of `[start, end]` seconds), or pick an existing interval name from `(IntervalList & {'nwb_file_name': ...}).fetch('interval_list_name')`.
   - **`SortGroup: MISSING`** → run the lab's standard sort-group setup for this session (e.g., `SortGroup.set_group_by_shank(nwb_file_name='j1620210710_.nwb')`), then re-check.
   - **`Raw: MISSING`** → the NWB file wasn't ingested into `Raw` for this session; re-run ingestion (`02_Insert_Data.ipynb` or `insert_sessions`).
   - **`SpikeSortingPreprocessingParameters: MISSING`** → `SpikeSortingPreprocessingParameters().insert_default()` (it has a class-level `contents` list with `'default'`).
   - **`LabTeam: MISSING`** → `LabTeam` row needs to be created; coordinate with whoever manages lab membership.
3. Retry the original `SpikeSortingRecordingSelection.insert_selection(key)` (or whatever insert call you used).

## Robust fix

Before calling `insert_selection` in scripts, run the diagnostic preemptively so a missing ancestor is reported clearly rather than as a raw MySQL error:

```python
report = SpikeSortingRecordingSelection().find_insert_fail(key)
if 'MISSING' in report:
    raise RuntimeError(f"Upstream row(s) missing for key {key}:\n{report}")
SpikeSortingRecordingSelection.insert_selection(key)
```

This turns a confusing `IntegrityError (1452, ...)` into a single line that names the parent and the missing sub-key — much faster to debug on the next session.

## Watch-outs

- The literal MySQL message lists `CONSTRAINT \`...\` FOREIGN KEY (\`...\`) REFERENCES \`...\``. The `REFERENCES` table name in that string also tells you which parent failed — but it's an internal table name (e.g., ``\`#sort_group\``), not a Python class name, so `find_insert_fail` is the friendlier read.
- "I swore I populated everything upstream" usually means *for some other session*. Sub-keys like `sort_group_id=0` and `interval_list_name='sort_02_r1'` are scoped by `nwb_file_name`. Check `len(SortGroup & {'nwb_file_name': 'j1620210710_.nwb'})` and similar — a parent table being non-empty globally doesn't mean it has a row for *this* session.
- Don't reach for `skip_duplicates=True` or `force=True` to silence the IntegrityError — those don't affect FK constraints, and bypassing the constraint would only push the failure downstream where `populate()` of `SpikeSortingRecording` would later try to fetch the missing parent and crash with a less informative error.
