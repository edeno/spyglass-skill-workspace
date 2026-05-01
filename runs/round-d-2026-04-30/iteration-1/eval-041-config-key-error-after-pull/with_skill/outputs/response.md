# `KeyError: 'pipeline_version'` from inside `SpikeSortingRecording.populate` after `git pull`

## Symptom

`SpikeSortingRecording.populate(...)` raises `KeyError: 'pipeline_version'` from
inside `make()`. It worked yesterday; the only thing that changed is `git pull`
on `spyglass/master`.

## Most likely root cause: schema drift between your code and the database

Between Spyglass releases, some table definitions change. The pulled package now
expects a column (`pipeline_version`, or — more commonly — `pipeline`, which is
how `IntervalList` records the producer of a row) that the on-disk MySQL table
doesn't have yet. DataJoint reads the column from `make()`'s `key` dict, the
column is missing, and you get `KeyError: '<column>'` from inside `make()`.

This is a documented post-pull failure mode. Note: I searched the current
`spyglass/src` tree and did not find a literal `pipeline_version` column; the
nearest live column is `pipeline = "": varchar(64)` on `IntervalList`
(`src/spyglass/common/common_interval.py:31`). Two possibilities:

1. The actual error is `KeyError: 'pipeline'` (same shape, same fix), and
   `pipeline_version` is a paraphrase from memory.
2. Your installed Spyglass is *not* the source you just pulled, and a different
   version of the code is running — see the secondary check below.

Either way, the diagnostic procedure is identical.

## Why this fits

- "Worked yesterday, broke after `git pull`" + `KeyError` from inside `make()`
  is the canonical schema-drift fingerprint. Spyglass releases periodically add
  columns to `IntervalList` / recording / curation tables; admins are supposed
  to run `Table().alter()` against the live DB to add those columns. Until that
  alter runs, the code expects a column that the table doesn't have.
- `SpikeSortingRecording.make_fetch` builds an interval and writes it via
  `IntervalList.insert1(sort_interval_valid_times.as_dict, skip_duplicates=True)`
  (`src/spyglass/spikesorting/v1/recording.py:208–217, 255–257`). If the
  `IntervalList` definition in code now declares a column the DB doesn't
  expose, the insert path inside `make()` raises a `KeyError` for that column.

## Fastest confirmation checks (do these before changing anything)

### 1. Confirm you're actually running the source you pulled

```python
import spyglass
print(spyglass.__file__)   # should be your checkout, NOT site-packages
```

```bash
cd <your spyglass checkout>
git log -1 --oneline       # confirm HEAD matches what you pulled
```

If `spyglass.__file__` points at `.../site-packages/spyglass/...` instead of
your checkout, that's editable-install drift — see the "Fix B" branch below
before chasing schema drift.

### 2. Compare the Python-side and DB-side table definitions

```python
from spyglass.common import IntervalList
IntervalList().describe()                        # Python-side definition

import datajoint as dj
dj.conn().query(
    "SHOW CREATE TABLE `common_interval`.`interval_list`"
).fetchall()                                    # DB-side definition
```

Columns present on one side but not the other are the drift. Repeat for any
other table the traceback names — likely candidates given a
`SpikeSortingRecording.populate` failure include `IntervalList`,
`SpikeSortingRecording`, and the `spikesorting_v1_recompute` schema's
`RecordingRecomputeSelection` (because `make_insert` calls
`_record_environment` -> `RecordingRecomputeSelection().insert(key, at_creation=True)`,
`recording.py:241–267`, `recompute.py:189–296`).

### 3. Capture the full traceback

Schema drift errors point at a specific column. The literal column name in the
traceback (`'pipeline'`? `'pipeline_version'`? something else?) tells the admin
exactly which `alter()` is missing.

## Minimal fix

### Fix A: schema drift (most likely)

Read the `CHANGELOG.md` section in your pulled spyglass checkout for the
version you advanced to. Recent releases (>=0.5.5) list every required
`Table().alter()` call. On a shared database the alters need ALTER privilege
that most users don't have — coordinate with the admin who runs your DB
rather than running them yourself.

The canonical alter shape (when an admin runs it) is:

```python
# Pull every FK-referenced class into scope, otherwise alter() raises
# "Foreign key reference Session could not be resolved"
from spyglass.common import *
from spyglass.spikesorting.v1 import *

IntervalList().alter()
SpikeSortingRecording().alter()
# ...plus any other tables CHANGELOG calls out for this version
```

After the alters land, restart your Python kernel and retry the populate.

### Fix B: editable-install drift (if step 1 above showed site-packages)

Your pulled source isn't actually loaded. Re-install editable, then restart
the kernel:

```bash
conda activate spyglass            # or your env
cd <your spyglass checkout>
pip install -e .
# Restart Jupyter / Python — old bytecode/cache must clear
```

If you originally `pip install spyglass-neuro`, uninstall that first
(`pip uninstall spyglass-neuro`) before re-installing the editable source.

## Robust fix

- Whenever you `git pull` Spyglass on a shared install, check the new
  version's `CHANGELOG.md` section for required `Table().alter()` calls
  *before* running any populate. Treat schema migration as a coordinated
  step, not something to discover from a traceback.
- For lab installs, have whichever admin owns the MySQL grant run the
  alters once, then announce the new version is safe to pull.
- Keep one `verify_spyglass_env.py` run handy after every pull — it
  surfaces version-pin drift among other things.

## Watch-outs

- **Don't roll back the pull to "fix" this on a shared DB.** Once another lab
  member with admin runs the `alter()`, the DB schema moves forward; an older
  Spyglass checkout will then mismatch in the *opposite* direction. Coordinate
  the version with the admin.
- **Restart the kernel after `pip install -e .`** or `Table().alter()`.
  Stale `Table` class objects in a long-running Jupyter session will keep the
  old heading cached and produce confusing follow-on errors.
- **Don't edit `src/spyglass/...` to "remove" the offending column.** Editable
  installs silently revert on the next `pip install -e .`, and you'd desync
  your DB heading from every other lab running the same release. The fix is
  the alter, not a code edit.
- A `KeyError` raised mid-populate can leave a row in the `~jobs` table marked
  `error`; once the schema is migrated and you retry, you may need to clear
  that entry. Inspect first, narrow to your key, then `delete_quick()`:

  ```python
  import datajoint as dj
  jobs = dj.Schema(SpikeSortingRecording.database).jobs
  errors = jobs & {
      "table_name": SpikeSortingRecording.table_name,
      "status": "error",
  }
  errors.fetch(as_dict=True)         # inspect first
  # narrow to your key, re-fetch, then delete_quick() only after confirming
  ```

## TL;DR

Most likely: `git pull` brought in a column the live DB doesn't have yet. Run
`IntervalList().describe()` and `SHOW CREATE TABLE common_interval.interval_list`
side-by-side; the missing column is the drift. The new version's `CHANGELOG.md`
lists the `Table().alter()` calls an admin needs to run. After the alter
lands, restart the kernel and retry. If `import spyglass; print(spyglass.__file__)`
points at site-packages, do `pip install -e .` from your checkout and restart
first — that's a different bug with a different fix.
