# Animals with PFC recordings AND w-track sessions

This is a compound query that intersects two facts about each subject:

1. They have at least one electrode group whose `BrainRegion` is prefrontal cortex.
2. They have at least one `TaskEpoch` whose linked `Task` is the w-track.

The relevant `spyglass.common` tables (verified in `references/common_tables.md`):

- `Subject` (PK `subject_id`) — animals.
- `Session` (PK `nwb_file_name`, FK to `Subject`) — bridges subjects to per-session tables.
- `ElectrodeGroup` (PK `nwb_file_name`, `electrode_group_name`) — links to `BrainRegion`.
- `Electrode` — same FK to `BrainRegion` via `ElectrodeGroup`.
- `TaskEpoch` (PK `nwb_file_name`, `epoch`, FK to `Task`).
- `Task` (PK `task_name`).
- `BrainRegion` (PK `region_id`, with `region_name`).

## Step 1 — discover the actual category names first

Both "prefrontal cortex" and "w-track" are free-text labels in this DB. **Do not assume** the strings — different labs / ingestions use different conventions (`PFC`, `mPFC`, `prefrontal cortex`, `prelimbic`, `medial prefrontal cortex`; `wtrack`, `w-track`, `w_track`, `WTrack`, `Sun et al W-track`...). Inspect the lookup tables before restricting:

```python
from spyglass.common import BrainRegion, Task

# What region labels exist?
BrainRegion.fetch("region_name", "subregion_name", as_dict=True)

# What task labels exist?
Task.fetch("task_name", as_dict=True)
```

Pick the matching strings (often more than one — e.g. you may need both `"PFC"` and `"mPFC"`). You can also pre-filter with `LIKE`:

```python
BrainRegion & 'region_name LIKE "%refrontal%" OR region_name LIKE "%PFC%"'
Task        & 'task_name  LIKE "%-track%"   OR task_name  LIKE "%track%"'
```

## Step 2 — the compound query

Once you have the matching values, intersect on `subject_id`. The cleanest DataJoint pattern is to compute the two sets of subjects separately, then take their set intersection:

```python
from spyglass.common import (
    Subject, Session, ElectrodeGroup, TaskEpoch, Task, BrainRegion,
)

# Adjust these to whatever Step 1 turned up.
pfc_regions   = BrainRegion & 'region_name LIKE "%refrontal%" OR region_name LIKE "%PFC%"'
wtrack_tasks  = Task        & 'task_name  LIKE "%-track%"'

# Sessions that have at least one PFC electrode group.
sessions_with_pfc = (Session
    & (ElectrodeGroup & pfc_regions))

# Sessions that have at least one w-track epoch.
sessions_with_wtrack = (Session
    & (TaskEpoch & wtrack_tasks))

# Subjects appearing in BOTH.
subjects_pfc    = set(sessions_with_pfc.fetch("subject_id"))
subjects_wtrack = set(sessions_with_wtrack.fetch("subject_id"))

animals = sorted(subjects_pfc & subjects_wtrack)
print(animals)
```

`(Session & (ElectrodeGroup & pfc_regions))` is a DataJoint semijoin: it keeps the `Session` rows for which at least one matching `ElectrodeGroup` row exists. Same shape for `TaskEpoch & wtrack_tasks`. The final Python set-intersection gives you the unique animals.

If you also want to see which sessions per animal qualify on each axis:

```python
# Per-animal: which sessions had PFC AND which had w-track?
for sid in animals:
    pfc_sess    = (sessions_with_pfc    & {"subject_id": sid}).fetch("nwb_file_name")
    wtrack_sess = (sessions_with_wtrack & {"subject_id": sid}).fetch("nwb_file_name")
    print(sid, "PFC:", list(pfc_sess), "wtrack:", list(wtrack_sess))
```

## Step 3 — sanity-check the result

Recommended in the spirit of the skill's "Verify cardinality" / inspect-before-trust directives:

```python
# Does the count look plausible?
print(len(animals), "animals match")

# Spot-check one animal: confirm at least one PFC electrode and at least one wtrack epoch.
sid = animals[0]
print("PFC electrode groups:",
      (ElectrodeGroup & (Session & {"subject_id": sid}) & pfc_regions).fetch(as_dict=True)[:3])
print("wtrack task epochs:",
      (TaskEpoch & (Session & {"subject_id": sid}) & wtrack_tasks).fetch(as_dict=True)[:3])
```

## Notes / caveats

- **"Has PFC recording" vs "has PFC unit / spike-sort / LFP"** — the query above is at the *electrode* layer (the animal had probes targeted at PFC). If you instead want animals where PFC data was actually populated through a downstream pipeline (LFPV1, SpikeSortingV1, etc.), join through the appropriate pipeline's selection table instead of `ElectrodeGroup`. See `references/workflows.md` "Find Data by Brain Region" for the LFP variant — note that LFP keys on `lfp_electrode_group_name`, not `electrode_group_name`, so you must resolve through `LFPElectrodeGroup.LFPElectrode`.
- **`ElectrodeGroup` vs `Electrode`** — `ElectrodeGroup` carries a region FK. `Electrode` also has region info per-channel. Either works; `ElectrodeGroup` is coarser and faster.
- **`Task` vs `TaskEpoch`** — `Task` is the lookup of task definitions; `TaskEpoch` is per-(session, epoch). You restrict `Task` to identify "w-track", and join through `TaskEpoch` to see which sessions actually ran it.
- **Verify before trusting `task_name` / `region_name`** — per the skill's "Do not invent identifiers" directive, run Step 1 in your live session before relying on any specific string. The exact labels are a property of *this* database, not something I can verify from source.
- For deeper graph-based exploration (e.g. confirming that `ElectrodeGroup → BrainRegion` and `TaskEpoch → Task` edges exist as I've described in the runtime DB), you can run `python skills/spyglass/scripts/db_graph.py describe ElectrodeGroup` and `... describe TaskEpoch`.
