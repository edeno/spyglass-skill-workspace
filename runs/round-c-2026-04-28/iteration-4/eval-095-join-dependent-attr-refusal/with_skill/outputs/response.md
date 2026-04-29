# Why your join is empty (or refusing) — `interval_list_name` is a dependent attribute on both sides

Short answer: **don't try to join `SpikeSortingSelection * SpikeSortingRecordingSelection` on `interval_list_name`.** That attribute is a *secondary* (dependent) attribute on **both** tables, and they reach it via **different foreign-key paths**, so DataJoint cannot treat them as the same column. Depending on exactly how you wrote the query, you'll see one of two failure shapes:

1. `SpikeSortingSelection * SpikeSortingRecordingSelection` — DataJoint raises
   `DataJointError: Cannot join query expressions on dependent attribute 'interval_list_name'`
   at query-build time (no rows fetched yet). If you've masked this with a `try/except` or it's surfacing as "no results" inside a wrapper, that's the real underlying error.
2. A hand-rolled workaround like `SpikeSortingSelection & (SpikeSortingRecordingSelection & {"interval_list_name": x}).proj()` — runs but **returns empty**, because the two `interval_list_name` columns are not semantically the same row identity. They name the same *interval string*, but they were inherited through different parent paths and the join surface DataJoint actually has between these two tables is `recording_id`, not `interval_list_name`.

Either way, `interval_list_name` is the wrong key.

## Why both columns exist but can't be joined

Per the v1 source:

- `SpikeSortingSelection` carries `nwb_file_name` and `interval_list_name` as secondaries via `-> IntervalList` (`src/spyglass/spikesorting/v1/sorting.py:199-207`).
- `SpikeSortingRecordingSelection` carries them as secondaries via `-> Raw` and `-> SortGroup` (`src/spyglass/spikesorting/v1/recording.py:147-157`).

DataJoint's rule (enforced in `datajoint/condition.py assert_join_compatibility`): a `*` join is only legal on attributes that are primary on at least one side. Two like-named secondaries reached via different FK paths could mean different things, so DataJoint refuses rather than silently producing a semantically-unsafe join.

The actual link between these two tables is `recording_id`: it's the primary key of `SpikeSortingRecordingSelection` and a secondary on `SpikeSortingSelection` (because `SpikeSortingSelection -> SpikeSortingRecording`, which itself depends on `SpikeSortingRecordingSelection`). One-sided-secondary joins are legal, so `recording_id` is the join column you actually want.

## What you should do instead

You said the goal is "find sortings whose recording covered a specific interval." The clean shape is:

1. Restrict `SpikeSortingRecordingSelection` by `interval_list_name` (and `nwb_file_name`, since intervals are per-session — see Common Mistake #2: `interval_list_name` alone is rarely unique).
2. Bridge to `SpikeSortingSelection` via `recording_id`.

```python
from spyglass.spikesorting.v1 import (
    SpikeSortingSelection,
    SpikeSortingRecordingSelection,
)

recording_keys = (
    SpikeSortingRecordingSelection
    & {"nwb_file_name": nwb_file, "interval_list_name": "02_r1"}
).fetch("KEY")  # list of {recording_id: ...}

sortings = SpikeSortingSelection & recording_keys
print(len(sortings))
sortings.fetch(as_dict=True)
```

`recording_id` is primary on the right and secondary on the left, so the implicit restriction-by-table works without tripping the dependent-attribute rule. If you want it as a single expression instead of two steps, use `.proj()` on the recording side to keep only its PK before joining:

```python
(
    SpikeSortingSelection
    * (SpikeSortingRecordingSelection
       & {"nwb_file_name": nwb_file, "interval_list_name": "02_r1"}
      ).proj()  # keeps only recording_id
).fetch(as_dict=True)
```

## Diagnostic habit for next time

Before writing any `A * B` chain across Spyglass selection / recording tables, look at each side's secondary attributes:

```python
SpikeSortingSelection.heading.secondary_attributes
SpikeSortingRecordingSelection.heading.secondary_attributes
```

If a non-PK attribute appears on **both** sides, that attribute is *not* a valid join key — `.proj()` it away on one side, or split into two restrictions. The two attributes in Spyglass most likely to collide this way are `nwb_file_name` (propagated through `-> Raw`, `-> Session`, `-> IntervalList`, `-> AnalysisNwbfile`, `-> Electrode`) and `interval_list_name` (through `-> IntervalList` on any selection table).

## Sanity check before trusting "no overlap"

If after using the correct join you still get zero rows, the issue isn't the join syntax — it's whether the rows actually exist. Worth confirming:

- `len(SpikeSortingRecordingSelection & {"nwb_file_name": nwb_file, "interval_list_name": "02_r1"})` — is there a recording selection row for that exact interval string? Interval names are case- and prefix-sensitive (`"02_r1"` vs `"02_r1_"` vs `"r1"`); `IntervalList & {"nwb_file_name": nwb_file}` will list the canonical names.
- `len(SpikeSortingSelection & recording_keys)` — does any sorting selection point at those `recording_id`s? It's perfectly possible to have a recording configured but no sorting selected on it.

Sources cited:
- `/Users/edeno/Documents/GitHub/spyglass-skill/skills/spyglass/references/datajoint_api.md` — "Footgun — dependent-attribute refusal" under `*` join.
- `/Users/edeno/Documents/GitHub/spyglass-skill/skills/spyglass/references/common_mistakes.md` § 9 — full mechanism + canonical Spyglass trigger (this exact pair of tables).
- Spyglass source: `src/spyglass/spikesorting/v1/sorting.py:199-207`, `src/spyglass/spikesorting/v1/recording.py:147-157`.
