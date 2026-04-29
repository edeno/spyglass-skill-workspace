## Short version

You bypassed the wrong check, and you also skipped the file-cleanup pass that the normal delete path runs for you. Two separate problems are layered on top of each other:

1. The original error wasn't a permissions denial — it was a **setup gap**. `Could not find exactly 1 datajoint user ... in common.LabMember.LabMemberInfo` means your DataJoint username has no matching row in `LabMember.LabMemberInfo`, so `cautious_delete` couldn't even run its team check. The fix is to insert your `LabMember` / `LabMemberInfo` row, not to bypass the check.
2. `super_delete()` aliases straight to `datajoint.Table.delete` and **does not run Spyglass's external-file cleanup**. So the DB rows are gone, but the analysis NWB files (and their entries in the external/raw filepath tables) are still on disk and in stale states. That's almost certainly what's breaking your downstream populate now.

Below is what's actually wrong and how to recover.

---

## What `super_delete()` actually did

From `src/spyglass/utils/mixins/cautious_delete.py:249-254`, `super_delete(warn=True)` is a thin alias to `datajoint.Table.delete`. It:

- Skips `cautious_delete`'s team-permission check (that's the part you wanted).
- Also skips `cautious_delete`'s post-delete loop that calls into the external filepath cleanup for each `ext_type`.
- Logs the bypass to `common_usage.CautiousDelete` (unless you passed `warn=False`).

So compared with a normal `(AnalysisNwbfile & key).delete()`:

| Step | `.delete()` (cautious path) | `.super_delete()` |
| ---- | --------------------------- | ----------------- |
| Team-permission check | yes | skipped |
| DB rows in `AnalysisNwbfile` removed | yes | yes |
| Cascaded child rows removed | yes (per FK) | yes (per FK) |
| External filepath entries (`schema.external["analysis"]`) cleaned | yes | **skipped** |
| Orphan analysis NWB files on disk removed | yes | **skipped** |

The contrast with `force_permission=True` matters here: that flag also skips the team check, but stays on the cautious_delete code path, so the per-`ext_type` external cleanup still runs (`cautious_delete.py:238-241`). `super_delete` is the harsher of the two and the one that leaves files behind.

## Why downstream populate is broken now

A typical failure mode after `super_delete()` on `AnalysisNwbfile`:

