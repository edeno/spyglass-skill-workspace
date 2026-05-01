# Recovering from an in-place `update1()` on `RippleParameters`

Short version: your DB now has *broken provenance* — the `RippleTimesV1`
rows under `ripple_param_name="Kay_ripple_detection_v2"` claim to have
been computed with the new `speed_threshold`, but they were actually
computed with the old one. The fix is to re-establish a consistent
mapping between param-name and ripple-times by either (A) reverting
the params row and starting over with a *new* name, or (B) re-running
the populate so the rows on disk match the current params blob. There
is no "patch the metadata" shortcut — DataJoint doesn't track which
blob value produced a given Computed row; the contract is "name →
blob → downstream rows" and you broke it.

Below is the recovery, the reasoning behind it (cascade scope), and
the rule going forward.

---

## 1. Inspect first — confirm the scope of the damage

Before deleting anything, find every `RippleTimesV1` row populated
under that name, and check no other params name aliases the same
problem.

```python
import datajoint as dj
from spyglass.ripple.v1 import RippleParameters, RippleTimesV1

bad_name = "Kay_ripple_detection_v2"

# (a) What's currently in RippleParameters under this name?
(RippleParameters & {"ripple_param_name": bad_name}).fetch(as_dict=True)

# (b) How many downstream rows reference this name?
affected = RippleTimesV1 & {"ripple_param_name": bad_name}
print(len(affected), "RippleTimesV1 rows have stale provenance")
affected.fetch("KEY", as_dict=True)   # full PK list — keep this
```

Save the `affected.fetch("KEY", as_dict=True)` output — those are the
exact rows you'll need to re-populate. Each key has the
`RippleLFPSelection` PK fields **plus** `ripple_param_name` **plus**
`pos_merge_id` (the projected `PositionOutput` FK at
`ripple/v1/ripple.py:184-186`). You need all three slices to scope a
populate cleanly.

Also walk the descendants to confirm nothing further down has been
populated off these stale ripple times — if you have a downstream
analysis (MUA detection, peri-ripple decoding, etc.) that took these
ripple intervals as input, those rows are *also* now mislabeled and
need to be re-run after the ripple fix:

```python
for child in RippleTimesV1.descendants(as_objects=True):
    n = len(child & {"ripple_param_name": bad_name})
    if n:
        print(child.table_name, n)
```

(Static-source equivalent if you don't have a live session:
`python skills/spyglass/scripts/code_graph.py path --down RippleTimesV1`.)

Stop and read the output before doing anything destructive. If the
counts are larger than you expected, something else is going on and
you should pause.

---

## 2. Pick a recovery path

Two valid options. Pick based on what you actually want the lab's
DB to record going forward.

### Option A — Treat the new threshold as a *new* parameter set (preferred)

This is the cleaner option whenever you want to keep both versions of
the analysis (e.g. for a comparison, or because someone else's
downstream work used the old threshold).

1. **Revert `Kay_ripple_detection_v2` to the original blob** so the
   name keeps matching the existing `RippleTimesV1` rows. You'll need
   the old `speed_threshold` value — get it from a notebook log,
   git, an export, a collaborator's notes, or just rebuild it from
   the Spyglass default at `ripple/v1/ripple.py:150` if your row was
   originally a copy of `"default"`. The blob shape is nested:

   ```python
   # Restore the OLD threshold under the OLD name, so the existing
   # RippleTimesV1 rows are correctly described again.
   RippleParameters().update1({
       "ripple_param_name": "Kay_ripple_detection_v2",
       "ripple_param_dict": {
           "speed_name": "head_speed",
           "ripple_detection_algorithm": "Kay_ripple_detector",
           "ripple_detection_params": {
               "speed_threshold": <OLD_VALUE>,   # the value before your edit
               "minimum_duration": 0.015,
               "zscore_threshold": 2.0,
               "smoothing_sigma": 0.004,
               "close_ripple_threshold": 0.0,
           },
       },
   })
   ```

   `speed_threshold` lives nested inside `ripple_detection_params`,
   not at the top of `ripple_param_dict` (see ripple_pipeline.md and
   the source at `ripple/v1/ripple.py:219-224`). Don't flatten it.

