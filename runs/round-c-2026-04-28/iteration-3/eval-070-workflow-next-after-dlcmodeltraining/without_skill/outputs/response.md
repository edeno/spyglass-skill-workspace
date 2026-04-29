# From a trained DLC model to a `PositionOutput` merge_id

Once `DLCModel` has a row, the rest of the v1 DLC pipeline is a chain of
`Selection` (manual insert) → `Computed` (`.populate()`) pairs, ending with a
final insert into the `PositionOutput` merge table. Here is the ordered list
of tables you still need to touch, with what you do at each one.

The schema lives under `spyglass.position.v1` (one Python module per stage).

## The chain

1. **`DLCPoseEstimationSelection`** (manual)
   Pair the trained `DLCModel` with the video / epoch you want pose for.
   There's a helper `DLCPoseEstimationSelection.insert_estimation_task(...)`
   that builds the row for you (it also figures out the output dir).

2. **`DLCPoseEstimation`** (computed) → `.populate()`
   Runs DeepLabCut inference. Writes one row per (selection key) into the
   master, plus one row per tracked bodypart into the part table
   **`DLCPoseEstimation.BodyPart`** (the per-bodypart h5 traces).

3. **`DLCSmoothInterpSelection`** (manual, **per BodyPart**)
   For each bodypart you want to use downstream, insert a row that joins the
   `DLCPoseEstimation.BodyPart` key with a `DLCSmoothInterpParams` row
   (the smoothing / interpolation hyperparameters — usually the lab's
   `'default'` row inserted via `insert_default()`).

4. **`DLCSmoothInterp`** (computed) → `.populate()`
   Smooths and interpolates each per-bodypart trace independently. You'll
   get one row per (epoch, bodypart, smooth_interp_params).

5. **`DLCSmoothInterpCohortSelection`** (manual) — *the easy step to miss*
   This is the **bodypart-aggregation step**. You give the cohort a name
   (`dlc_si_cohort_selection_name`) and a `bodyparts_params_dict` listing
   *which* bodyparts (and which params per bodypart) belong to this cohort.
   Without this row, downstream centroid/orientation have nothing to bind
   to — they don't FK back to individual bodyparts, they FK to a cohort.

6. **`DLCSmoothInterpCohort`** (computed) → `.populate()`
   Materializes the cohort. The part table `DLCSmoothInterpCohort.BodyPart`
   pins down the specific `DLCSmoothInterp` rows that make up the cohort.

7. **`DLCCentroidSelection`** (manual)
   Joins a `DLCSmoothInterpCohort` row with a `DLCCentroidParams` row
   (e.g., `'four_led_centroid'`, `'two_led_centroid'`, `'one_led_centroid'`,
   typically already in the params table via `insert_default()`).

8. **`DLCCentroid`** (computed) → `.populate()`
   Computes the centroid (and velocity) from the cohort's bodyparts.

9. **`DLCOrientationSelection`** (manual)
   Same pattern: cohort + a `DLCOrientationParams` row.

10. **`DLCOrientation`** (computed) → `.populate()`
    Computes head/body orientation from the same cohort.

11. **`DLCPosSelection`** (manual)
    Combines a specific `DLCCentroid` row with a specific `DLCOrientation`
    row. **Footgun:** look at the definition
    (`src/spyglass/position/v1/position_dlc_selection.py:32-35`):

    ```
    -> DLCCentroid.proj(dlc_si_cohort_centroid='dlc_si_cohort_selection_name', ...)
    -> DLCOrientation.proj(dlc_si_cohort_orientation='dlc_si_cohort_selection_name', ...)
    ```

    The single cohort name is **renamed to two separate aliases** —
    `dlc_si_cohort_centroid` and `dlc_si_cohort_orientation`. They can be
    different cohorts in principle, but in practice you almost always want
    them to be the same string. If your insert dict still has
    `dlc_si_cohort_selection_name`, the insert will fail because that
    field name no longer exists at this level — you have to use the two
    aliases.

12. **`DLCPosV1`** (computed) → `.populate()`
    Builds the analysis NWB file with `position`, `orientation`, and
    `velocity` objects, and (per its `make()`) **also inserts the key into
    `PositionOutput` via the `PositionOutput.DLCPosV1` part table**. So in
    practice step 13 below is done *for* you by `DLCPosV1.make`; you don't
    have to insert into the merge table by hand.

13. **`PositionOutput.DLCPosV1`** (merge part table)
    The `merge_id` you wanted lives here. Fetch it with the standard merge
    pattern, e.g.:

    ```python
    from spyglass.position import PositionOutput
    merge_key = (PositionOutput.DLCPosV1 & your_dlc_pos_v1_key).fetch1("KEY")
    merge_id  = merge_key["merge_id"]
    ```

## Compact summary

```
DLCModel (already done)
   ↓
DLCPoseEstimationSelection  →  DLCPoseEstimation  (.BodyPart per bodypart)
   ↓ (per bodypart)
DLCSmoothInterpSelection    →  DLCSmoothInterp
   ↓ (aggregate bodyparts)
DLCSmoothInterpCohortSelection → DLCSmoothInterpCohort
   ↓                                 ↓
DLCCentroidSelection         DLCOrientationSelection
   ↓                                 ↓
DLCCentroid                  DLCOrientation
   ↘                              ↙
       DLCPosSelection
            ↓
        DLCPosV1   ──(auto-insert)──►  PositionOutput.DLCPosV1   ⇒ merge_id
```

## Three params tables you don't "touch" but must exist

Each per-stage `Selection` table FKs to its own params table. Confirm the
default rows are there before each selection insert (or insert custom rows):

- `DLCSmoothInterpParams` — feeds `DLCSmoothInterpSelection`
- `DLCCentroidParams` — feeds `DLCCentroidSelection`
- `DLCOrientationParams` — feeds `DLCOrientationSelection`

A quick check:

```python
from spyglass.position.v1 import (
    DLCSmoothInterpParams, DLCCentroidParams, DLCOrientationParams,
)
(DLCSmoothInterpParams & {"dlc_si_params_name": "default"}).fetch1()
(DLCCentroidParams      & {"dlc_centroid_params_name": "default"}).fetch1()
(DLCOrientationParams   & {"dlc_orientation_params_name": "default"}).fetch1()
```

Most labs already have a `'default'` row in each via `insert_default()`;
if any of those `fetch1` calls raise, insert a row before the matching
selection step.

## Things people typically forget

- **The cohort step (5–6)**. Centroid and orientation operate on a
  *cohort* of bodyparts, not on individual bodyparts. Newcomers often try
  to go `DLCSmoothInterp → DLCCentroidSelection` directly and can't figure
  out the FK error.
- **The aliases on `DLCPosSelection`** (the rename in the definition above).
  Build your insert dict from
  `(DLCCentroid & key).fetch1("KEY")` and
  `(DLCOrientation & key).fetch1("KEY")` and rename
  `dlc_si_cohort_selection_name` to the two aliases — don't hand-construct.
- **You do not insert into `PositionOutput` yourself.** `DLCPosV1.make()`
  inserts the merge row as part of populate. Calling
  `PositionOutput.insert1(...)` on top of that will error.
