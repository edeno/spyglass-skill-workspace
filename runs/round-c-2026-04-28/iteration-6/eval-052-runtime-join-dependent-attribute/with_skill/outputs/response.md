# `Cannot join query expressions on dependent attribute 'nwb_file_name'`

## What the error means

This is DataJoint's **dependent-attribute refusal**. The rule:

> `A * B` refuses when a shared attribute is **secondary** on *both* sides — not just when it appears in one side.

Why DataJoint refuses: two like-named *secondary* columns reached the two tables via **different FK paths**, so DataJoint can't guarantee they mean the same thing semantically. Rather than silently producing a join whose meaning depends on which path you read, it raises. (One-sided-secondary joins — secondary on one side, primary on the other — are legal; that's the normal `*` over a foreign key.)

Crucially, this fires at **query-build time**, not at fetch. There is no row-level check happening yet. So:

- This is **not** a "no matching rows" / under-restricted problem. Restricting harder won't help.
- `sorting_id` isn't "too loose" — the failure happens before any restriction is consulted. In your expression `SpikeSortingSelection * SpikeSortingRecordingSelection & {'sorting_id': 'abc'}`, `*` binds tighter than `&`, so DataJoint tries to build the `*` first and raises immediately.

## Why it fires on these two tables

`nwb_file_name` is secondary on **both** sides via different FK paths (verified against `src/spyglass/spikesorting/v1/`):

- `SpikeSortingSelection` (`sorting.py:199-207`) — gets `nwb_file_name` (and `interval_list_name`) through `-> IntervalList`.
- `SpikeSortingRecordingSelection` (`recording.py:147-157`) — gets `nwb_file_name` through `-> Raw` and `-> SortGroup`, plus `interval_list_name` through its own `-> IntervalList`.

Two different propagation paths land the same secondary column on each side, so `*` refuses. (`interval_list_name` would refuse for the same reason if `nwb_file_name` weren't there first.)

## Canonical fix — `.proj()` the left side

Project `SpikeSortingSelection` down to its PK plus the one bridging secondary you actually need (`recording_id`). That drops the colliding `nwb_file_name` and `interval_list_name` secondaries before the `*`:

```python
((SpikeSortingSelection & {'sorting_id': 'abc'}).proj('recording_id')
 * SpikeSortingRecordingSelection
 * SortGroup.SortGroupElectrode * Electrode * BrainRegion
).fetch('region_name')
```

After the `.proj`, the only attribute shared with `SpikeSortingRecordingSelection` is `recording_id` — secondary on the (projected) left, **primary** on the right. That's a legal one-sided-secondary join.

Prefer this form: it stays composable in a single expression and is the smallest correct change.

## Debug-friendly alternative — split into two restrictions

If you want to pause and inspect the bridging value mid-debug, fetch it and use it as a restriction so the two tables never appear in the same `*`:

```python
recording_id = (SpikeSortingSelection & {'sorting_id': 'abc'}).fetch1('recording_id')
regions = (SpikeSortingRecordingSelection
           * SortGroup.SortGroupElectrode * Electrode * BrainRegion
           & {'recording_id': recording_id}
          ).fetch('region_name')
```

This is more legible when you want to see `recording_id` and verify it before going downstream, but it loses composability — use `.proj()` as the default; reach for the split when you're actively debugging.

## What *not* to do

- **Don't replace `*` with `&`.** `&` is a restriction, not a join — it would silently change the semantics (no attribute pickup from the right side, just a row filter), not fix the diagnosis.
- **Don't add more PK fields to the restriction** thinking the key is "too loose." The error fires at query-build time, before the restriction is applied. `sorting_id` alone is the full PK of `SpikeSortingSelection`; nothing about the restriction is wrong.
- **Don't reach for a merge-table helper** (`merge_get_part`, etc.). Neither table here is a merge master — this is a plain join collision, not a merge dispatch issue.

## Diagnostic habit for next time

Before recommending or writing a multi-table `*` chain, inspect each side's secondary attributes and look for collisions:

```python
SpikeSortingSelection.heading.secondary_attributes
SpikeSortingRecordingSelection.heading.secondary_attributes
```

Or from the shell, without a Python session:

```bash
python skills/spyglass/scripts/code_graph.py describe SpikeSortingSelection --json
python skills/spyglass/scripts/code_graph.py describe SpikeSortingRecordingSelection --json
```

The two attributes most likely to collide across Spyglass are **`nwb_file_name`** (propagated via `-> Raw`, `-> Session`, `-> IntervalList`, `-> AnalysisNwbfile`, `-> Electrode`) and **`interval_list_name`** (via `-> IntervalList` on any selection table). If a candidate join shares either of those as a secondary on both sides, plan on `.proj()` from the start.

## References

- Full mechanism, both fixes, and the diagnostic habit: [common_mistakes.md § 9](../../../../skills/spyglass/references/common_mistakes.md#9--refuses-to-join-on-a-dependent-attribute).
- Join operator and the dependent-attribute footgun in context: [datajoint_api.md § Join (`*`)](../../../../skills/spyglass/references/datajoint_api.md).
- DataJoint upstream check: `assert_join_compatibility` in `datajoint/condition.py`.
