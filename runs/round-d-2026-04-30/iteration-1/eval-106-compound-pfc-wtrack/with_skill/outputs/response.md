# Finding animals with PFC recordings AND w-track behavior

Welcome! This is a classic "compound query" — two independent facts (anatomy + behavior) about each session, intersected, then rolled up to the animal level. In Spyglass these live in two separate common tables:

- **Brain region targeting** — `ElectrodeGroup` carries an FK to `BrainRegion`. Each `electrode_group_name` for a session has a `region_name` (the string Spyglass ingested from the NWB `electrode_group.location` field).
- **Behavioral task** — `TaskEpoch` carries an FK to `Task` (PK `task_name`), and also has a secondary `task_environment` attribute. `Task` is just a lookup of names; `TaskEpoch` is the per-session, per-epoch row.

Both tables share the `nwb_file_name` PK with `Session`, and `Session` carries `subject_id` (via FK to `Subject`). So the strategy is: restrict each table independently, take the set of `nwb_file_name`s in each, intersect, then join to `Session` to recover `subject_id`.

## Step 1 — see what brain-region strings actually exist

The biggest gotcha here is that `region_name` is a free-text string ingested from each NWB file. There is no canonical "PFC" enum — different labs/animals may have used `"prefrontal cortex"`, `"PFC"`, `"mPFC"`, `"medial prefrontal cortex"`, `"PrL"`, `"IL"`, etc. **Look first, then write the restriction.**

```python
from spyglass.common import BrainRegion, ElectrodeGroup, Task, TaskEpoch, Session

# What region strings exist in the database?
BrainRegion.fetch("region_name", "subregion_name")
```

Spot the variants that mean PFC for your data. Then, similarly:

```python
# What task names exist?
Task.fetch("task_name")
# And the per-epoch environment strings:
import datajoint as dj
dj.U("task_environment") & TaskEpoch
```

`"w-track"` may be encoded as `task_name = "Sleep"` vs `"W-track"`, or as `task_environment = "wtrack"` / `"w-track"` / `"WTrack"`. Check both fields — different ingest pipelines populate them differently.

## Step 2 — write each restriction with a LIKE filter

Once you know the actual strings, use a wildcard so you catch the variants you saw:

```python
# Sessions that have at least one electrode group targeting PFC.
# Adjust the LIKE pattern to match the strings you saw in Step 1.
pfc_region = BrainRegion & 'region_name LIKE "%refrontal%"'   # case-sensitive in MySQL by default — use %refrontal% to catch "Prefrontal" / "prefrontal"
pfc_groups = ElectrodeGroup & pfc_region
pfc_files = set(pfc_groups.fetch("nwb_file_name"))

# Sessions that have at least one w-track epoch.
# Try task_name first; if empty, also try task_environment.
wtrack_epochs = TaskEpoch & (Task & 'task_name LIKE "%-track%" OR task_name LIKE "%track%"')
wtrack_files_by_task = set(wtrack_epochs.fetch("nwb_file_name"))

wtrack_files_by_env = set((TaskEpoch & 'task_environment LIKE "%track%"').fetch("nwb_file_name"))
wtrack_files = wtrack_files_by_task | wtrack_files_by_env
```

Tighten the `LIKE` patterns once you know the exact spellings — broad patterns are fine while exploring, but narrow them before treating the result as authoritative.

## Step 3 — intersect, then roll up to animals

```python
both_files = pfc_files & wtrack_files                       # set intersection on nwb_file_name
print(f"{len(both_files)} sessions match both criteria")

# Map sessions back to animals via the Session -> Subject FK
animals = (Session & [{"nwb_file_name": f} for f in both_files]).fetch("subject_id")
unique_animals = sorted(set(animals))
print(unique_animals)
```

Or, equivalently, do the whole thing as one DataJoint expression and let the server do the join — useful if you also want to see how many sessions per animal:

```python
import datajoint as dj

pfc_sessions = dj.U("nwb_file_name") & (ElectrodeGroup & (BrainRegion & 'region_name LIKE "%refrontal%"'))
wtrack_sessions = dj.U("nwb_file_name") & (
    (TaskEpoch & (Task & 'task_name LIKE "%track%"'))
    + (TaskEpoch & 'task_environment LIKE "%track%"')   # union via "+" if you need both fields
)
# Sessions in BOTH:
both = pfc_sessions & wtrack_sessions
# Per-animal counts:
((Session.proj("subject_id") & both)
    .fetch(format="frame")
    .groupby("subject_id")
    .size()
    .sort_values(ascending=False))
```

(`dj.U("nwb_file_name")` projects down to just the session key so the intersection is on sessions, not on the cross of electrode groups × epochs. Without it you'd get duplicated rows.)

## A few things to double-check as you go

1. **Don't trust a single spelling.** Even within one lab, `region_name` strings drift across animals. Always run the `BrainRegion.fetch("region_name")` discovery step first.
2. **`region_name` is a secondary attribute on `BrainRegion`, not on `ElectrodeGroup`.** The FK from `ElectrodeGroup` carries only `region_id` — that's why the pattern is `ElectrodeGroup & (BrainRegion & {...})` rather than `ElectrodeGroup & {"region_name": ...}` (which would silently match nothing useful — DataJoint would drop the unknown attr).
3. **`task_environment` lives on `TaskEpoch`, not on `Task`.** Restrict the right table for the field.
4. **One PFC electrode is enough to flag a session.** The query above counts a session as "PFC" if *any* `ElectrodeGroup` targets PFC. If you want a stricter criterion (e.g., ≥ N PFC channels), aggregate over `Electrode` instead of `ElectrodeGroup`.
5. **Print intermediate counts.** `len(pfc_files)`, `len(wtrack_files)`, `len(both_files)` at each step makes it obvious when a `LIKE` pattern is too narrow (zero matches) or too broad (matches non-PFC structures like "orbitofrontal").

## Quick verification commands inside your session

```python
ElectrodeGroup.describe()         # confirm the FK to BrainRegion
TaskEpoch.describe()              # confirm task_name comes via Task FK and task_environment is a secondary attr
Session.heading                   # confirm subject_id is exposed
```

If you hit anything unexpected — empty intersection, surprising region strings, mismatched session counts — share what you find and we can refine the patterns. The discovery step (Step 1) is where most of the real information lives; the rest is mechanical.
