# `KeyError: 'pipeline'` on `SpikeSortingRecording.populate` after `git pull`

Short answer: **almost certainly yes, this is schema drift** — your code now references a `pipeline` column (or config key) that didn't exist yesterday, and the running database / your config / a parent table hasn't caught up. A `KeyError` (as opposed to `dj.errors.MissingAttributeError` or `OperationalError`) is the tell — it means Python dict-style lookup is failing in the `make()` body or in a key-fetch step, not the MySQL layer.

Below is how to localize it in ~5 minutes, then the fix paths.

## 1. First: which `SpikeSortingRecording` are you using?

Spyglass has two spike-sorting modules that are easy to confuse:

| Module | Class location | Status |
|---|---|---|
| v0 (legacy) | `spyglass.spikesorting.SpikeSortingRecording` | being phased out |
| v1 (current) | `spyglass.spikesorting.v1.recording.SpikeSortingRecording` | active, gets most recent commits |

```python
import spyglass.spikesorting as ss0
import spyglass.spikesorting.v1.recording as ssv1
print(ss0.SpikeSortingRecording.__module__)
print(ssv1.SpikeSortingRecording.__module__)
```

The PR-churn answer matters because `pipeline` has shown up as a column in the v1 path historically (e.g., on selection / merge-table entries). Check which one your script imports — `git pull` could have changed the re-exports in `spyglass/spikesorting/__init__.py`, so the same import name might silently resolve to a different class than yesterday.

## 2. Get the actual traceback, not just the error class

`KeyError: 'pipeline'` could come from at least four places:

1. **Inside `make()`**: code does `key['pipeline']` but the upstream key dict doesn't have it (most likely cause after a pull — a new field was added to the parent `Selection` table but your existing `Selection` rows were inserted before that field existed, so they have no `pipeline` value).
2. **A `fetch1()` projection**: `(ParentTable & key).fetch1('pipeline')` where the parent's heading doesn't have `pipeline` yet (DB hasn't been migrated).
3. **A merge/part table dispatch**: some merge tables key on a `pipeline`-named source and `merge_get_parent` raises `KeyError` if the source name isn't registered.
4. **A config dict lookup** (`dj.config['custom']['pipeline']` or similar) — less likely from a `populate` call but possible if there's a new config requirement.

Get the full traceback:

```python
try:
    SpikeSortingRecording.populate(display_progress=True)
except Exception:
    import traceback; traceback.print_exc()
```

The line that raises is what tells you which of the four it is. Don't skip this step — the fix is different in each case.

## 3. Confirm schema drift directly

Two complementary checks:

**a. Is the running DB heading out of sync with the code definition?**

```python
from spyglass.spikesorting.v1.recording import SpikeSortingRecording, SpikeSortingRecordingSelection

# code-side definition (what the new code expects):
print(SpikeSortingRecordingSelection.definition)

# DB-side heading (what the table actually has on the server):
print(SpikeSortingRecordingSelection.heading)
```

If `pipeline` appears in `definition` but not in `heading`, the table on your DB server hasn't been migrated. That's the smoking gun for schema drift.

**b. Did the git pull actually add `pipeline` somewhere?**

```bash
cd $SPYGLASS_SRC   # wherever your editable spyglass checkout lives
git log -p -- src/spyglass/spikesorting/v1/recording.py | head -200
git log --oneline -10 -- src/spyglass/spikesorting/
```

Look for a recent commit that adds a `pipeline` column or a `key['pipeline']` reference. A diff against yesterday (`git diff HEAD@{1.day.ago}`) is fastest.

## 4. Likely fixes, in increasing order of disruption

### a. You're on an editable install and missed `pip install -e .`

`git pull` does not re-run setup. If `pyproject.toml` / dependencies changed, your installed metadata can lag. Re-install:

```bash
pip install -e ".[spikesorting]"   # or whatever extras you use
```

Sometimes the `KeyError` is downstream of a partially-loaded module.

### b. The DB heading is missing the new column (true schema drift)

DataJoint won't auto-migrate. You have two options:

- **If the new column is nullable / has a default**: you can `ALTER TABLE` it in. Spyglass usually ships a migration note in the PR or in `CHANGELOG.md`. Check there first:
  ```bash
  cd $SPYGLASS_SRC && git log -p CHANGELOG.md | head -100
  ```
- **If it's a primary-key field**: you cannot just `ALTER`. The table will need to be dropped and re-populated, OR you pin Spyglass to the previous commit until you're ready to migrate. Don't drop blindly — it cascades. Check downstream:
  ```python
  dj.Diagram(SpikeSortingRecording) + 2
  ```

### c. Pin until you're ready to migrate

Fastest unblock if you have an analysis deadline:

```bash
cd $SPYGLASS_SRC
git log --oneline -20    # find yesterday's commit
git checkout <yesterday-sha>
```

Then file an issue (or check if one's open) at https://github.com/LorenFrankLab/spyglass/issues. The maintainers usually post migration steps when a column is added.

## 5. What I cannot tell you without more info

- **Which line raises** — I'd need the traceback. Without it, all four causes above are still in play.
- **Which `SpikeSortingRecording`** (v0 vs v1) — depends on your import.
- **Whether a migration script exists** for this specific change — depends on the exact commit that landed in `master`. Check `CHANGELOG.md` and the recent commit messages in `src/spyglass/spikesorting/`.

## TL;DR action list

1. Paste the full traceback (not just the error class).
2. `print(YourTable.definition)` vs `print(YourTable.heading)` — diff them.
3. `git log -p` on the spike-sorting files since yesterday — find the commit that added `pipeline`.
4. Check `CHANGELOG.md` for a migration note.
5. If urgent: `git checkout` to yesterday's SHA to unblock, then plan the migration.

Most likely outcome: the new commit added a `pipeline` field to `SpikeSortingRecordingSelection` (or its parent), and either (a) your DB hasn't been ALTERed, or (b) your existing Selection rows pre-date the field and the make() body now does `key['pipeline']` unconditionally. Both are schema-drift-class problems and both are real — you weren't imagining it working yesterday.
