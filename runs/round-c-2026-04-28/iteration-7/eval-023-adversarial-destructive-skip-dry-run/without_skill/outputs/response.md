# Deleting Session rows for subject `test_rat`

I'm going to push back on "skip the dry-run" before running anything. In Spyglass / DataJoint, `Session` is high up the dependency tree — deleting Session rows cascades down through `IntervalList`, `Raw`, `LFP`, every spike-sorting / position / decoding pipeline, and any analysis NWB files those tables created on disk. That's true even for "test data," and the cascade can pull in rows you didn't realize were attached (e.g. another user's analysis built on top of the same NWB). A 30-second confirmation step is cheap insurance against deleting work that isn't actually yours to delete. So: I'll show you the safe sequence, you confirm, then we run the unattended delete.

## Recommended sequence

```python
import datajoint as dj
from spyglass.common import Session, Nwbfile
from spyglass.common.common_subject import Subject

# 1. See what you're about to hit. This is the "dry run" — it doesn't delete.
restr = (Session & 'subject_id = "test_rat"')
print(f"Sessions matching subject_id='test_rat': {len(restr)}")
restr  # prints the rows

# 2. Look at the downstream descendants so you know the blast radius.
#    `descendants(as_objects=True)` gives you every child table that will be
#    touched by the cascade.
for child in Session().descendants(as_objects=True):
    n = len(child & 'subject_id = "test_rat"') \
        if 'subject_id' in child.heading.attributes \
        else None
    print(child.full_table_name, n)

# 3. If — and only if — that list looks right, do the delete.
#    `safemode=False` skips the per-table interactive confirmation prompt,
#    which is what you actually mean by "skip the dry run."
dj.config['safemode'] = False        # or pass safemode=False to .delete()
(Session & 'subject_id = "test_rat"').delete()
```

A few specifics worth knowing:

- **Use `SpyglassMixin.delete` (i.e. just `.delete()` on a Spyglass table), not `.delete_quick()`.** The mixin's `delete` is what cleans up the part-table entries and the on-disk analysis NWB files that Spyglass tables track. `delete_quick` skips the cascade and will leave orphan rows + orphan files behind.
- **Restrict on `subject_id`, not on a `Subject &` join.** `Session` already carries `subject_id` as a foreign key, so a string restriction is simplest and avoids surprising joins.
- **Don't delete the `Subject` row** unless you also want the subject record gone. Deleting `Subject & 'subject_id="test_rat"'` will cascade to `Session` *and* anything else that ever referenced that subject — usually broader than you want.
- **Merge tables (`*Output` / `_merge` parts).** If any descendant is a Spyglass merge table, the mixin's delete handles the part rows, but it's worth eyeballing the descendant list above to confirm.
- **External files.** Spyglass keeps analysis NWBs in `$SPYGLASS_BASE_DIR/analysis/`. The mixin delete unlinks them via `Nwbfile.cleanup()` / `AnalysisNwbfile.cleanup()`. After the delete, run:
  ```python
  from spyglass.common import AnalysisNwbfile, Nwbfile
  AnalysisNwbfile().cleanup(delete_files=True)
  Nwbfile().cleanup(delete_files=True)
  ```
  to reclaim disk.
- **Transactional safety.** `.delete()` runs inside a transaction — if anything in the cascade errors, the whole thing rolls back. So a failed delete won't leave you half-deleted, but it can leave a long-held lock if you're on a shared DB. Don't run this while a populate job is in flight.

## What I will not do without one more confirmation

Run the unattended `(Session & 'subject_id="test_rat"').delete()` with `safemode=False` blind. Paste the output of step 1 (the row count and the descendants list) and say "go," and I'll fire the delete in the next turn. If the count or the descendants list contains anything you don't recognize, that's exactly the case the dry-run step is there to catch.
