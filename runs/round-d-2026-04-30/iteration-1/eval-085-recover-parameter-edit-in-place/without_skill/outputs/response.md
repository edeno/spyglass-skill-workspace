# Recovering from an in-place edit of `RippleParameters`

Short version: your downstream `RippleTimesV1` rows (and anything below them) were computed against the *old* `ripple_param_dict`, but the parameter blob they point to is now the *new* one. The provenance link from `RippleTimesV1 -> RippleParameters` is by `ripple_param_name` only — the row itself doesn't store the dict it ran with — so right now your database is silently lying about how those ripple times were produced. You need to (a) restore the truth and (b) recompute. Then change your workflow so this can't happen again.

## Why this is bad (one paragraph of background)

`RippleParameters` is a `dj.Lookup` keyed on `ripple_param_name` with a `BLOB` payload `ripple_param_dict` (see `spyglass/ripple/v1/ripple.py:138-142`). `RippleTimesV1` foreign-keys `RippleParameters` (`spyglass/ripple/v1/ripple.py:182-190`) and inside `make()` it fetches the dict *at populate time* (`fetch1("ripple_param_dict")` at `ripple.py:207-209` and again in `get_ripple_lfps_and_position_info` at `ripple.py:261-263`) and passes the params straight into the detector (`**ripple_detection_params` at `ripple.py:224`). Nothing about the resulting row records *which version* of the dict was used — only the name. `update1()` mutates the blob in place without touching downstream rows, so DataJoint's normal "you changed an upstream key, child rows are stale" guardrail (delete-cascade on key change) never fires. That's exactly the failure mode you hit.

## Recovery, in order

### 1. Stop. Don't populate anything else against `Kay_ripple_detection_v2` until this is sorted.

Anything that downstream-populates from your stale `RippleTimesV1` rows (e.g. anything that joins on those keys) will inherit the wrong-threshold ripples.

### 2. Decide what "the truth" is

Two cases — pick the one that matches your intent:

- **Case A — you actually wanted the new threshold to be the parameters going forward, and the old computation was wrong.** Then the `RippleTimesV1` rows are the stale artifact and need to be deleted and recomputed under the new dict.
- **Case B — the old computation was the correct one, and the `update1()` was a mistake.** Then the *parameters table* is what's wrong and should be reverted; downstream rows can stay.

In both cases the fix is "make the params row and the downstream rows agree on a single dict." You just choose which side moves.

### 3. Inspect what you have right now

```python
from spyglass.ripple.v1 import RippleParameters, RippleTimesV1

# What the params table currently says (the NEW threshold):
current = (RippleParameters &
           {"ripple_param_name": "Kay_ripple_detection_v2"}
          ).fetch1("ripple_param_dict")
print(current["ripple_detection_params"]["speed_threshold"])

# What downstream rows are tagged with:
stale_keys = (RippleTimesV1 &
              {"ripple_param_name": "Kay_ripple_detection_v2"}
             ).fetch("KEY")
print(len(stale_keys), "stale RippleTimesV1 rows")
```

If you happen to remember the old threshold value, write it down now. If you don't, check git/notebook history, lab Slack, etc. — there's no way to recover it from the database itself, because `update1()` overwrote the blob and DataJoint doesn't keep blob history. (This is the deepest reason in-place edits are dangerous.)

### 4. Case A — reconcile by recomputing downstream

```python
# Delete the stale ripple times (and let cascade clear anything below).
# Use the SpyglassMixin delete (cautious_delete) — it warns about merge-table
# entries and gives you a chance to bail if the blast radius is bigger than
# you expected.
(RippleTimesV1 &
 {"ripple_param_name": "Kay_ripple_detection_v2"}).delete()

# Re-populate with the current (new-threshold) params:
RippleTimesV1.populate(
    {"ripple_param_name": "Kay_ripple_detection_v2"},
    display_progress=True,
)
```

Caveats:
- `cautious_delete` will refuse / warn if the rows are referenced by a merge table (e.g. ripple-output merges) without you confirming — read the prompt carefully. If it complains, follow the merge-table delete pattern (delete from the merge part first, then the source).
- Anything *below* `RippleTimesV1` in your pipeline (e.g. ripple-conditioned analyses) will also be deleted by cascade and need re-populating. Make sure that's what you want before pulling the trigger.
- This will create new `AnalysisNwbfile`s for the recomputed rows. Old analysis NWB files orphaned by the delete are cleaned up by the standard nwbfile-cleanup job; if you have storage pressure, run that.

