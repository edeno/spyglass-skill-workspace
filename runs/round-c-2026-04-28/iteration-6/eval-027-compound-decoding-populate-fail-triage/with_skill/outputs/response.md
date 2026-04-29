# Triaging a `fetch1` cardinality failure inside `fetch_position_info`

A `fetch1`-cardinality error from inside `ClusterlessDecodingV1.populate -> fetch_position_info` after re-populating position is almost never a "stale `pos_merge_id`" story. DataJoint enforces the foreign key on `PositionGroup.Position` (`-> PositionOutput.proj(pos_merge_id='merge_id')`, defined at `src/spyglass/decoding/v1/core.py:139-143`), so a `pos_merge_id` row that doesn't exist in `PositionOutput` is not a state the normal `populate` / `cautious_delete` flow can produce. The realistic causes are misalignment between the **decoding selection** and the **position state for the session** — chase those, in this order, before reaching for any delete.

There are several `fetch1`/`fetch1_dataframe` calls inside `fetch_position_info` (`src/spyglass/decoding/v1/core.py:204-225`); any of them can raise. Don't guess which — narrow it down by walking the diagnostic surface.

## Step 1 — Confirm the failing decoding key is fully specified

Look at `ClusterlessDecodingSelection` (`src/spyglass/decoding/v1/clusterless.py:83-91`):

```python
class ClusterlessDecodingSelection(SpyglassMixin, dj.Manual):
    definition = """
    -> UnitWaveformFeaturesGroup
    -> PositionGroup
    -> DecodingParameters
    -> IntervalList.proj(encoding_interval='interval_list_name')
    -> IntervalList.proj(decoding_interval='interval_list_name')
    estimate_decoding_params = 1 : bool # 1 to estimate the decoding parameters
    """
```

There is **no `---` boundary** in this definition, so every line — including the default-valued bool — is part of the primary key. The full PK pulled in transitively is:

- `nwb_file_name` (via both groups)
- `waveform_features_group_name`
- `position_group_name`
- `decoding_param_name`
- `encoding_interval`
- `decoding_interval`
- `estimate_decoding_params` — easy to miss because it has a `= 1` default

A partially-specified key handed to `populate(key)` is the easiest way to land surprising downstream `fetch1` calls. Confirm it explicitly:

```python
print(ClusterlessDecodingSelection.primary_key)         # full PK list
print(len(ClusterlessDecodingSelection & key))          # should be 1
(ClusterlessDecodingSelection & key).fetch1()           # raises if key isn't unique
```

If `len(...)` is >1, your key is missing one of the PK fields above (most often `estimate_decoding_params` after re-creating selection rows). If it's 0, the selection row doesn't exist and `populate(key)` walked everything that the loose dict matched.

## Step 2 — Confirm position is populated for the session at all

Before chasing alignment problems, make sure you didn't end up with a vacuous position state for the session — that's a missing-prereq, not a triage path:

```python
from spyglass.position import PositionOutput

len(PositionOutput.merge_restrict({"nwb_file_name": key["nwb_file_name"]})) > 0
```

