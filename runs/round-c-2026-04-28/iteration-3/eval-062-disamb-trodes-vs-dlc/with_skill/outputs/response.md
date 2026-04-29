# Trodes vs DLC — which position pipeline?

**Short answer:** you don't have to pick. Trodes and DLC each feed their own part table under the `PositionOutput` merge master, and both can coexist on the same session as separate entries. The right *primary* choice depends on what your downstream analysis needs (a single centroid+orientation track vs. per-bodypart pose) and what your setup cost / compute budget can absorb.

## What each pipeline actually is

Both pipelines end at the same merge layer, `spyglass.position.PositionOutput`, but as different part tables:

| Pipeline | Part table | Source |
| --- | --- | --- |
| Trodes (LED) | `PositionOutput.TrodesPosV1` | `TrodesPosV1` in `spyglass.position.v1.position_trodes_position` |
| DeepLabCut | `PositionOutput.DLCPosV1` | `DLCPosV1` in `spyglass.position.v1.position_dlc_selection` |

Both `make()` handlers explicitly call `PositionOutput._merge_insert(...)` (`position/v1/position_trodes_position.py:241`, `position/v1/position_dlc_selection.py:85`), so when populate succeeds, each one auto-surfaces a row under its corresponding part table.

- **`TrodesPosV1` (Trodes / LED-based).** Reads the headstage-LED positions that SpikeGadgets/Trodes already extracted into `RawPosition`, smooths and computes velocity, and produces a single track. Pipeline shape is the standard 3-step: `TrodesPosParams` → `TrodesPosSelection` → `TrodesPosV1.populate()`. Output columns: `position_x`, `position_y`, `orientation`, `velocity_x`, `velocity_y`, `speed`.
- **`DLCPosV1` (DeepLabCut / pose estimation).** Runs a trained DLC model on the top-down video to label bodyparts (e.g. greenLED/redLED, or nose/ears/tailbase, depending on what the model was trained for), then composes them into a centroid + orientation track. Pipeline shape is the long DLC chain: `DLCProject → DLCModelSource → DLCModelSelection → DLCModel → DLCPoseEstimationSelection → DLCPoseEstimation → DLCSmoothInterp (per bodypart) → DLCSmoothInterpCohort → DLCCentroid + DLCOrientation → DLCPosSelection → DLCPosV1`. Same `position_x/position_y/orientation/velocity_x/velocity_y/speed` columns at the merge layer, plus per-bodypart pose accessible via `PositionOutput.fetch_pose_dataframe(...)`.

## They coexist — picking one does not preclude the other

`PositionOutput` is a DataJoint merge master keyed only by `merge_id` (UUID). Its parts (`PositionOutput.TrodesPosV1`, `PositionOutput.DLCPosV1`, plus `CommonPos` and `ImportedPose`) are independent. For the same `(nwb_file_name, interval_list_name)`, you can populate Trodes *and* DLC and end up with two distinct merge rows on the session — one per source. Downstream queries pick whichever part table they want via `merge_get_part(key)` / `merge_restrict(...)`.

This is useful in practice: many labs run Trodes as a quick "always available" track, then run DLC on top when the analysis needs more.

## Decision logic

Choose Trodes when:

- You only need centroid + orientation (e.g. linearization on a track, decoding spatial position).
- Setup cost matters — Trodes is the simpler 3-step pipeline; no model to train, no GPU required for `populate`.
- LEDs were visible and reliable for the session (no occlusion by shielding cap, no LEDs out of frame, no high-reflectance environment that confuses the LED tracker).
- Latency / iteration speed matters — Trodes populate is much faster than the DLC chain.

Choose DLC when:

- You need pose granularity beyond head centroid: nose vs. ears vs. tail base, body axis from the trunk, head-direction independent of running direction, etc. The `DLCSmoothInterpCohort` step is what lets you mix and match bodyparts; Trodes has no equivalent.
- LED tracking is unreliable for this session (occluded, dropped, swapped colors mid-recording, animal grooming the headstage, etc.).
- Behavior is naturalistic and your science cares about non-running postures (rearing, freezing, grooming) — DLC sees the body, the LEDs only see the head.
- You're willing to pay the setup cost: train a DLC model on labeled frames, manage `DLC_PROJECT_DIR` / `DLC_VIDEO_DIR` / `DLC_OUTPUT_DIR`, and run a heavier (often GPU) populate.

Both at once is reasonable when:

- You want Trodes as a sanity-check baseline against DLC's centroid (great for catching DLC model failures).
- Some downstream analyses want bodyparts (DLC) and others just want a track (Trodes), and you don't want to special-case fetches.

## Match the choice to the downstream consumer

- **Decoding / linearization / simple "where was the rat":** centroid + orientation is enough — Trodes is sufficient and cheaper. DLC also works (same merge columns), it's just overkill if you don't need bodyparts.
- **Behavior segmentation, pose-aware analysis, head-direction independent of running, anything that asks about a specific bodypart:** DLC is required. The per-bodypart cohort step (`DLCSmoothInterpCohort`) and `PositionOutput.fetch_pose_dataframe(...)` only exist on the DLC side.
- **Mixed:** populate both, then route each downstream consumer to the right `merge_id` via `PositionOutput.merge_get_part({...}, multi_source=True)`.

## How to pick the right merge entry once both exist

```python
from spyglass.position import PositionOutput

# Both Trodes and DLC entries for this session, if both have been populated:
PositionOutput.merge_get_part(
    {"nwb_file_name": nwb_file},
    multi_source=True,
)

# A specific source's row (Trodes shown; same shape for DLC with its keys):
trodes_merge_key = PositionOutput.merge_get_part({
    "nwb_file_name": nwb_file,
    "interval_list_name": "pos 1 valid times",
    "trodes_pos_params_name": "default",
}).fetch1("KEY")

trodes_df = (PositionOutput & trodes_merge_key).fetch1_dataframe()
# columns: position_x, position_y, orientation, velocity_x, velocity_y, speed

# Per-bodypart pose only exists on the DLC side:
dlc_pose_df = (PositionOutput & dlc_merge_key).fetch_pose_dataframe()
```

For the full workflows, see `21_DLC.ipynb` (DLC) and `20_Position_Trodes.ipynb` (Trodes); the v1 source modules are `spyglass.position.v1.position_trodes_position` and `spyglass.position.v1.position_dlc_selection`.
