# Finding animals with PFC recordings AND w-track behavior

Welcome! This is a great early-stage exploration question. The good news is Spyglass stores both pieces of information in normalized tables, so you can answer it with a single DataJoint join + restriction. Let me walk through what's involved, then give you the query.

## Which tables you need

The recording side (brain region):

- `Session` — one row per ingested NWB file; links each session to a `Subject` (the animal).
- `ElectrodeGroup` — one row per probe/group within a session; carries a `BrainRegion` foreign key.
- `Electrode` — one row per channel; *also* carries a `BrainRegion` foreign key (electrodes can be assigned a region independently of their group, e.g., when one shank crosses a boundary).
- `BrainRegion` — lookup table holding `region_name`, `subregion_name`, `subsubregion_name`.

The behavior side (task):

- `TaskEpoch` — one row per (session, epoch); links the epoch to a `Task` and an `IntervalList`.
- `Task` — lookup table with `task_name`, `task_description`, `task_type`.

The animal:

- `Subject` — `subject_id` is the primary key (and what you typically mean by "animal").

`Session` has `subject_id` as a (nullable) foreign key, so once you've restricted `Session` you can fetch `subject_id` directly.

## A practical caution before you query

PFC and "w-track" are both fuzzy across the database — different ingesters use different spellings. Before writing the final query, **list the distinct values** so you can pick the right ones:

```python
import datajoint as dj
from spyglass.common import (
    Session,
    Subject,
    BrainRegion,
    ElectrodeGroup,
    Electrode,
)
from spyglass.common.common_task import Task, TaskEpoch

# What region names exist? (look for PFC, mPFC, prefrontal cortex, PrL, IL, ACC, etc.)
print(sorted(set(BrainRegion.fetch("region_name"))))

# What task names exist? (look for "w-track", "wtrack", "W-track", "linear track w", etc.)
print(sorted(set(Task.fetch("task_name"))))
```

Common variants you may see:

- PFC: `"prefrontal cortex"`, `"mPFC"`, `"PFC"`, `"PrL"`, `"IL"`, `"OFC"`, `"medial prefrontal cortex"`.
- W-track: `"w-track"`, `"wtrack"`, `"W track"`, sometimes embedded in `task_description` rather than `task_name`.

If the canonical name varies, use a regex restriction (`LIKE`) rather than equality.

## The query

Once you've identified the right strings, the join is straightforward. DataJoint's `&` is restriction (filter), `*` is join, and you can join across foreign keys without naming the join columns explicitly.

```python
# 1. Sessions that have at least one PFC electrode group.
#    Using LIKE to be tolerant of "PFC" / "prefrontal cortex" / "mPFC" etc.
pfc_region = BrainRegion & 'region_name LIKE "%refrontal%"'  # or use exact names you found
pfc_sessions = Session & (ElectrodeGroup & pfc_region)

# 2. Sessions that have at least one w-track task epoch.
wtrack_task = Task & 'task_name LIKE "%-track%" OR task_name LIKE "%track%"'
# Better: pick the exact name(s) you saw, e.g.
# wtrack_task = Task & 'task_name = "Sleep"'  # NO — illustrative
# wtrack_task = Task & 'task_name LIKE "%track%"'
wtrack_sessions = Session & (TaskEpoch & wtrack_task)

# 3. Animals that satisfy BOTH.
animals = dj.U("subject_id") & (pfc_sessions & wtrack_sessions)
animal_list = animals.fetch("subject_id")
print(animal_list)
```

A few notes on what's happening:

- `ElectrodeGroup & pfc_region` is the set of electrode groups in PFC. Restricting `Session` by that subquery keeps only sessions that have at least one PFC group.
- The same pattern with `TaskEpoch & wtrack_task` keeps only sessions where at least one epoch was a w-track epoch.
- Intersecting the two `Session` restrictions (`pfc_sessions & wtrack_sessions`) gives sessions that satisfy both conditions in the *same* session. If you want animals that ever had PFC recordings AND ever ran w-track — even on different days — drop down to subject-level first:

```python
pfc_animals = dj.U("subject_id") & pfc_sessions
wtrack_animals = dj.U("subject_id") & wtrack_sessions
both = pfc_animals & wtrack_animals
print(both.fetch("subject_id"))
```

That's usually the version you want for a "which animals are eligible for this analysis" survey.

- `dj.U("subject_id")` is "project to unique values of subject_id" — it deduplicates across sessions.

## Optional: also check the per-electrode region

`Electrode` has its own `BrainRegion` FK that can differ from the group's. If you want to be extra inclusive (catch sessions where a single channel was labeled PFC even if the group's nominal target was elsewhere):

```python
pfc_via_electrode = Session & (Electrode & pfc_region)
pfc_sessions = pfc_sessions + pfc_via_electrode  # union
```

For most lab use this is overkill — `ElectrodeGroup` is the right granularity.

## Optional: get more context per animal

If you want a table rather than just a list of IDs:

```python
result = (
    Subject
    * (dj.U("subject_id") & (pfc_sessions & wtrack_sessions))
).fetch(format="frame")
print(result)
```

That gives you sex, species, genotype, etc. alongside each `subject_id`.

## What to do next

1. Run the two `fetch` calls under "A practical caution" first to see the actual region and task name strings in your database.
2. Replace the `LIKE` patterns with the exact strings (or a tighter pattern) so you don't accidentally include, say, `"orbitofrontal cortex"` if you only want medial PFC, or `"linear track"` if you only want W-mazes.
3. Spot-check one or two animals from the result: pull their PFC sessions (`Session & {"subject_id": "..."} & (ElectrodeGroup & pfc_region)`) and their w-track epochs (`TaskEpoch & {"subject_id": "..."} & wtrack_task`) and confirm they match your expectation. With a fuzzy term like "PFC", a quick sanity check beats trusting the join blindly.

If anything in the column names or table layout doesn't match what you see locally, `Session.describe()`, `ElectrodeGroup.describe()`, `BrainRegion.describe()`, `Task.describe()`, and `TaskEpoch.describe()` will print the schema so you can confirm.
