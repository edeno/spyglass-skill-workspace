# `DataJointError: Cannot join query expressions on dependent attribute 'nwb_file_name'`

## What the error means

This is a **query-build-time** refusal from DataJoint, not a runtime / "no
matching rows" problem. It fires the moment you write the `*` — before any
restriction is evaluated, before any rows are fetched. So restricting harder
(e.g. tightening `{'sorting_id': 'abc'}`) cannot help; the parser is rejecting
the join expression itself.

The rule, stated precisely:

> `*` (the natural join) refuses to combine two tables when a shared attribute
> is **secondary on both sides**. DataJoint calls such a shared-secondary a
> "dependent attribute" because, on each side, its value depends on (was
> brought in by) some other foreign-key reference. If the same name was
> reached by two different FK paths, DataJoint cannot guarantee the two
> columns mean the same thing, so it refuses rather than silently produce a
> Cartesian/garbage result.

Important nuance: the rule fires **only** when the attribute is secondary
on *both* sides. If `nwb_file_name` is primary on one side (say, in the
upstream `Nwbfile` master) and secondary on the other, `*` is fine. The
asymmetry — "secondary on both" vs. "primary on one" — is the whole rule.

## Why these two tables collide on `nwb_file_name`

Looking at the two definitions in
[`/Users/edeno/Documents/GitHub/spyglass/src/spyglass/spikesorting/v1/sorting.py`](file:///Users/edeno/Documents/GitHub/spyglass/src/spyglass/spikesorting/v1/sorting.py)
and
[`/Users/edeno/Documents/GitHub/spyglass/src/spyglass/spikesorting/v1/recording.py`](file:///Users/edeno/Documents/GitHub/spyglass/src/spyglass/spikesorting/v1/recording.py):

**`SpikeSortingSelection`** (sorting.py:199):
```
sorting_id: uuid
---
-> SpikeSortingRecording
-> SpikeSorterParameters
-> IntervalList                   # brings nwb_file_name + interval_list_name as secondaries
```

**`SpikeSortingRecordingSelection`** (recording.py:147):
```
recording_id: uuid
---
-> Raw                            # brings nwb_file_name as secondary (via Nwbfile)
-> SortGroup                      # also references nwb_file_name
-> IntervalList                   # again references nwb_file_name + interval_list_name
-> SpikeSortingPreprocessingParameters
-> LabTeam
```

On **both** tables `nwb_file_name` arrived as a **secondary** attribute,
through different foreign-key chains:

- on `SpikeSortingSelection`: via `-> IntervalList` (and indirectly via
  `-> SpikeSortingRecording`)
- on `SpikeSortingRecordingSelection`: via `-> Raw`, `-> SortGroup`, and
  `-> IntervalList`

Same name, secondary on both → "dependent attribute" → `*` refuses.
(`interval_list_name` is in the same boat and would be the next collision
if you fixed only `nwb_file_name`.)

## How to fix it

There are two correct fixes. They are **not** equivalent: prefer the first.

### Fix 1 (canonical, composable): `.proj()` one side down to the bridge attribute

Project `SpikeSortingSelection` down to its primary key plus the **single**
attribute you actually need to bridge to `SpikeSortingRecordingSelection`,
namely `recording_id`. That drops `nwb_file_name`/`interval_list_name`
from the left side's heading, so the `*` no longer has a both-secondary
collision:

```python
((SpikeSortingSelection & {'sorting_id': 'abc'}).proj('recording_id')
 * SpikeSortingRecordingSelection).fetch()
```

After the `.proj('recording_id')`, the only attribute shared between the
two sides is `recording_id` — primary on `SpikeSortingRecordingSelection`,
secondary on the projected left. One-sided-secondary joins are legal,
so `*` succeeds and the semantics are exactly "the row of
`SpikeSortingRecordingSelection` referenced by `sorting_id='abc'`".

You can keep chaining downstream tables on this:

```python
((SpikeSortingSelection & {'sorting_id': 'abc'}).proj('recording_id')
 * SpikeSortingRecordingSelection
 * SortGroup.SortGroupElectrode
 * Electrode
 * BrainRegion
).fetch('region_name')
```

### Fix 2 (debug-friendly): split into two restrictions

If you want to pause and inspect the bridge value mid-debug, split the
single `*` into a `fetch1` followed by a separate restriction so the two
tables are never combined with `*`:

```python
recording_id = (SpikeSortingSelection & {'sorting_id': 'abc'}).fetch1('recording_id')
rows = (SpikeSortingRecordingSelection & {'recording_id': recording_id}).fetch()
```

This is great when you're trying to figure out *which* `recording_id` is
implicated, but it doesn't compose: every step downstream needs another
restriction. Use it as a debug move, not as the production form.

### What *not* to do

- **Do not "use `&` instead of `*`."** `&` is restriction, not join — it
  doesn't bring in the right side's attributes at all, so it silently
  changes the query semantics. Different operation, different result.
- **Do not assume `sorting_id` is "too loose"** and try to add more
  restriction. The error fires before any row is matched; the restriction
  isn't the problem.
- **Do not interpret this as "no matching rows."** That would be an empty
  fetch, not a `DataJointError` at query construction.

## Diagnostic habit

Before you write a multi-table `*` chain in Spyglass, peek at each table's
secondary attributes:

```python
SpikeSortingSelection.heading.secondary_attributes
SpikeSortingRecordingSelection.heading.secondary_attributes
```

If `nwb_file_name` (or `interval_list_name`, or any other widely-shared
metadata column) shows up as secondary on more than one of the tables you
are about to `*` together, plan a `.proj(<bridge_pk>)` on one of them up
front. In Spyglass specifically, `nwb_file_name` and `interval_list_name`
are the two attributes that almost always trigger this — they propagate
through `Nwbfile`, `Raw`, `IntervalList`, `SortGroup`, and most selection
tables, so collisions are the rule rather than the exception once you
chain three or more tables.