- The row in `AnalysisNwbfile` is gone, so any merge part / pipeline table that referenced it cascaded away too. Good so far.
- But the **external filepath table entry** (managed by DataJoint's `schema.external["analysis"]` store) is still there, pointing at an `.nwb` file on disk that nothing in the schema references anymore. It's an orphan from DataJoint's POV.
- When a downstream `populate()` tries to write a new analysis file for the same key, depending on which pipeline you're running, you can hit one of:
  - `IntegrityError` / duplicate filepath in `~external_analysis` because the orphan entry collides with what populate is trying to register.
  - `FileExistsError` / `OSError` if populate computes a deterministic filename that already exists on disk.
  - Stale rows in *part* tables of merge masters that didn't cascade — `super_delete` only cascades through declared FKs; rows in tables that don't have a FK back to `AnalysisNwbfile` (or whose FK went through a path the cascade didn't touch) stay behind and now reference a vanished parent in spirit but not in schema.
  - For decoding/spike-sorting outputs specifically, pipeline-scoped cleanups like `DecodingOutput().cleanup(...)` or `SpikeSortingOutput` part rows that reference the old file by UUID can also be left dangling.

In other words: `super_delete` punched a hole in the row layer but left the **file/external-filepath layer** intact, and your populate is now tripping over the resulting inconsistency.

## What you should have done

The original error message — `Could not find exactly 1 datajoint user ... in common.LabMember.LabMemberInfo` — is documented in `setup_troubleshooting.md` as a setup gap, not a permission denial. The fix is to add yourself to `LabMember`:

```python
import spyglass.common as sgc
import datajoint as dj

sgc.LabMember.insert1({
    'lab_member_name': 'Your Name',
    'first_name': 'Your',
    'last_name': 'Name',
}, skip_duplicates=True)

sgc.LabMember.LabMemberInfo.insert1({
    'lab_member_name': 'Your Name',
    'google_user_name': 'you@lab.org',
    'datajoint_user_name': dj.config['database.user'],
    'admin': 0,
}, skip_duplicates=True)
```

Once that row exists, `cautious_delete` can do its team check. If it then raises a real `PermissionError`, that's a *different* situation — it means another lab member owns the session and you need to coordinate with them, not bypass.

## Recovery now

Stop running more populates against the affected keys until you've cleaned up. Order matters here.

### 1. See what's actually orphaned

```python
from spyglass.common import AnalysisNwbfile, Nwbfile
from spyglass.common.common_nwbfile import schema  # or wherever your install exposes it

# Orphan analysis-file external entries (DB-side)
schema.external["analysis"].unused()    # list rows external cleanup would touch
schema.external["raw"].unused()         # same for raw store
```

Read the output. These are the entries `super_delete` skipped.

### 2. Run Spyglass's cleanup helpers (the ones `super_delete` skipped)

`AnalysisNwbfile().cleanup(dry_run=True)` is the safe-preview version — it logs what would be removed without removing anything. Do this first:

```python
AnalysisNwbfile().cleanup(dry_run=True)
```

Read the logs. If the paths it lists match what you `super_delete`d (and nothing live), then run for real:

```python
AnalysisNwbfile().cleanup(dry_run=False)
```

**Caveat on `Nwbfile.cleanup` (different signature, no dry_run):** `Nwbfile.cleanup(delete_files=False)` is destructive in *both* modes — it always mutates the external table; `delete_files` only controls whether on-disk files are removed (`common_nwbfile.py:140-146`). Don't reach for it as a "preview"; passing `dry_run=True` will raise `TypeError`. If you also super_deleted raw `Nwbfile` rows and want to clean those up, run `Nwbfile.cleanup()` first (entries only) and review, then `Nwbfile.cleanup(delete_files=True)` once you're sure.

### 3. Pipeline-scoped cleanups, if relevant

If the downstream populate that's broken is in decoding, also run:

```python
DecodingOutput().cleanup(dry_run=True)
# review logs
DecodingOutput().cleanup(dry_run=False)
```

Same `dry_run` shape applies. Other pipeline-scoped cleanups follow the `AnalysisNwbfile().cleanup(...)` instance-method shape.

### 4. Check for orphan part rows in merge masters

If the deleted `AnalysisNwbfile` rows fed into a merge pipeline (`SpikeSortingOutput`, `DecodingOutput`, `PositionOutput`, `LFPOutput`, `LinearizedPositionOutput`), inspect the master and its parts. Use `merge_restrict` / `merge_get_part` rather than naive `&` restriction (the master's heading is just `merge_id`, so `& {"nwb_file_name": ...}` returns the whole table). You may need to clean up part rows whose source file no longer exists — but **inspect first**, then decide; do not run another `super_delete`.

### 5. Then retry populate

Re-run the downstream populate against a single key first as a smoke test before launching the full set, and watch for the same error class. If it still fails, the next traceback should point at a more specific orphan you missed in step 1.

---

## Going forward

- A `Could not find exactly 1 datajoint user` error means "add yourself to `LabMember`", not "bypass the check". The Spyglass codebase deliberately routes through `cautious_delete` so analysis-file cleanup runs alongside the row delete; jumping to `super_delete` skips both protections together.
- If you ever do hit a real team-permission `PermissionError` on a session you don't own, the documented response is to coordinate with the experimenter named in the error, not to escalate to `super_delete` or `force_permission=True`.
- Whenever you do need a bypass (`super_delete`, `force_permission=True`, `merge_delete_parent`), **always** follow it with the file cleanup that the cautious path would have run, in the same session.
