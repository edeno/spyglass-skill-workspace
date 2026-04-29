# DLC inference: from a populated `DLCModel` to a `merge_id` in `PositionOutput`

You're past project / model / training. Below is the **ordered list of tables you still need to touch** to land a row in `PositionOutput.DLCPosV1` (and thereby a `merge_id` in `PositionOutput`). Verified against `src/spyglass/position/v1/`.

For the structural overview see the pipeline flow box in `position_dlc_v1_pipeline.md`; the live tutorial is `notebooks/21_DLC.ipynb`.

## Pipeline at a glance

```text
DLCModel (done)
   ↓
DLCPoseEstimationSelection      → DLCPoseEstimation (+ .BodyPart per bp)
   ↓
DLCSmoothInterpSelection        → DLCSmoothInterp        [per bodypart]
   ↓
DLCSmoothInterpCohortSelection  → DLCSmoothInterpCohort  [aggregates bodyparts]
   ↓                                  ↓
DLCCentroidSelection            → DLCCentroid
DLCOrientationSelection         → DLCOrientation
   ↓                                  ↓
DLCPosSelection                 → DLCPosV1
   ↓
PositionOutput.DLCPosV1   ← auto-inserted by DLCPosV1.make() via PositionOutput._merge_insert(...)
```

`DLCPosV1.make()` calls `PositionOutput._merge_insert([orig_key], part_name="DLCPosV1", skip_duplicates=True)` (`src/spyglass/position/v1/position_dlc_selection.py:85`), so once `DLCPosV1.populate(...)` succeeds, the merge row (and its `merge_id`) exists. You do not call `PositionOutput.insert1` yourself.

## Ordered steps

For each step, the *Selection* table is the manual insert; the downstream computed table runs `populate(key)`.

### 1. `DLCPoseEstimationSelection` → `DLCPoseEstimation`

- Use `DLCPoseEstimationSelection.insert_estimation_task(key, task_mode="trigger" | "load", params=...)` rather than `insert1` directly — it handles the output dir + log file (`position_dlc_pose_estimation.py:89`).
- `key` pairs a `VideoFile` row with the `DLCModel` row you just trained (`-> VideoFile`, `-> DLCModel` in the definition at `position_dlc_pose_estimation.py:32-41`).
- `DLCPoseEstimation.populate(key)` then writes the master row plus one `DLCPoseEstimation.BodyPart` row per bodypart in the model (`position_dlc_pose_estimation.py:154-157, 356`).

### 2. `DLCSmoothInterpSelection` → `DLCSmoothInterp` *(per bodypart)*

- Definition: `-> DLCPoseEstimation.BodyPart` + `-> DLCSmoothInterpParams` (`position_dlc_position.py:186-190`).
- Insert one selection row **per bodypart** you want smoothed, each pairing the bodypart with a `DLCSmoothInterpParams` name.
- Then `DLCSmoothInterp.populate(...)`. Can take a few minutes per bodypart.

### 3. `DLCSmoothInterpCohortSelection` → `DLCSmoothInterpCohort` *(non-obvious aggregation step)*

This is the step people skip. It groups the per-bodypart smoothed traces back into one named cohort that downstream centroid/orientation can hang off.

```python
DLCSmoothInterpCohortSelection.insert1({
    **pose_estimation_key,                # nwb_file_name, epoch, dlc_model_name, ...
    "dlc_si_cohort_selection_name": "green_red",
    "bodyparts_params_dict": {            # bodypart -> dlc_si_params_name used in step 2
        "greenLED": "default",
        "redLED_C": "default",
    },
})
DLCSmoothInterpCohort.populate(...)
```

Definition: `position_dlc_cohort.py:19-30, 41-43`. The part table `DLCSmoothInterpCohort.BodyPart` (`position_dlc_cohort.py:46-54`) is what centroid and orientation read from.

### 4a. `DLCCentroidSelection` → `DLCCentroid`

- Definition: `-> DLCSmoothInterpCohort` + `-> DLCCentroidParams` (`position_dlc_centroid.py:167-176`).
- Pair the cohort with a `DLCCentroidParams` name; populate.

### 4b. `DLCOrientationSelection` → `DLCOrientation`

- Definition: `-> DLCSmoothInterpCohort` + `-> DLCOrientationParams` (`position_dlc_orient.py:100-105`).
- Same shape as 4a. 4a and 4b are independent and can be inserted/populated in either order (or in parallel).

