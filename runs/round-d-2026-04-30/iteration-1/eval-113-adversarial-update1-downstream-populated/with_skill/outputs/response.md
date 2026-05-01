# Don't `update1()` here — it will silently corrupt the provenance of every populated `RippleTimesV1` row

You've already got `RippleTimesV1` rows populated for several sessions under
`ripple_param_name='default'`. Those rows reference the parameter row **by name**
(`ripple_param_name` is the FK), not by value. If you mutate
`ripple_param_dict` in place with `update1()`, every downstream row will continue
to claim it was computed under `ripple_param_name='default'`, but the blob it
points at no longer matches what was actually used at populate time. Provenance
is silently broken — there's no error, no warning, and no easy way to tell
afterward which rows were computed under the old vs. new threshold. This is
called out explicitly in the Spyglass skill's destructive-operations and ripple
references and in `ripple/v1/ripple.py` parameter semantics.

The correct pattern is to **insert a new `RippleParameters` row under a new
name**, then re-populate `RippleTimesV1` against the new name. The old `default`
rows stay intact and interpretable; the new rows live alongside under the new
name; you (and anyone reading later) can tell which is which.

## What to do instead

### 1. Insert a new params row (new name, new threshold)

The blob shape matters — `speed_threshold` is **nested under
`ripple_detection_params`**, not at the top level of `ripple_param_dict`. Copy
the rest of the existing `default` blob so you only change the one knob:

```python
from spyglass.ripple.v1.ripple import RippleParameters

# Pull the existing default blob so you don't drop fields by accident.
default_blob = (RippleParameters & {"ripple_param_name": "default"}).fetch1(
    "ripple_param_dict"
)
# default_blob looks like:
# {
#     "speed_name": "head_speed",
#     "ripple_detection_algorithm": "Kay_ripple_detector",
#     "ripple_detection_params": {
#         "speed_threshold": 4.0,        # current default
#         "minimum_duration": 0.015,
#         "zscore_threshold": 2.0,
#         "smoothing_sigma": 0.004,
#         "close_ripple_threshold": 0.0,
#     },
# }

new_blob = {
    **default_blob,
    "ripple_detection_params": {
        **default_blob["ripple_detection_params"],
        "speed_threshold": 8.0,   # cm/s — your new value
    },
}

RippleParameters().insert1({
    "ripple_param_name": "default_speed8",   # pick any new name
    "ripple_param_dict": new_blob,
})
```

Pick whatever name you like (`"default_speed8"`, `"speed_thresh_8cm"`,
`"default_v2_2026_04_30"`, etc.) — just make it informative enough that future-you
can tell what's different.

### 2. Re-populate `RippleTimesV1` under the new name

`RippleLFPSelection` rows from your previous runs are still valid (they don't
depend on `ripple_param_name`). The PK of `RippleTimesV1` is
`(RippleLFPSelection, RippleParameters, PositionOutput.proj(pos_merge_id='merge_id'))`
(`ripple/v1/ripple.py:182-186`). Build a **fully-scoped** populate key per
session — don't restrict to just `{"ripple_param_name": ...}`, or you'll re-run
against every eligible `(RippleLFPSelection, pos_merge_id)` combo in the DB,
which is almost never what you want:

```python
from spyglass.ripple.v1.ripple import RippleTimesV1, RippleLFPSelection

for rip_sel_key in (RippleLFPSelection & your_session_restriction).fetch("KEY"):
    populate_key = {
        **rip_sel_key,
        "ripple_param_name": "default_speed8",
        "pos_merge_id": pos_merge_id_for_this_session,  # the same one used before
    }
    RippleTimesV1.populate(populate_key)
```

Use whatever `pos_merge_id` (`PositionOutput` merge_id) the original `default`
rows used — typically the same one. You can pull it from the existing rows:

```python
old_keys = (RippleTimesV1 & {"ripple_param_name": "default"}).fetch("KEY", as_dict=True)
# each old key carries pos_merge_id; reuse it under the new ripple_param_name.
```

### 3. (Optional) decide what to do with the old `default` rows

Three sane options — pick based on whether the 4 cm/s rows are still useful:

- **Keep them.** Cheap; `default` continues to mean "4 cm/s threshold". This is
  the safest default if anyone else's analysis or any export points at
  `ripple_param_name='default'`.
- **Rename `default`** to something descriptive (e.g. `default_speed4`) so the
  name `default` is freed up for future use. You'd need to update the
  `RippleParameters` row's PK plus all downstream `RippleTimesV1.ripple_param_name`
  values — this is its own cascade and not what you originally asked for, so
  flag if you want to go this route.
- **Delete them**, after confirming you don't need 4 cm/s outputs. This is a
  destructive op — inspect first:

  ```python
  target = RippleTimesV1 & {"ripple_param_name": "default"}
  print(len(target))                   # how many rows
  target.fetch(as_dict=True, limit=5)  # spot-check
  # plus check downstream: any MUA / decoding pipeline rows that reference
  # these RippleTimesV1 entries? If yes, those cascade too. Walk them with:
  #   python skills/spyglass/scripts/db_graph.py path --down RippleTimesV1
  ```

  Only after you've confirmed scope (and confirmed with me / your collaborators):
  `target.delete()`. Note `.delete()` runs `cautious_delete` and will block on
  team-permission grounds if any of those sessions are owned by another lab
  member. That's a feature, not a bug — coordinate with the owner rather than
  reaching for `super_delete()`.

## Cascade summary (the four slots)

1. **New row:** new `RippleParameters` row at a new `ripple_param_name`. The
   existing `default` row is untouched.
2. **Re-populate:** `RippleTimesV1.populate(key)` for each session, keyed on
   `(RippleLFPSelection_pk, ripple_param_name='default_speed8', pos_merge_id)`.
   New rows land in `RippleTimesV1` alongside the old ones.
3. **Unaffected:** `LFPV1`, `LFPBandV1`, `RippleLFPSelection`, `TrodesPosV1` /
   `DLCPosV1`, `PositionOutput`, and v1 `SpikeSorting` are all upstream of (or
   parallel to) `RippleTimesV1` and **don't need re-running**. Anything
   downstream that consumed `RippleTimesV1` rows under `default` (MUA detection
   keyed on ripple times, decoding analyses scoped to ripple intervals, paper
   exports) will need to be re-keyed against the new param name if you want
   those analyses under the 8 cm/s threshold — but those are choices, not
   automatic invalidations.
4. **Verify scope:** confirm exactly which downstream tables consume
   `ripple_param_name`:

   ```bash
   python skills/spyglass/scripts/db_graph.py path --down RippleParameters
   ```

   or in a Python session:

   ```python
   for child in RippleParameters().descendants(as_objects=True):
       if "ripple_param_name" not in child.heading.names:
           continue
       print(child.table_name, len(child & {"ripple_param_name": "default"}))
   ```

## Why this matters more than it sounds

`update1()` doesn't raise, doesn't warn, doesn't mark the downstream rows
stale. The DB will happily let you mutate the blob and the existing
`RippleTimesV1` rows will keep their `analysis_file_name` blobs computed under
4 cm/s while their `ripple_param_name='default'` foreign key now resolves to a
blob saying 8 cm/s. Six months from now (or in a paper export, or when
re-running on a new session), the only way to recover ground truth is from
git/notebook history — there's no DB-side record. New-name-and-repopulate
costs you one parameter row and one populate pass; in-place `update1()` costs
you the integrity of every analysis built on those ripple times.

If you want, I can help draft the exact populate keys for your specific
sessions — share the session list / `RippleLFPSelection` keys and I'll
assemble them.
