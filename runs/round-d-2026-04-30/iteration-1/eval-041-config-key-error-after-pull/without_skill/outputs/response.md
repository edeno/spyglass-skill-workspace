# `KeyError: 'pipeline_version'` from `SpikeSortingRecording.populate` after `git pull`

Short version: **the error is not coming from current Spyglass code.** There is no field, key, attribute, or string named `pipeline_version` anywhere in `spyglass/spikesorting/` (v0 or v1) on current `master`. Whatever is raising that `KeyError` is either (a) **your own user code / config / params dict** that's being passed into the populate call, or (b) **stale `__pycache__` / a stale install / a duplicated checkout** that's still serving you yesterday's `make()`. The fix is almost always one of three things below.

## How I verified

Against your local checkout at `/Users/edeno/Documents/GitHub/spyglass/src/spyglass`:

- `grep -rn "pipeline_version" src/spyglass/` -> **zero matches**.
- `SpikeSortingRecording` (v1) primary key in `spikesorting/v1/recording.py:186-195` is just `recording_id: uuid` plus the part-table refs (`AnalysisNwbfile`, `object_id`, `electrodes_id`, `hash`). No `pipeline_version`.
- `SpikeSortingRecordingSelection` (v1, line 147-157) keys on `recording_id` and FKs to `Raw`, `SortGroup`, `IntervalList`, `SpikeSortingPreprocessingParameters`, `LabTeam`. No `pipeline_version`.
- `SpikeSortingPreprocessingParameters.preproc_params` (line 99-138) is a `blob` dict whose default keys are `frequency_min`, `frequency_max`, `margin_ms`, `seed`, `min_segment_length`. No `pipeline_version`.
- v0 (`spikesorting/v0/spikesorting_recording.py`) likewise has no `pipeline_version` anywhere.

The closest related strings in the source are literal pipeline *names* like `"spikesorting_recording_v1"` written into `IntervalList.pipeline` (recording.py:215, artifact.py:198, v0 line 386). Those are values, not keys, and they wouldn't raise `KeyError`.

So the canonical Spyglass `make()` cannot itself raise `KeyError: 'pipeline_version'`. Something else is.

## What's almost certainly happening (in order of likelihood)

### 1. Stale bytecode / stale install — most likely cause of "worked yesterday, broken today after `git pull`"

If Spyglass is installed in non-editable mode, or if there are leftover `__pycache__` dirs from the old version, Python may still be importing the old module while you think you're running the new one — but the *table definition* on the database has been migrated by `git pull` running you against new schema code somewhere in the call chain. The mismatch surfaces as a `KeyError` on a field name that exists in one version and not the other.

Do this first, in order:

```bash
# 1. Confirm where Spyglass is actually being imported from
python -c "import spyglass, os; print(spyglass.__file__)"
# Should print a path inside .../spyglass/src/spyglass/__init__.py
# If it prints a site-packages path, you have a stale non-editable install.

# 2. If it's site-packages, reinstall editable from your checkout
pip uninstall spyglass-neuro    # confirm package name from your env
pip install -e /Users/edeno/Documents/GitHub/spyglass

# 3. Wipe stale bytecode
find /Users/edeno/Documents/GitHub/spyglass -name __pycache__ -type d -prune -exec rm -rf {} +

# 4. Restart the Python process (kernel restart in Jupyter). This is mandatory —
#    Python will not pick up new module source in a live interpreter.
```

After that, retry `SpikeSortingRecording.populate(key)` and capture the *full* traceback if it still fails. The line of the traceback inside `make_fetch` / `make_compute` / `make_insert` will tell you exactly where the lookup is happening.

### 2. Your own params / key dict has `'pipeline_version'` baked in

If you (or a notebook you copied from) build a `key` dict like:

```python
key = {"pipeline_version": "v1", "nwb_file_name": ..., ...}
SpikeSortingRecordingSelection.insert_selection(key)
SpikeSortingRecording.populate(key)
```

…then `insert_selection` will silently drop unknown fields, but if any *helper* you wrote does `params["pipeline_version"]` or `key.pop("pipeline_version")` on the way in, you'll get exactly this `KeyError` from inside the `make()` chain. Same goes for a custom `preproc_params` dict where you (or some upstream helper) reads `preproc_params["pipeline_version"]`.

Search your own user code:

```bash
grep -rn "pipeline_version" path/to/your/notebooks/ path/to/your/lab_code/
```

If it's there, that's your bug — the field never existed in upstream Spyglass; some lab-internal wrapper invented it. Remove the reference, or compute `"v1"`/`"v0"` from which class you're calling rather than reading it from the dict.

### 3. Two Spyglass checkouts / two environments

`git pull` in checkout A doesn't change checkout B. If your conda/uv env was installed against a *different* clone (e.g. you have `~/spyglass` and `~/Documents/GitHub/spyglass`), Python is still serving the old one. Verify:

```bash
python -c "import spyglass; print(spyglass.__file__)"
which python
conda info --envs    # or: uv pip list | grep -i spyglass
```

If `__file__` doesn't point inside the checkout you just pulled in, that's the entire problem.

## Diagnostic to run regardless

Re-trigger the failure and capture the **full traceback** (not just the last line). The frames matter:

```python
import traceback
try:
    SpikeSortingRecording.populate(key)
except KeyError:
    traceback.print_exc()
```

Look at the deepest frame inside `make_fetch` / `make_compute` / `make_insert` (or wherever the `KeyError` originates). One of three things will be true:

- The frame is inside *your* code (a wrapper, a helper, a notebook cell) — fix #2 above.
- The frame is inside `spyglass/spikesorting/...` but the file path is in `site-packages/`, not your checkout — fix #1 (stale install) or #3 (wrong env).
- The frame is inside your checkout's `spyglass/spikesorting/...` and references `pipeline_version` — that would contradict what I found in the source, so paste the traceback and we'll re-investigate. (I'd also `git status` and `git log -1` in the checkout to rule out a dirty merge / unfinished pull.)

## What I would NOT do

- Don't roll back the `git pull` blindly — there's no `pipeline_version` schema migration to roll back to, because the field isn't in master either way. The diff is unlikely to be the actual cause.
- Don't `dj.config["safemode"] = False` and start dropping tables. There's no schema mismatch suggested by this error; it's a Python `KeyError`, not a DataJoint `DataJointError` about missing/extra fields.
- Don't paste your `dj_local_conf.json` anywhere — it has DB credentials.

## Most-probable one-liner fix

If you're in a Jupyter session: **kernel restart, then re-import**. That alone resolves this class of "worked yesterday" `KeyError` after a `git pull` more often than any other single action, because it's almost always a stale-module issue. If after kernel restart it still fails, work down the list above.

Send the full traceback (with file paths) and the output of `python -c "import spyglass; print(spyglass.__file__)"` if it's still broken after that, and I can pinpoint it.
