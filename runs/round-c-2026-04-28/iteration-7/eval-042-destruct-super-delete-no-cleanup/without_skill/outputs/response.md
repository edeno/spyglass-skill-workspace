# What `super_delete()` actually did, and why your populates are now broken

Short version: you bypassed every safety net that keeps the database and the
filesystem in sync. `super_delete()` is the raw DataJoint `Table.delete()`
with the Spyglass cleanup *intentionally* removed. So your DB rows are gone,
but the analysis NWB files they pointed to are still on disk, and — more
importantly — the FreeSOLO/`ExternalMapping` rows that the DataJoint external
file store uses to remember "this hash belongs to this file" are now in an
inconsistent state. Downstream `populate()` is failing because either
(a) it's trying to fetch a parent row that no longer exists, or (b) it's
trying to *re-create* an `AnalysisNwbfile` row whose filename collides with
an orphaned external/file on disk.

Below is what each piece was supposed to do, what `super_delete` skipped,
and how to clean it up.

---

## 1. What `cautious_delete` was complaining about

`cautious_delete` is the Spyglass mixin override of `dj.Table.delete()`
(defined on `SpyglassMixin` in `spyglass/utils/dj_mixin.py`). Before it
deletes anything, it does a few things vanilla DataJoint doesn't:

1. **Identifies the DataJoint user** running the delete, by joining
   `dj.config["database.user"]` against `LabMember.LabMemberInfo` /
   `LabTeam`. The error you saw — *"Could not find exactly 1 datajoint
   user"* — is this lookup failing. It means your DB login isn't
   registered (or is registered more than once) in `LabMember` /
   `LabMemberInfo`.
2. **Walks merge tables** so that if you delete an upstream key, the
   matching `*Merge.*Output` part-table rows go too (vanilla DJ doesn't
   know about Spyglass merge-table topology and will leave dangling part
   rows).
3. **Cleans up `AnalysisNwbfile` external store entries and on-disk
   files** via `AnalysisNwbfile.cleanup()` / the `nwb_file_abs_path`
   logic, so you don't accumulate orphan `.nwb` files in
   `$SPYGLASS_BASE_DIR/analysis/...`.
4. **Permission/safety checks** (e.g., refusing to delete rows owned by
   another lab member without `--force`).

The right fix for the original error was to make yourself a known DJ
user — add a row to `LabMember` and `LabMember.LabMemberInfo` keyed to
your `dj.config["database.user"]`, with a single `datajoint_user_name`.
**Not** to escape-hatch around it.

## 2. What `super_delete` does

`super_delete` lives on `SpyglassMixin` and is literally:

```python
def super_delete(self, *args, **kwargs):
    """Delete without any of the Spyglass checks. Use with caution."""
    logger.warning("Bypassing cautious_delete for super_delete.")
    super().delete(*args, **kwargs)   # raw dj.Table.delete
```

So compared to `cautious_delete`, `super_delete` skipped **all four**
items above. Specifically, on `AnalysisNwbfile`:

- **No `AnalysisNwbfile.cleanup()`** — the rows in
  `~external_analysis` (the DataJoint external-file tracking table for
  the `analysis` store) that pointed at those NWB files were *not*
  removed, and the `.nwb` files on disk were *not* deleted.
- **No merge-table descent** — any `*Output` merge part-table rows that
  referenced those `analysis_file_name`s are now orphaned (they
  cascaded via FK if the FK was declared with `ON DELETE CASCADE`, but
  any merge-master `*Merge` rows whose part rows are gone are now in a
  weird half-state).
- **No FK cascade audit** — vanilla DJ `delete()` does cascade FKs, so
  downstream computed tables that referenced your `AnalysisNwbfile` rows
  *were* deleted. That's almost certainly part of why your downstream
  populate is broken: the rows it expected to find as parents are gone.

## 3. Why the next `populate()` is now failing

There are three failure modes, depending on which downstream table is
running. From most to least common:

### (a) `make()` calls `AnalysisNwbfile().create(nwb_file_name)` and the filename collides

Most pipeline `make()` methods do something like:

```python
analysis_file_name = AnalysisNwbfile().create(nwb_file_name)
# ... write data into it ...
AnalysisNwbfile().add(nwb_file_name, analysis_file_name)
self.insert1({**key, "analysis_file_name": analysis_file_name, ...})
```

`AnalysisNwbfile().create()` generates a new `analysis_file_name` and
writes the file to disk. If the *same name* already exists on disk (from
your orphaned files) you can get either a silent overwrite or, more
often, an `OSError`/`FileExistsError` from `pynwb`/`h5py` when it tries
to `mode="w-"` the path. Look for tracebacks that bottom out in
`h5py`/`pynwb` complaining about an existing file.

