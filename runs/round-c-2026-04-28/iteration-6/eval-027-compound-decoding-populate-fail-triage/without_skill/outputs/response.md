# Triaging a `fetch1` cardinality error inside `fetch_position_info()`

A `fetch1` cardinality error means that somewhere inside `fetch_position_info()` a query that the code expects to return exactly one row is returning either zero rows or more than one. Given that you just changed/re-populated some position entries before this happened, the most likely failure modes are about **what the decoding key is pointing at** rather than corruption of `PositionOutput` itself. Here is a triage order.

## 1. Confirm the failing key is fully specified

Before doing anything else, make sure the `key` you handed to `populate()` actually pins down a single decoding selection row. `populate(key)` will happily run with a partial key, and a partial key can fan out into multiple matching rows downstream, which is one easy way to land in `fetch1` cardinality territory.

```python
from spyglass.decoding.v1.clusterless import ClusterlessDecodingSelection

ClusterlessDecodingSelection.primary_key       # what fields must be present?
(ClusterlessDecodingSelection & key).fetch1()  # raises if key is not unique
len(ClusterlessDecodingSelection & key)        # should be exactly 1
```

Walk down the `primary_key` list and confirm every field is present and non-`None` on `key`. The decoding selection's PK includes things like `nwb_file_name`, `waveform_features_group_name`, `position_group_name`, `decoding_param_name`, `encoding_interval`, `decoding_interval`. Watch out for fields that look like they have a default value (e.g. an `estimate_decoding_params` flag): in DataJoint, anything declared *above* the `---` boundary is part of the primary key even when it has a default. If the table definition has no `---` separator at all, then the default-valued line is still PK and you still need to set it explicitly on `key`. A missing PK field is the quickest way to silently match more rows than you intended.

## 2. Confirm `PositionOutput` is populated for this session at all

Before chasing alignment, rule out the trivial "nothing is there" case:

```python
from spyglass.position import PositionOutput

len(PositionOutput.merge_restrict({'nwb_file_name': key['nwb_file_name']})) > 0
```

If this is 0, the fix is "populate position first" — not a triage problem, just a missing prerequisite.

## 3. Compare what the decoding selection's `PositionGroup` is reaching for vs. what is actually live

This is the heart of the diagnosis. The decoding selection points at a `position_group_name`, and that group has a part table (`PositionGroup.Position`) that lists the specific `pos_merge_id`s the decoder will pull from `PositionOutput`. If those merge_ids and the `PositionOutput` rows for this session have drifted apart, `fetch_position_info()` will hit either zero or multiple rows when it tries to resolve them.

```python
from spyglass.decoding.v1.core import PositionGroup
from spyglass.position import PositionOutput

position_group_key = {
    'nwb_file_name':       key['nwb_file_name'],
    'position_group_name': key['position_group_name'],
}

reaching_for = (PositionGroup.Position & position_group_key).fetch(
    'pos_merge_id', as_dict=True
)
live_for_session = PositionOutput.merge_restrict(
    {'nwb_file_name': key['nwb_file_name']}
).fetch('merge_id')
```

Now compare `reaching_for` against `live_for_session` and read off one of three diagnostic outcomes:

- **(i) The merge_ids exist in `PositionOutput`, but for a *different* `nwb_file_name`.** This means the `position_group_name` on the decoding selection is mis-pointed — the group bundles position rows from another session. Fix the decoding selection's `position_group_name` (or rebuild the `PositionGroup` for this session correctly).

- **(ii) The merge_ids match the right session, but the *count* / shape doesn't match what the decoder expects** (e.g., the group bundles two epochs and the decoder expects one, or vice versa). This is again a mis-pointed `position_group_name` on the failing key, or a `PositionGroup` that was assembled incorrectly. Inspect `PositionGroup.Position & position_group_key` directly and confirm it lists the rows you actually want.

- **(iii) Some `pos_merge_id` in `PositionGroup.Position` does *not* exist anywhere in `PositionOutput`.** This is the surprising one and it is *not* a normal triage path. `PositionGroup.Position` declares a foreign key on `PositionOutput` (roughly `-> PositionOutput.proj(pos_merge_id='merge_id')` in `src/spyglass/decoding/v1/core.py`). DataJoint enforces foreign keys, so under normal `populate()` / `cautious_delete()` flow you should not be able to leave `PositionGroup.Position` pointing at a `pos_merge_id` that isn't in `PositionOutput`. If you hit this state, the FK invariant has been bypassed somehow — `super_delete()` on a `PositionOutput` part, raw SQL, an aborted transaction, schema-level oddness. **Flag this for your lab admin** to audit how the FK got bypassed; do not try to fix it from the user side by deleting things.

This is also why I would *not* lead with a "stale `pos_merge_id` from re-populating position" story. DataJoint's FK semantics on `PositionGroup.Position` mean that "stale" reference is supposed to be impossible without admin-level intervention. The realistic causes after re-populating position are (i) and (ii) — the decoding selection or its `PositionGroup` is pointing at the wrong slice of position state — not orphans on `PositionOutput`.

## 4. Check interval-list compatibility (a sub-case of the same triage)

Even when every `pos_merge_id` resolves and lives in `PositionOutput`, `fetch_position_info()` can still hit a `fetch1` cardinality error if the decoding key's `encoding_interval` / `decoding_interval` don't line up with the `interval_list_name` recorded on the corresponding `PositionOutput.TrodesPosV1` / `.DLCPosV1` part rows. This is an **interval mismatch** — the position part-row says one interval, the decoding key asks for another, and the join inside `fetch_position_info` falls off the rails.

```python
from spyglass.position import PositionOutput

for pos_merge_id in reaching_for:
    print(
        (PositionOutput.TrodesPosV1 & pos_merge_id).fetch('interval_list_name'),
        # or .DLCPosV1 if that is the upstream source
    )

print(key['encoding_interval'], key['decoding_interval'])
```

If the interval names disagree, the fix is to align the decoding selection's interval names with what is actually recorded on the position merge entries. Don't fix this by deleting position rows — the misalignment lives on the decoding selection key (or on the `IntervalList` you handed it), not on `PositionOutput`.

## What *not* to do

- **Don't reach for `PositionOutput.delete()` or `merge_delete` as a first move.** The wrong reference (if any) lives in `PositionGroup.Position` or in the decoding selection's `key` — `PositionOutput` is downstream of the misalignment, and deleting from it will at best churn upstream tables and at worst make the diagnostic surface harder to read.
- **Don't assume orphaned `pos_merge_id`s are the cause** just because you re-populated position. The foreign key on `PositionGroup.Position -> PositionOutput` makes that abnormal, not the default outcome of a re-populate. If you do find orphans (outcome iii above), that is a database-state problem to escalate, not a user-fixable triage path.
- **Don't bypass the FK with `super_delete()` to "clean up"** while triaging — that is what creates outcome (iii) in the first place.

## Quick checklist

1. `ClusterlessDecodingSelection.primary_key` — is every PK field present on `key`? Watch for default-valued PK fields (e.g. an `estimate_decoding_params` bool).
2. `len(PositionOutput.merge_restrict({'nwb_file_name': ...})) > 0` — is position there at all?
3. `(PositionGroup.Position & position_group_key).fetch('pos_merge_id', as_dict=True)` vs. live `PositionOutput.merge_restrict(...)` — which of (i), (ii), (iii) above?
4. Compare `interval_list_name` on the position part-row to `key['encoding_interval']` / `key['decoding_interval']` — interval mismatch?

That walk should land you on the actual misalignment, which will almost certainly be on the decoding selection's key or its `PositionGroup`, not on `PositionOutput`.
