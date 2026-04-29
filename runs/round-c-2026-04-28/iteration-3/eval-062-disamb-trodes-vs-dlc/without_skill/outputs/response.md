# Trodes vs. DLC: which position pipeline?

Short answer: in Spyglass you don't have to pick exclusively — both pipelines
land in the same downstream merge table (`PositionOutput`) as separate
part-table entries, so a single session can carry both a Trodes-LED-derived
position and a DLC-derived position side by side. Use Trodes when the LEDs
are visible and you only need centroid/orientation; use DLC when you need
multi-bodypart pose, robustness to LED dropouts, or higher accuracy on
natural behavior.

## What the two pipelines actually are

- **`TrodesPosV1`** (`spyglass.position.v1.position_trodes_position`) — the
  SpikeGadgets / Trodes online tracking path. It consumes the LED centroids
  emitted by Trodes from the overhead camera (the red/green headstage LEDs)
  and turns them into `position`, `orientation`, `velocity` for the
  animal. It's essentially "use the tracking the acquisition system already
  did," with smoothing and unit conversion on top.

- **`DLCPosV1`** (`spyglass.position.v1.position_dlc_selection`) — the
  DeepLabCut pose-estimation path. It runs a trained DLC model on the raw
  video, gets per-frame coordinates for each labeled bodypart, and then
  passes the per-bodypart estimates through a cohort step
  (`position_dlc_cohort`), centroid step (`position_dlc_centroid`), and
  orientation step (`position_dlc_orient`) before producing a final
  `position` / `orientation` time series.

Both terminate in `spyglass.position.position_merge.PositionOutput`:

- `PositionOutput.TrodesPosV1` — part table for Trodes-derived results.
- `PositionOutput.DLCPosV1`   — part table for DLC-derived results.

Anything downstream that needs "the animal's position" (linearization,
ripple detection gated on speed, decoding, place-field maps, …) reads from
`PositionOutput`, so both sources are first-class citizens.

## Decision logic

You said you have *both* headstage LEDs and a top-down camera with trained
DLC models. That puts you in the "either is technically possible" zone.
Pick along these axes:

| Dimension | TrodesPosV1 (LED) | DLCPosV1 (DLC) |
|---|---|---|
| **Setup cost** | Effectively free — Trodes already produced the centroids during acquisition. | Train / curate a DLC model, run inference, manage the model + project tables. |
| **Compute** | Light (smoothing + conversion). | GPU-heavy inference pass over the whole video, then cohort / centroid / orientation. |
| **What it tracks** | Two LED points (front/back of headstage) → centroid + head direction. | Arbitrary set of bodyparts (nose, ears, shoulders, tail base, …) → richer pose. |
| **Robustness** | Fragile when LEDs are occluded (under shelter, headstage tilted, glare, low light). Bad samples become NaNs/dropouts you have to interpolate. | Robust as long as the model generalizes; can label the body even when LEDs are off-screen. |
| **Accuracy on natural behavior** | Good when LEDs are clean; head direction comes "for free" from the two-LED geometry. | Generally more accurate, especially for orientation derived from body axis vs. just the headstage rig. |
| **Latency to first analysis** | Immediately available. | Wait for inference + curation. |
| **Bodypart granularity** | None — you only have the LED pair. | Yes — the cohort step lets you keep individual bodyparts (e.g. nose vs. tail-base) for downstream analyses. |

### Practical recipe

1. **Default to Trodes if it's clean.** If the LEDs are visible across the
   full session and your downstream analysis only needs centroid +
   orientation (decoding, linearized track position, speed-gated ripple
   detection), `TrodesPosV1` → `PositionOutput.TrodesPosV1` is the
   cheapest, most reproducible choice.

2. **Use DLC when you need pose, not just position.** If your analysis
   cares about which bodypart is where (sniffing, rearing, reaching, head
   vs. body angle, tail-base for trajectory smoothing), populate
   `DLCPosV1` and consume `PositionOutput.DLCPosV1`. The DLC cohort step
   is the part of the pipeline that lets you keep specific bodyparts.

3. **Use DLC as a fallback when LEDs fail.** If your Trodes tracking has
   substantial dropouts (occlusions, dim sessions, headstage geometry
   issues), the DLC model can recover position from the body itself.

4. **Populate both when in doubt.** Because they land as different part
   tables in the same merge, you can have both
   `PositionOutput.TrodesPosV1` and `PositionOutput.DLCPosV1` for the same
   session and choose at analysis time. They don't conflict — each
   downstream consumer picks one merge entry by `merge_id`.

5. **Match the choice to the downstream consumer.** Decoding pipelines
   (clusterless / sorted-spikes) just want a single position +
   orientation time series; either pipeline supplies that. Pose-aware
   analyses (e.g. behavior segmentation, head-direction tuning derived
   from the body axis rather than the LED pair) require DLC.

## TL;DR

- `TrodesPosV1` = LED tracking, cheap, fast, fragile to occlusion, no
  bodypart granularity.
- `DLCPosV1` = DeepLabCut pose, expensive, accurate, multi-bodypart,
  robust to LED loss.
- They coexist as `PositionOutput.TrodesPosV1` and
  `PositionOutput.DLCPosV1` part-table entries on the same session — pick
  per downstream analysis, and populate both when you want the option.