### (b) `make()` calls `fetch_nwb()` and the file is gone but the row isn't

Less common in your case (since you deleted the rows), but if any
downstream table still has a row pointing at one of the deleted
`analysis_file_name`s through a merge table, `fetch_nwb()` will raise
`FileNotFoundError` because `nwb_file_abs_path()` resolves to a path
DataJoint thinks should exist (per `~external_analysis`) but doesn't.

### (c) Merge-table `fetch1()` returns 0 or >1 rows

If a `*Merge` master row is intact but its `*Output` part row was
cascade-deleted, `merge_get_part(key)` will return an empty queryset,
and any downstream `make()` doing `(SomeMerge & key).fetch1("KEY")`
raises `DataJointError: fetch1 should return exactly one tuple`.

## 4. How to clean up

Run these in order. Adapt names to your schema.

### Step 1. See what's orphaned in the external store

```python
from spyglass.common import AnalysisNwbfile
import datajoint as dj

schema = AnalysisNwbfile.connection.schemas[AnalysisNwbfile.database]
ext = schema.external["analysis"]    # the ~external_analysis table

# Files tracked by DJ but not referenced by any AnalysisNwbfile row
unreferenced = ext - AnalysisNwbfile.proj(hash="contents_hash")
print(len(unreferenced), "orphan external rows")
```

(The exact join keys vary slightly with DJ version — `filepath` vs
`hash` — but the idea is: rows in `~external_analysis` that no live
`AnalysisNwbfile` row points at.)

### Step 2. Run the canonical cleanup

```python
AnalysisNwbfile().cleanup(delete_files=True)
```

This is the *thing* `cautious_delete` would have called. It removes
unreferenced rows from `~external_analysis` and (with
`delete_files=True`) deletes the orphan `.nwb` files from
`$SPYGLASS_BASE_DIR/analysis/...`. Run it once; it's idempotent.

If you're nervous, do `delete_files=False` first to see what it
would touch.

### Step 3. Find and clean orphan merge-table rows

If you used merge tables downstream (e.g., `LFPOutput`, `PositionOutput`,
`SpikeSortingOutput`), check for masters without parts:

```python
from spyglass.lfp.lfp_merge import LFPOutput
master_keys = LFPOutput.fetch("KEY")
for k in master_keys:
    if not (LFPOutput & k).merge_get_parent(multi_source=True):
        print("orphan master:", k)
        # (LFPOutput & k).delete_quick()  # uncomment once you've reviewed
```

Repeat per merge table you populated downstream of the deleted
`AnalysisNwbfile` rows.

### Step 4. Fix the original `cautious_delete` complaint

So you don't need `super_delete` next time:

```python
from spyglass.common import LabMember
LabMember().insert_from_name("Your Name")    # if not already there
LabMember.LabMemberInfo.insert1({
    "lab_member_name": "Your Name",
    "datajoint_user_name": dj.config["database.user"],   # exact match
    "admin": 0,
}, skip_duplicates=True)
```

The "not exactly 1" error is almost always one of:
- you have **zero** matching `LabMemberInfo` rows for your DJ login, or
- you have **two** (e.g., the same DJ username registered to two lab
  members — fix by deleting the wrong one).

### Step 5. Re-run the failing populate

After cleanup, the downstream populate should either succeed or fail
with a *real* error (missing upstream key) instead of the
file-collision / fetch1 / FileNotFoundError noise. If a downstream
table is permanently missing parents because of cascade, you'll need to
re-`populate` the upstream computed tables that produced those
`AnalysisNwbfile`s in the first place. That's the irreversible cost of
having used `super_delete`: the upstream rows are gone and have to be
recomputed from the raw NWB.

---

## 5. Rule of thumb going forward

`super_delete` is the "I know what I'm doing, suppress all the airbags"
escape hatch. It exists for cases where the metadata is so corrupted
that `cautious_delete` itself crashes on the cleanup step — *not* for
working around a `LabMember` registration error. The right escalation
ladder when `cautious_delete` complains is:

1. Read the error. Most of them (DJ user not found, foreign key
   violation, merge-table descendant exists) point at a specific row to
   add or remove.
2. If it's a permission/ownership complaint and you actually do own the
   data, pass `force_permission=True` to `cautious_delete`.
3. Only if `cautious_delete` itself errors *during* its own cleanup
   logic do you reach for `super_delete` — and immediately follow it
   with `AnalysisNwbfile().cleanup(delete_files=True)` and a sweep of
   the affected merge tables.

You skipped step 3's cleanup, which is why you're here.
