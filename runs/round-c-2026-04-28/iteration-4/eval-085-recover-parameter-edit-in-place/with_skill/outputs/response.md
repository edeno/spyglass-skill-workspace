# Recovering from an in-place edit of `RippleParameters`

Short version: you can't "un-edit" the row — the old `zscore_threshold=2` value isn't stored anywhere in the database anymore. The downstream `RippleTimesV1` rows still reference the row by name (`ripple_param_name="Kay_ripple_detection_v2"`), but the row's blob now says `zscore_threshold=3`. So those `RippleTimesV1` rows are *provenance-corrupted*, not just stale: their key claims `zscore=3` but the analysis NWB on disk was actually computed with `zscore=2`. Anyone reading the table tomorrow will get the wrong answer for "what threshold produced these ripples?"

This is exactly the failure mode the skill warns about under `destructive_operations.md` → "`update1` on params with downstream rows" (`skills/spyglass/references/destructive_operations.md:200-270`).

## Recovery plan (sketch — confirm before any destructive step)

There are two independent decisions:

1. **What value do you actually want going forward — 2, 3, or both?**
2. **Do you want to keep the old `RippleTimesV1` rows (recompute provenance) or drop them?**

Below is the recommended shape. **Do not run the delete step until you've inspected the row counts and confirmed (Phase 1-3 of the inspect-before-destroy workflow in `destructive_operations.md`).**

### Step 1 — Stop treating the existing row as authoritative

The row named `"Kay_ripple_detection_v2"` is now ambiguous. Don't `update1()` it again to "fix" it — that compounds the problem. Instead, create distinct, self-describing names for both threshold values so downstream rows are interpretable from the name alone (per `feedback_loops.md` naming guidance, e.g. `kay_speed4_zscore2`, `kay_speed4_zscore3`):

```python
from spyglass.ripple.v1 import RippleParameters

# 1a. Insert the value you actually want under a NEW, descriptive name.
#     Use the full nested blob shape — speed_threshold and zscore_threshold
#     live under "ripple_detection_params", NOT at the top level.
RippleParameters().insert1({
    "ripple_param_name": "kay_speed4_zscore3",
    "ripple_param_dict": {
        "speed_name": "head_speed",
        "ripple_detection_algorithm": "Kay_ripple_detector",
        "ripple_detection_params": {
            "speed_threshold": 4.0,
            "minimum_duration": 0.015,
            "zscore_threshold": 3.0,
            "smoothing_sigma": 0.004,
            "close_ripple_threshold": 0.0,
        },
    },
})

# 1b. If you ALSO want to preserve the original zscore=2 setup as a
#     reproducible config (recommended — your old downstream rows used it),
#     insert it too under its own name. The blob isn't recoverable from
#     the corrupted row, but the values are documented in
#     ripple_pipeline.md (and presumably in your notes / git history of
#     whatever script created "Kay_ripple_detection_v2").
RippleParameters().insert1({
    "ripple_param_name": "kay_speed4_zscore2",
    "ripple_param_dict": {
        "speed_name": "head_speed",
        "ripple_detection_algorithm": "Kay_ripple_detector",
        "ripple_detection_params": {
            "speed_threshold": 4.0,
            "minimum_duration": 0.015,
            "zscore_threshold": 2.0,
            "smoothing_sigma": 0.004,
            "close_ripple_threshold": 0.0,
        },
    },
})
```

(If you don't actually know the rest of the original blob, fetch the
current row first — `(RippleParameters & {"ripple_param_name":
"Kay_ripple_detection_v2"}).fetch1()` — and copy everything except
`zscore_threshold` into the new rows. That's the only piece you know
changed.)

### Step 2 — Inspect what's downstream of the corrupted name

Before deleting anything, count the affected rows and remind yourself
what cascades:

```python
from spyglass.ripple.v1 import RippleTimesV1

stale = RippleTimesV1 & {"ripple_param_name": "Kay_ripple_detection_v2"}
print(len(stale), "RippleTimesV1 rows reference the corrupted params name")
stale.fetch(as_dict=True, limit=5)        # what rows are these?
print(stale.get_table_storage_usage(human_readable=True))  # how much disk
```