If 0, populate position first (TrodesPosV1 / DLCPosV1 -> PositionOutput) and re-do the PositionGroup setup. Note the use of `merge_restrict` rather than `& {"nwb_file_name": ...}` — restricting a merge master with a non-PK dict silently returns the whole table (Common Mistake #6 in SKILL.md / merge_methods.md).

## Step 3 — Inspect what the decoding selection's PositionGroup is reaching for

This is the diagnostic that distinguishes the realistic root causes. Pull the `pos_merge_id`s the selection's `PositionGroup` actually walks, and compare against the live `PositionOutput` set for the session:

```python
from spyglass.decoding import PositionGroup
from spyglass.position import PositionOutput

position_group_key = {
    "nwb_file_name": key["nwb_file_name"],
    "position_group_name": key["position_group_name"],
}

# Confirm the group itself exists and is unique:
print(len(PositionGroup & position_group_key))   # should be 1

# What pos_merge_ids the group's part-table walks (this is what
# fetch_position_info iterates at core.py:209):
reaching_for = (PositionGroup.Position & position_group_key).fetch(
    "pos_merge_id", as_dict=True
)

# What's actually populated for this session:
live_for_session = PositionOutput.merge_restrict(
    {"nwb_file_name": key["nwb_file_name"]}
).fetch("merge_id")
```

Three diagnostic outcomes, each pointing at a different fix:

1. **`reaching_for` ids exist in `PositionOutput` but for a *different* `nwb_file_name`** — wrong `position_group_name` on the decoding selection: the group is bundling position rows from another session. Fix the selection key's `position_group_name` (or rebuild the group with the right rows). Don't touch `PositionOutput`.

2. **`reaching_for` ids match `live_for_session` but the count or content doesn't match what the decoding selection expects** — the `position_group_name` on the failing key is mis-pointed (or the group bundles a different membership than you thought). Inspect what `(PositionGroup.Position & position_group_key)` returns, decide whether the membership is the one you want, and fix the selection's `position_group_name` field — the misalignment lives in `PositionGroup.Position` or in the selection's key, not on `PositionOutput`.

3. **`reaching_for` ids do NOT exist anywhere in `PositionOutput`** — this is the FK-invariant case. The DataJoint foreign key on `PositionGroup.Position` (`-> PositionOutput.proj(pos_merge_id='merge_id')`, `core.py:139-143`) is supposed to make this state unreachable from the normal API. If you see it, the FK was bypassed somehow — `super_delete()` on a `PositionOutput` part, manual SQL, or a mid-transaction abort that left the database inconsistent. **Flag for the lab admin** to audit how the FK got bypassed; don't chase it from the user side, and don't reach for `PositionOutput.delete()` to "clean up" — the wrong reference (if any) lives in `PositionGroup.Position`, and deleting from `PositionOutput` is the wrong layer.

## Step 4 — Check interval compatibility (Signature F)

Even when every `pos_merge_id` resolves and lives in `PositionOutput`, `fetch_position_info` can still produce a downstream `fetch1` cardinality error if the decoding key's `encoding_interval` / `decoding_interval` don't match the `interval_list_name` recorded on the corresponding part rows of `PositionOutput`. This is **Signature F (interval mismatch)** from `runtime_debugging.md` — decoding takes *two* interval fields (`encoding_interval` AND `decoding_interval`, both projections from `IntervalList.interval_list_name` per `clusterless.py:88-89`), and either can desync with what was set when position was re-populated.

Compare the names directly:

```python
for row in reaching_for:
    pid = row["pos_merge_id"]
    # Check whichever part(s) populated this session:
    print(
        pid,
        (PositionOutput.TrodesPosV1 & {"merge_id": pid}).fetch("interval_list_name"),
        # or (PositionOutput.DLCPosV1 & {"merge_id": pid}).fetch("interval_list_name")
    )

# vs:
print(key["encoding_interval"], key["decoding_interval"])

# And confirm the named intervals exist for this session at all:
from spyglass.common import IntervalList
(IntervalList & {"nwb_file_name": key["nwb_file_name"]}).fetch("interval_list_name")
```

Divergence here means the decoding selection's interval names need re-aligning with what's on the position merge entries. Fix it by re-inserting the decoding selection with the correct `encoding_interval` / `decoding_interval`, **not** by deleting position rows.

## What not to do

- **Don't** lead with a "stale `pos_merge_id` from re-populating position" story. DataJoint FK semantics on `PositionGroup.Position` make orphans abnormal — outcome (3) above is an FK invariant violation, not a normal triage path.
- **Don't** call `PositionOutput.delete()` or `PositionOutput.merge_delete(...)` as a fix on the way through this triage. The wrong reference (if any) lives in `PositionGroup.Position` or in the decoding selection's key. Deleting from `PositionOutput` is the wrong layer and may make the diagnostic surface worse (cascading deletes through the FK chain).
- **Don't** restrict a merge master with a friendly `{"nwb_file_name": ...}` — `PositionOutput & {"nwb_file_name": ...}` silently returns the *whole* table because the master's heading only has `merge_id` (Common Mistake #6). Use `PositionOutput.merge_restrict({"nwb_file_name": ...})`.

## Summary of the diagnostic walk

| Step | What you check | What it rules in/out |
| --- | --- | --- |
| 1 | `ClusterlessDecodingSelection.primary_key` vs your `key` (incl. `estimate_decoding_params`) | Under-specified key → `populate(key)` walked the wrong row |
| 2 | `PositionOutput.merge_restrict({nwb_file_name})` non-empty | Missing prereq vs. misalignment |
| 3 | `(PositionGroup.Position & position_group_key).fetch('pos_merge_id')` vs live `PositionOutput` set | Wrong `position_group_name` on selection / mis-pointed group / FK-invariant violation |
| 4 | Per-pos_merge_id `interval_list_name` vs `key['encoding_interval']` / `key['decoding_interval']` | Signature F interval mismatch |

References used: `decoding_pipeline.md` (PositionGroup, ClusterlessDecodingSelection, fetch_position_info shape) and `runtime_debugging.md` Signature A (fetch1 cardinality) and Signature F (interval mismatch).