2. **Insert a brand-new params row for the bumped threshold**:

   ```python
   RippleParameters().insert1({
       "ripple_param_name": "Kay_ripple_detection_v2_speedXX",  # new name
       "ripple_param_dict": {
           "speed_name": "head_speed",
           "ripple_detection_algorithm": "Kay_ripple_detector",
           "ripple_detection_params": {
               "speed_threshold": <NEW_VALUE>,   # your bumped value
               "minimum_duration": 0.015,
               "zscore_threshold": 2.0,
               "smoothing_sigma": 0.004,
               "close_ripple_threshold": 0.0,
           },
       },
   })
   ```

3. **Re-populate `RippleTimesV1` against the new name**, scoped to
   the same `(RippleLFPSelection, pos_merge_id)` combinations you
   captured above. `RippleLFPSelection` rows already exist; you only
   need the params name and the position merge IDs to change.
   Build a fully scoped populate key — restricting to
   `{"ripple_param_name": ...}` alone will re-populate against
   *every* eligible upstream combination, which is usually not what
   you want.

   ```python
   for old_key in affected_keys:        # the saved fetch("KEY") list
       new_key = {**old_key, "ripple_param_name":
                  "Kay_ripple_detection_v2_speedXX"}
       RippleTimesV1.populate(new_key, display_progress=True)
   ```

4. The `Kay_ripple_detection_v2` name and its existing
   `RippleTimesV1` rows are now consistent again (old threshold).
   The `..._speedXX` name has the bumped threshold and its own,
   freshly computed `RippleTimesV1` rows. Both are valid; downstream
   analyses can cite whichever is appropriate.

### Option B — Commit to the new threshold; recompute in place

Use this if you don't care about preserving the old-threshold
results and want the existing name to mean the new threshold going
forward.

1. Leave `Kay_ripple_detection_v2` as it is now (with the new
   `speed_threshold`).

2. **Delete** the stale `RippleTimesV1` rows so the populate is forced
   to recompute. Inspect first:

   ```python
   stale = RippleTimesV1 & {"ripple_param_name": bad_name}
   print(len(stale), "rows to delete")
   stale.fetch(as_dict=True, limit=5)
   stale.get_table_storage_usage(human_readable=True)  # disk preview
   ```

   Then, after you've confirmed the count and the rows are what you
   expect, get explicit go-ahead from anyone else who touches this
   data (`.delete()` is `cautious_delete` — it will block on team
   permissions if the sessions belong to another lab member; that
   block is a feature, not a bug to bypass), then:

   ```python
   stale.delete()    # cascades to anything downstream of RippleTimesV1
   ```

   If the cascade hits other people's rows, coordinate with them
   first — don't reach for `super_delete` to silence the
   `PermissionError`.

3. **Re-populate** against the same name. Build the populate key
   from the saved `affected_keys` so you don't accidentally widen
   the scope to other (selection, position) combinations:

   ```python
   for old_key in affected_keys:
       RippleTimesV1.populate(old_key, display_progress=True)
   ```

4. Anything you found in step 1's descendant walk also needs to be
   re-run, in dependency order.

Either path ends with: `RippleParameters[name].ripple_param_dict`
matches the threshold actually used to compute the rows in
`RippleTimesV1[name]`. Verify by spot-checking one ripple-rate or
event-count number against your expectation for the new vs. old
threshold (raising the threshold loosens the immobility filter and
keeps **more** events; lowering tightens it — see
`ripple/v1/ripple.py:219-224` and `ripple_detection/core.py:326-329`).

---

## 3. What's affected vs. unaffected (cascade scope)

For a `RippleParameters` change:

- **New row / mutated row.** In the future, *insert* a new
  `ripple_param_name` instead of mutating an existing one.
  `*Params` tables are PK'd on a name, so a new name is a new row
  and the old name + old downstream rows stay valid and
  interpretable. `update1()` mutates in place and silently
  decouples name-meaning from any already-populated downstream
  rows — which is the bug you're recovering from now.

