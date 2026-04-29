# IntegrityError on `SpikeSortingRecordingSelection.insert1` — diagnosing the missing parent

That MySQL error code `1452` is a foreign-key constraint failure. It means MariaDB/MySQL refused the insert because at least one of the referenced parent rows doesn't exist. In DataJoint terms: one of the upstream tables that `SpikeSortingRecordingSelection` declares as a parent is missing the row identified by the corresponding sub-key.

Importantly, the FK violation is **not** in `SpikeSortingRecordingSelection` itself — it's in *one of its parents*. The error message from MySQL is usually noisy and doesn't tell you cleanly which parent is the offender, so guessing ("must be a typo in the key") is a bad strategy. You want a deterministic diagnostic.

## First: use the SpyglassMixin diagnostic

Spyglass tables inherit from `SpyglassMixin`, which provides a `find_insert_fail` helper exactly for this situation. Run it with the same key you tried to insert:

```python
from spyglass.spikesorting.v1 import SpikeSortingRecordingSelection

key = {
    'nwb_file_name': 'j1620210710_.nwb',
    'sort_group_id': 0,
    'interval_list_name': 'sort_02_r1',
    'preproc_param_name': 'default',
    'team_name': 'my_team',
}

SpikeSortingRecordingSelection().find_insert_fail(key)
```

This walks every parent of the Selection table, restricts each by the relevant subset of `key`, and prints something like:

```
Raw: OK
SortGroup: OK
IntervalList: MISSING
SpikeSortingPreprocessingParameters: OK
LabTeam: OK
```

So whichever parent prints `MISSING` is the row you still need to insert.

## Fallback if `find_insert_fail` isn't available

If you're on an older Spyglass or the helper isn't on this table, you can do the same walk by hand using DataJoint's parent introspection:

```python
sel = SpikeSortingRecordingSelection()

for parent in sel.parents(as_objects=True):
    parent_pk = parent.primary_key
    sub_key = {k: key[k] for k in parent_pk if k in key}
    n = len(parent & sub_key)
    print(f"{parent.table_name}: {'OK' if n else 'MISSING'} (sub_key={sub_key})")
```

`parents(as_objects=True)` returns the actual parent table objects, and `primary_key` tells you which fields of your `key` are relevant for that parent. The one that comes back with zero rows is your culprit.

## The concrete FK parents for this Selection

Looking at `spyglass/spikesorting/v1/recording.py`, `SpikeSortingRecordingSelection` has foreign-key references (directly or via secondary attributes) to:

- `Raw` — the raw electrophysiology data for this `nwb_file_name` (i.e. the session has actually been ingested).
- `SortGroup` — keyed by `(nwb_file_name, sort_group_id)`; this is the per-session grouping of electrodes into tetrodes/probes that you populate per session.
- `IntervalList` — keyed by `(nwb_file_name, interval_list_name)`; the time interval to sort over.
- `SpikeSortingPreprocessingParameters` — keyed by `preproc_param_name`.
- `LabTeam` — keyed by `team_name`.

So the question is which of those five sub-keys doesn't currently resolve to a row.

## Most likely candidate (a hypothesis to confirm with the diagnostic)

`'sort_02_r1'` looks like a custom sort interval ("sort, epoch 02, run 1") rather than one of the canonical intervals NWB ingestion creates. It is *very* common to assume that because you derived a sub-interval (e.g. with `interval_list_intersect`) it's automatically in the database — it isn't. You have to insert it explicitly:

```python
from spyglass.common import IntervalList

IntervalList.insert1({
    'nwb_file_name': 'j1620210710_.nwb',
    'interval_list_name': 'sort_02_r1',
    'valid_times': sort_02_r1_valid_times,  # (n_intervals, 2) array of [start, stop]
    'pipeline': 'spikesorting',  # or whatever fits
}, skip_duplicates=True)
```

A second plausible candidate is `SortGroup` not having been populated for this `nwb_file_name` (it's a per-session table and is usually filled by `SortGroup.set_group_by_shank(nwb_file_name)` or similar). Less likely but possible: `preproc_param_name='default'` not actually inserted into `SpikeSortingPreprocessingParameters`, or `team_name='my_team'` missing from `LabTeam`.

But don't take my word for which one is missing — let `find_insert_fail` tell you. Then `.insert1` the missing parent (with the right values for that table's secondary attributes) and retry the Selection insert. This is the expected workflow, not a Spyglass bug; the FK constraint is doing its job.

## Summary

1. Run `SpikeSortingRecordingSelection().find_insert_fail(key)` first — it tells you exactly which parent is missing.
2. The five FK parents to know about are `Raw`, `SortGroup`, `IntervalList`, `SpikeSortingPreprocessingParameters`, `LabTeam`.
3. Top hypothesis: `IntervalList` is missing the row `(j1620210710_.nwb, sort_02_r1)` because `sort_02_r1` is a custom interval that wasn't `insert1`'d. Confirm with the diagnostic, then insert it.
4. Re-run your `SpikeSortingRecordingSelection.insert1(key)` once the missing ancestor is in place.