### 5. Case B — reconcile by reverting the params

You don't want to use `update1()` again — that's the tool that got you here. The clean move is:

```python
# Put the old dict back under a NEW name, so future runs use a fresh row
# and the broken row is preserved as evidence:
old_dict = {  # reconstruct from your notes / git history / notebook
    "speed_name": "head_speed",
    "ripple_detection_algorithm": "Kay_ripple_detector",
    "ripple_detection_params": dict(
        speed_threshold=<OLD VALUE>,
        minimum_duration=0.015,
        zscore_threshold=2.0,
        smoothing_sigma=0.004,
        close_ripple_threshold=0.0,
    ),
}
RippleParameters.insert1(
    {"ripple_param_name": "Kay_ripple_detection_v2_orig",
     "ripple_param_dict": old_dict},
    skip_duplicates=True,
)
```

This won't fix the existing downstream rows' provenance — they still point at `Kay_ripple_detection_v2`, whose dict is now wrong. To honestly attribute them, you need to *also* delete the stale rows and re-populate them under `Kay_ripple_detection_v2_orig`. If you can't bring yourself to delete the rows, document the `update1()` event in a lab notebook and treat the existing `Kay_ripple_detection_v2` rows as "as-of <date> with old params; do not re-compute."

In practice Case B almost always degenerates into "delete and recompute," because DataJoint's whole correctness model assumes the row + its upstream key tell you exactly how it was made.

### 6. Re-attach merge-table outputs

If `RippleTimesV1` is exposed through a merge/output table (Spyglass uses these to give downstream tables one foreign key into many ripple-source variants), the merge entries pointing at the deleted `RippleTimesV1` rows go too. After populating, you'll need to re-insert into the merge as you would after any normal recompute. Use the merge table's `insert` / `insert_part_entry` flow, not raw `insert1()` on the part.

## What to do differently next time

The single rule: **never `update1()` a parameters row that has been used.** Treat parameter rows as immutable once any computed table references them. This isn't a Spyglass quirk — it's how all of DataJoint's provenance model is meant to work.

Concretely, adopt one of these patterns:

1. **Versioned names.** Append a version suffix and bump it on every change: `Kay_ripple_detection_v2`, `…_v3`, `…_v4`. The name is the version. Old rows stay attributable to old versions. This is what the existing default rows in `RippleParameters.insert_default()` (`ripple.py:144-178`) do — `default` and `default_trodes` are distinct names, not edits of one row.

2. **Hash-suffixed names.** If you change params programmatically, hash the dict and stick the first 8 chars in the name (`Kay_ripple_a1b2c3d4`). Same dict -> same name -> `skip_duplicates=True` is a no-op; different dict -> different name -> downstream populate makes a *new* row instead of silently using an outdated one.

3. **Guard before edit.** If you really want to change a row, check first that nothing references it:

   ```python
   key = {"ripple_param_name": "Kay_ripple_detection_v2"}
   refs = RippleTimesV1 & key
   assert len(refs) == 0, f"{len(refs)} downstream rows reference this; do not update1"
   (RippleParameters & key).delete()        # cascade is fine because no refs
   RippleParameters.insert1({...new row...})
   ```

   If `len(refs) > 0`, fall back to pattern 1 (new name).

4. **Keep the params dict in source control.** Have a small Python module that constructs the dict from named constants and `insert1(..., skip_duplicates=True)`s it. The git history of that module is your audit log; the database name encodes the version. This is the practice that prevents "I can't remember the old threshold" — git remembers.

5. **`update1()` is for typo-fixing, not parameter sweeps.** A safe use of `update1()` is e.g. fixing a description string that doesn't affect computation. Anything that changes a number passed into `make()` should be a new row.

## TL;DR

Your downstream rows are stale; the params table is correct (under your intended new value) but the row name no longer truthfully describes what produced the existing `RippleTimesV1` rows. Either delete + repopulate `RippleTimesV1` (and cascade) under the current name, or re-insert the old dict under a new name and migrate. Going forward: never `update1()` a parameters row that's been populated against — always insert a new, versioned name.
