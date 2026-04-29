# Where the missing 2 epochs went

Short answer: `insert_sessions` doesn't refuse or raise on a per-epoch problem
by default — it logs and continues. So missing rows almost always mean the two
epochs hit a known silent-drop path during ingestion. The two most common causes
in that order are (1) tag/name mismatches with `IntervalList` and (2) duplicate
or missing `interval_list_name` causing PK collisions.

Before fixing anything, inspect what actually landed.

## 1. First, confirm which side is short

`IntervalList` for a normal Frank-lab session has many more rows than just the
behavioral epochs (raw timestamps interval, pos intervals, etc.). If you are
already filtering, fine — but make sure the 6 you see really are the
epoch-derived rows:

```python
from spyglass.common import IntervalList, TaskEpoch
from spyglass.utils.nwb_helper_fn import get_nwb_copy_filename

nwb_copy = get_nwb_copy_filename("j1620210710.nwb")  # -> "j1620210710_.nwb"

# What's in IntervalList for this file?
print(len(IntervalList & {"nwb_file_name": nwb_copy}))
(IntervalList & {"nwb_file_name": nwb_copy}).fetch("interval_list_name")

# What's in TaskEpoch (epoch -> interval mapping)?
print(len(TaskEpoch & {"nwb_file_name": nwb_copy}))
(TaskEpoch & {"nwb_file_name": nwb_copy}).fetch(
    "epoch", "interval_list_name", as_dict=True
)
```

Note the filename gotcha: `insert_sessions` is called with the raw filename
(`j1620210710.nwb`), but every downstream query uses the copy name
(`j1620210710_.nwb`) — `_` appended before `.nwb`. If you queried with the raw
name you might be undercounting for an unrelated reason. (See ingestion ref:
"Two Filename-Convention Rules".)

## 2. The documented silent-drop path: tag-format mismatch

This is the canonical "epochs go missing" failure mode in Spyglass. Two distinct
sub-cases, both rooted in `src/spyglass/common/common_task.py`:

- **`nwbfile.epochs.tags` mismatch.** `get_epoch_interval_name`
  (`common/common_task.py:315`) tries to match each epoch's tag to an existing
  `IntervalList.interval_list_name` for the session. It checks exact match
  first, then 2-digit zero-padded substring (`'01'` in `'01_s1'`), then 3-digit
  (`'001'`). If no match — or worse, an *ambiguous* match (e.g. tag `'2'`
  substring-matches both `'02_r1'` and `'12_s2'`) — the method **logs a warning
  and returns `None`**, and the corresponding row is silently dropped from
  downstream tables. Non-numeric tags (`'sleep'`, `'run_a'`) hit this path
  immediately.
- **`nwbfile.processing['tasks'].task_table.task_epochs` non-numeric.** That
  field gets cast to `TaskEpoch.epoch`, which is an `int` PK
  (`common/common_task.py:128`). A non-castable string raises at the `insert(...)`
  step rather than dropping silently — but the surrounding `permissive`
  ingestion mode (default) catches the error, logs it to `InsertError`, and
  keeps going. End result: the row is missing without a traceback in your face.

So the first thing to inspect is the NWB itself, before re-ingesting:

```python
import pynwb
with pynwb.NWBHDF5IO("/path/to/j1620210710.nwb", "r") as io:
    nwb = io.read()
    print("epochs.tags:", [list(t) for t in nwb.epochs.tags[:]])
    print("epochs frame:")
    print(nwb.epochs.to_dataframe()[["start_time", "stop_time", "tags"]])
    if "tasks" in nwb.processing:
        print("task_table:")
        print(nwb.processing["tasks"].task_table.to_dataframe())
```

What you're looking for:

1. Any tag that isn't a numeric string (`'sleep'`, `'run_a'`, an empty list, a
   multi-element list with mixed types).
2. Any `task_epochs` value that isn't castable to `int`.
3. Any pair of epochs whose tags substring-collide against an existing interval
   name (the `'2'` vs `'12'` problem).

## 3. The other silent-drop path: PK collisions in `IntervalList`

`IntervalList` PK is `(nwb_file_name, interval_list_name)`. If two NWB epochs
end up sharing an `interval_list_name` — e.g. both have empty tags and default
to the same string, or both `nwb.epochs` rows are named the same — the second
insert would collide. Whether that surfaces as a `DuplicateError` or a silent
skip depends on the call path; in `permissive` mode (the default for
`insert_sessions`) it gets logged to `InsertError` and ingestion moves on.

Also worth checking: `start_time == stop_time` or NaN time bounds in `nwb.epochs`
can cause downstream `make()` methods to skip those rows.

## 4. Pull the actual error log

Because `insert_sessions` runs permissively by default
(`rollback_on_fail=False`, `raise_err=False`,
`src/spyglass/data_import/insert_sessions.py:73-92`), the per-table errors are
written to `common.common_usage.InsertError`, not raised. Check there for the
two missing epochs:

```python
from spyglass.common.common_usage import InsertError
(InsertError & {"nwb_file_name": "j1620210710_.nwb"}).fetch(as_dict=True)
```

Each row records the table, key, and exception. That will name the actual
failure for your two missing epochs without you having to guess between (2) and
(3).

## 5. Re-ingest cleanly after fixing the NWB

Spyglass does NOT coerce tags. The fix is on the NWB side. Once you've
identified which epochs broke and why:

- Rewrite the file so all `nwb.epochs.tags` are numeric strings (`'1'`, `'01'`,
  or `'001'` — all match an interval named `'01'`; zero-padding is conventional
  but not strictly required by current source).
- Make sure `task_epochs` is castable to `int`.
- Make sure no two epochs map to the same `interval_list_name`.

Then re-ingest **with `reinsert=True`**, not `skip_duplicates=True`
(`skip_duplicates` is a `TypeError` here — `insert_sessions` doesn't accept it):

```python
import spyglass.data_import as sgi
sgi.insert_sessions("j1620210710.nwb", reinsert=True)
```

Heads-up that `reinsert=True` is destructive — it cascades a delete through
every table FK'd to `Nwbfile` for this session before re-running ingestion. If
you've already run downstream pipelines (spike sorting, position, decoding) on
this file, that work will be deleted and need to be recomputed. (Details in the
ingestion ref under "What `reinsert=True` actually does".)

## TL;DR ranked by likelihood

1. **Two `nwb.epochs.tags` values don't match any `IntervalList` name** (or
   match ambiguously) → `get_epoch_interval_name` returned `None` → rows
   dropped silently. Most common.
2. **Two `task_epochs` values are non-numeric** → `int()` cast failed during
   `TaskEpoch.insert` → caught by the permissive-mode error logger.
3. **Two epochs collide on `(nwb_file_name, interval_list_name)`** → PK
   conflict → second insert dropped.

Run the inspection in §1 and §4 first — the `InsertError` table will tell you
which one without ambiguity.