- **Downstream branches that need re-population (Option A: under the
  new name; Option B: under the same name after deletion).** Just
  one direct branch: `RippleTimesV1`. The same
  `(RippleLFPSelection, pos_merge_id)` combinations you already
  used; selection rows do **not** need re-creating (the change is
  only in the params blob, not the electrode set or the position
  source). If anything *consumes* `RippleTimesV1` downstream
  (a custom analysis, MUA-from-ripples, decoding restricted to
  ripple intervals…), those Computed tables also need to be
  re-populated for the same keys, in dependency order.

- **Unaffected siblings / upstream branches.** Keep them as-is — the
  threshold change does not invalidate any of them:
  - `LFPV1`, `LFPBandV1` (the wideband + ripple-band LFP) — upstream
    of `RippleLFPSelection`; identical inputs.
  - `LFPBandSelection` and `RippleLFPSelection` themselves —
    electrode set is independent of the speed threshold.
  - `TrodesPosV1` / `DLCPosV1` and `PositionOutput` — upstream of
    the ripple PK via `pos_merge_id`; the speed *trace* is the same,
    only the threshold applied to it changed.
  - `SpikeSortingV1`, `CurationV1`, etc. — parallel pipelines, not
    in the ripple FK chain at all.

- **Verify scope yourself** — don't take the list above on faith.
  In a Python session:

  ```python
  # Walk the descendants of the params table to enumerate every
  # table that could be invalidated by the change.
  for d in RippleParameters().descendants(as_objects=True):
      print(d.table_name)
  ```

  Or from the live DB:
  `python skills/spyglass/scripts/db_graph.py path --down RippleParameters`.
  Source-only (no DB session):
  `python skills/spyglass/scripts/code_graph.py path --down RippleParameters`.
  Confirm the union of child tables matches what you re-populated.

---

## 4. What to do differently next time

- **Never `update1()` a `*Params` row when anything downstream has
  been populated against it.** The pattern silently corrupts
  provenance: the row name still resolves to a single param blob,
  but the existing Computed rows were calculated against the *prior*
  blob. DataJoint won't tell you about the mismatch, and `populate()`
  won't re-compute on its own — it sees that a row already exists for
  that key and skips. This applies equally to `RippleParameters`,
  `DecodingParameters`, `MetricParameters`, sorter param tables,
  filter param tables, etc.

- **Default workflow for any parameter change: insert a new
  `*_param_name` row.** Choose a name that encodes what changed
  (e.g. `Kay_ripple_detection_v2_speed10`). Then re-populate the
  Computed table against the new name with a fully-scoped key
  (selection PK + new param name + the relevant position
  `merge_id` for ripples). Old rows under the old name stay intact
  and interpretable — this is exactly what makes Spyglass's
  name-keyed params usable for parameter sweeps and head-to-head
  comparisons.

- **Before any `update1()` on a `*Params` row, verify nothing
  consumes it.** A short check, copy-pasteable:

  ```python
  for child in RippleParameters().descendants(as_objects=True):
      if "ripple_param_name" not in child.heading.names:
          continue
      n = len(child & {"ripple_param_name": "<the_name>"})
      assert n == 0, f"{child.table_name} has {n} rows under this name"
  ```

  If any descendant has rows, do not `update1()` — insert a new
  params row instead.

- **When you do have to delete (Option B), inspect first, get
  confirmation, then delete.** `.delete()` on `SpyglassMixin` is
  `cautious_delete` and will block on team-permission grounds if any
  of the affected sessions are owned by another lab member; that's
  the right behavior — coordinate, don't bypass.

- **If you're sweeping parameters frequently, consider naming
  conventions that encode the diff** (`..._speed4`, `..._speed10`,
  `..._zthr3`). Future-you reading the DB six months later will be
  able to tell which row produced which result without re-reading
  every blob.