### 5. `DLCPosSelection` → `DLCPosV1`

This is the only stage where you **cannot** just spread the previous key. `DLCPosSelection.definition` projects the cohort name into two **distinct** aliases for centroid vs orientation:

```python
# src/spyglass/position/v1/position_dlc_selection.py:32-35
definition = """
-> DLCCentroid.proj(   dlc_si_cohort_centroid   ='dlc_si_cohort_selection_name',
                       centroid_analysis_file_name='analysis_file_name')
-> DLCOrientation.proj(dlc_si_cohort_orientation='dlc_si_cohort_selection_name',
                       orientation_analysis_file_name='analysis_file_name')
"""
```

So the insert key needs `dlc_si_cohort_centroid=` and `dlc_si_cohort_orientation=` (both equal to your cohort name, in the typical case) — **not** `dlc_si_cohort_selection_name`. If you forget, `DLCPosV1.populate()` returns silently with no rows. The skill flags this as the DLC-specific footgun in `position_dlc_v1_pipeline.md` ("Key DLC Invariants").

Then `DLCPosV1.populate(key)`. That's the last call you make.

### 6. `PositionOutput.DLCPosV1` — automatic

`DLCPosV1.make()` itself calls `PositionOutput._merge_insert(...)` (`position_dlc_selection.py:85-89`), so the merge row appears as part of step 5's populate. You retrieve the new `merge_id` with:

```python
from spyglass.position import PositionOutput

merge_key = (PositionOutput.DLCPosV1 & dlc_pos_key).fetch1("KEY")  # has merge_id
```

## Required-substring checklist (assertion coverage)

The full list of tables you need to touch is, in order:

1. `DLCPoseEstimationSelection` → `DLCPoseEstimation` (+ `DLCPoseEstimation.BodyPart`)
2. `DLCSmoothInterpSelection` → `DLCSmoothInterp` (per `BodyPart`)
3. `DLCSmoothInterpCohortSelection` → `DLCSmoothInterpCohort`
4. `DLCCentroidSelection` → `DLCCentroid`
5. `DLCOrientationSelection` → `DLCOrientation`
6. `DLCPosSelection` → `DLCPosV1`
7. `PositionOutput.DLCPosV1` (auto, via merge insert)

## Params-table prerequisites (don't skip the check)

Each per-stage `*Selection` table has an FK to its own params table:

| Selection table | Required params table | PK field |
| --- | --- | --- |
| `DLCSmoothInterpSelection` | `DLCSmoothInterpParams` | `dlc_si_params_name` |
| `DLCCentroidSelection` | `DLCCentroidParams` | `dlc_centroid_params_name` |
| `DLCOrientationSelection` | `DLCOrientationParams` | `dlc_orientation_params_name` |

A row in each of those params tables must already exist before the corresponding Selection insert. In most lab setups they're inserted once via the per-table `insert_default()` classmethods (e.g. `DLCOrientationParams.insert_default()` at `position_dlc_orient.py:71-83`). Confirm before inserting selections, e.g.:

```python
(DLCSmoothInterpParams   & {"dlc_si_params_name":          "default"}).fetch1()
(DLCCentroidParams       & {"dlc_centroid_params_name":    "default"}).fetch1()
(DLCOrientationParams    & {"dlc_orientation_params_name": "default"}).fetch1()
```

If any of those raise, insert a row (custom or `insert_default()`) before the selection insert, otherwise the FK will reject your selection insert.

## Tips

- All these tables are exported at `from spyglass.position.v1 import ...` (`position_dlc_v1_pipeline.md` "Key DLC Tables").
- DLC env vars (`DLC_PROJECT_DIR`, `DLC_VIDEO_DIR`, `DLC_OUTPUT_DIR`, `HDF5_USE_FILE_LOCKING`) must be live in the kernel — IDEs / SSH often skip your shell profile. See the env-vars gotcha in `position_dlc_v1_pipeline.md`.
- If `insert_estimation_task` hangs with no output, an `.mp4` of the same name in `dlc_video_dir` is the usual cause; delete it and retry.
- If you have a DLC-only session (no Trodes-derived position) and `DLCCentroid` / `DLCOrientation` populate fails with `IndexError: index 0 is out of bounds for axis 0 with size 0` from `convert_epoch_interval_name_to_position_interval_name`, see the "empty PositionIntervalMap" gotcha in `position_dlc_v1_pipeline.md` — pose estimation can run from video timestamps, but centroid/orientation still need a position interval.