Also check whether anything is downstream of `RippleTimesV1` itself
(MUA, decoding selection, custom tables) — those will cascade when you
delete:

```python
# Source-graph view of what's downstream of RippleTimesV1:
#   python skills/spyglass/scripts/code_graph.py path --down RippleTimesV1
# Runtime view (will show your custom tables too):
#   python skills/spyglass/scripts/db_graph.py  path --down RippleTimesV1
```

**Stop here.** Report the row counts, samples, and cascade list; get
explicit confirmation before Step 3.

### Step 3 — Delete the corrupted-provenance rows and recompute

Once confirmed:

```python
# Delete the RippleTimesV1 rows that were computed under the now-mutated
# params name. .delete() on a SpyglassMixin table routes through
# cautious_delete — if you don't own the sessions, it will raise
# PermissionError; coordinate with the owner rather than reaching for
# super_delete().
(RippleTimesV1 & {"ripple_param_name": "Kay_ripple_detection_v2"}).delete()

# Optionally also delete the corrupted parameter row itself, now that
# nothing downstream references it:
(RippleParameters & {"ripple_param_name": "Kay_ripple_detection_v2"}).delete()
```

### Step 4 — Repopulate against the new, unambiguous param names

Build a fully-scoped populate key. `RippleTimesV1`'s PK is
`RippleLFPSelection` PK + `ripple_param_name` +
`PositionOutput.proj(pos_merge_id='merge_id')`
(`src/spyglass/ripple/v1/ripple.py:182-186`). Restricting populate to
just `{"ripple_param_name": ...}` re-runs across every eligible
upstream combo — usually not what you want.

```python
populate_key = {
    **rip_sel_key,                       # RippleLFPSelection PK fields
    "ripple_param_name": "kay_speed4_zscore3",  # or zscore2, or both
    "pos_merge_id": pos_merge_id,        # specific PositionOutput merge_id
}
RippleTimesV1.populate(populate_key, display_progress=True)
```

## Why not just `update1()` it back to 2?

That would corrupt provenance a second time — any new analyses you ran
in the interim would now silently claim `zscore=2` even though they were
computed under `zscore=3`. The "row name is the contract" model in
DataJoint only works if the row is immutable once anything downstream
exists. Recovery requires *new* rows with *new* names; you cannot undo
the corruption of the existing name, only stop using it.

## Things to verify, not assume

- **Whether you actually own the affected sessions.** If `.delete()`
  raises `PermissionError` naming another experimenter, the right move
  is to coordinate with them, not bypass with `super_delete()`
  (`destructive_operations.md` "Team-based protection").
- **Whether `Kay_ripple_detection_v2` is referenced by anything other
  than `RippleTimesV1`** (custom tables, group tables, downstream MUA
  detection on those ripple times). The `db_graph.py` / `code_graph.py`
  commands above are the way to check.
- **The exact blob you originally had.** The pre-edit value of every
  field other than `zscore_threshold` is gone from the DB; reconstruct
  from your code/notebook history before re-inserting "the old version"
  as `kay_speed4_zscore2`.
- **Whether the analysis NWB files for the corrupted rows still exist
  on disk.** After deleting, you may want to run
  `AnalysisNwbfile().cleanup(dry_run=True)` to see orphaned files;
  inspect the log before running with `dry_run=False`
  (`destructive_operations.md` "File cleanup").

## Forward-looking guard

Before the next `update1()` on any params table, check no downstream
rows exist (this is the snippet from `destructive_operations.md:255-268`):

```python
for child in RippleParameters().descendants(as_objects=True):
    if "ripple_param_name" not in child.heading.names:
        continue
    n = len(child & {"ripple_param_name": "<the name you want to mutate>"})
    assert n == 0, f"{child.table_name} has {n} rows under this params name"
```

If any descendant has rows, insert a new params row under a new name
instead of mutating the existing one. That's the rule that would have
prevented this in the first place.
