# `KeyError: 'pipeline'` after `git pull` on `SpikeSortingRecording.populate`

Short answer: **probably not in-DB schema drift**. A `KeyError` is a Python dict lookup, not a DataJoint relational error — DataJoint surfaces missing-column / FK problems as `DataJointError` or `IntegrityError`, never `KeyError`. The "worked yesterday + git pull today" pattern points at **source-vs-environment drift** (or stale state), not at a column the database is missing.

I can't pin the exact `'pipeline'` key without seeing the full traceback — `'pipeline'` isn't a documented field on any of the v1 spike-sorting selection / params tables I'd expect (`sort_group_id`, `interval_list_name`, `preproc_param_name`, `team_name`, `recording_id`, etc.). So this is a hypothesis I'd want you to confirm rather than a definite diagnosis.

## What I'd suspect, in order

1. **You pulled new source but didn't reinstall.** Spyglass is installed editable (`pip install -e .`); a `git pull` updates `.py` files but does **not** re-resolve `pyproject.toml` / `setup.py` dependencies. If the new commit added a required key to a params dict / preset / config schema and bumped a dependency at the same time, you can land in a half-upgraded state where the new code reads `params['pipeline']` but the dependency that ships the default isn't there yet. Re-run `pip install -e .` from your `$SPYGLASS_SRC` checkout.
2. **A pre-existing row in a Lookup / params table is now missing a key the new `make()` reads.** Spyglass is conservative about migrating existing rows when defaults change. If yesterday's default params blob (e.g. a `sorter_params`, `preproc_params`, or artifact-params dict stored as a `blob` / `longblob`) lacked a `'pipeline'` field that today's `make()` now does `params['pipeline']` on, you get `KeyError: 'pipeline'` even though the schema (column list) is unchanged. This is **source drift against existing row contents**, not column drift. Common with `dj.Lookup` defaults that get re-seeded only via `insert_default()` (e.g., `ArtifactDetectionParameters().insert_default()` — `spikesorting/v1/artifact.py`).
3. **An actual schema column was added.** Possible but less likely to surface as `KeyError`. If a new non-default column was added to `SpikeSortingRecordingSelection` and your local DB is on the old schema, you typically see a `DataJointError`/`IntegrityError` or DataJoint complaining the heading doesn't match — not `KeyError`. You can rule this in/out by comparing source vs. runtime headings (commands below).
4. **Unrelated stale state.** A reserved job, an old `dj_local_conf.json` pointing at a different DB, or a Python kernel that imported the *old* module before the pull and is still resolving against it. `importlib.reload` won't fully clean this — restart the kernel.

## Confirmation checks (run before changing anything)

```bash
# Confirm Spyglass really updated, and reinstall in-place
cd $SPYGLASS_SRC
git log -1 --oneline                  # what commit are you on?
git diff HEAD@{1} HEAD -- src/spyglass/spikesorting/v1/recording.py
git diff HEAD@{1} HEAD -- src/spyglass/spikesorting/v1/sorting.py
pip install -e .                      # picks up any new deps + console scripts
```

Then in Python:

```python
# Full traceback, please — the final KeyError line is rarely the cause.
# Reproduce on ONE key with orchestration off so the trace is clean.
from spyglass.spikesorting.v1 import (
    SpikeSortingRecordingSelection, SpikeSortingRecording,
)

# Pick the failing recording_id. Inspect the row contents:
key = (SpikeSortingRecordingSelection & your_restriction).fetch1("KEY")
row = (SpikeSortingRecordingSelection & key).fetch1()
print(row)                            # does any blob field hold a dict
                                       # missing a 'pipeline' key?

# Run a single key, no reservation, no parallelism — full traceback:
SpikeSortingRecording.populate(key, reserve_jobs=False, processes=1)
```

If the traceback names a params-table fetch (e.g., `SpikeSortingPreprocessingParameters`), the `KeyError` is on that blob's contents, not the recording row itself.

To rule out actual column drift in one call, compare source heading vs. live DB heading:

```bash
# Source-only (what the .py file declares):
python skills/spyglass/scripts/code_graph.py describe SpikeSortingRecordingSelection --json

# Runtime (what the DB actually has) + parents/children + row count:
python skills/spyglass/scripts/db_graph.py describe SpikeSortingRecordingSelection --count --json
```

If those two headings disagree, you have real schema drift; coordinate with whoever owns the DB before forcing a migration. If they agree, it's source-vs-row or source-vs-env drift, not the schema.

## Minimal fix (once you've confirmed the cause)

- **Half-upgraded install** → `pip install -e .` in `$SPYGLASS_SRC`, restart the kernel, retry the failing key.
- **Stale params-row contents** → re-seed the relevant `*Parameters().insert_default()` (after confirming no in-flight populate references the old row), or insert a new params row with the `'pipeline'` field that current source expects. Don't `.delete()` the old default without checking who else depends on it (Core Directive: never delete without confirmation; `.delete()` on `SpyglassMixin` is team-gated).
- **Actual schema drift** → don't hand-edit `src/spyglass/...` to "fix" it; that's [Core Directive #8 — don't edit the installed package](https://github.com/LorenFrankLab/spyglass). File against upstream and pin to the previous commit until the migration ships: `git checkout <yesterday's-sha>`.

## Watch-outs

- **Don't `git checkout` master forward-and-back without `pip install -e .` in between.** Editable installs reflect source state, but new dependencies don't appear until pip re-runs.
- **Schema drift is a real risk on a shared DB**, just not the most likely cause of `KeyError`. If multiple lab members run the same DB and you bumped Spyglass before they did, your inserts may write columns their old code can't read. Coordinate before merging the new commit.
- **If the traceback frames go through `SpikeSortingPreprocessingParameters` or `_get_recording_extractor` / `make_recording`**, the missing `'pipeline'` key is in a stored params blob, not in your call. Inspect the blob's dict directly.
- **Paste the full traceback** (not just the last line) and the exact failing `key`. With those, I can name the exact frame the `KeyError` originates in and whether the fix is reinstall, re-seed params, or pin to yesterday's commit.
