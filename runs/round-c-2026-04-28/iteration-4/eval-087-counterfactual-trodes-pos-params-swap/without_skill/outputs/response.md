# Counterfactual: swapping `trodes_pos_params_name` from `default` to `default_smooth_50`

## Short answer

`trodes_pos_params_name` is part of the **primary key** of `TrodesPosSelection` (it points at a row in `TrodesPosParams`). Changing it doesn't *modify* an existing row in place — DataJoint primary keys are immutable. What you actually do is **insert a new selection row** with the new params name (and the same `nwb_file_name`, `interval_list_name`, etc.) and re-`populate()`. That gives you a parallel set of downstream rows that coexist with the old `default` rows.

Concretely, the rows that *differ* (i.e., are new and carry different numerical values) are everything in the position pipeline keyed on `trodes_pos_params_name`, plus anything merged or decoded from them.

## The chain that gets new rows

For the Trodes branch (`spyglass.position.v1.position_trodes_position`):

1. **`TrodesPosSelection`** — new row with `trodes_pos_params_name="default_smooth_50"`. The old `default` row is still there.
2. **`TrodesPosV1`** — `make()` re-runs `_upstream_smoothing` / Trodes-style position computation with the new params (different smoothing kernel / window — `default_smooth_50` typically means a 50-sample (or 50 ms, depending on params definition) Gaussian/boxcar smoothing applied to head position and head orientation before velocity is computed). New row in `TrodesPosV1` with different values in its analysis NWB file:
   - smoothed `head_position` (x, y)
   - smoothed `head_orientation`
   - `head_velocity` (derivative of smoothed position — this changes a lot, since velocity is the noisiest quantity and is what smoothing is usually intended to fix)
   - `head_speed`
3. **`PositionOutput` merge table** (`spyglass.position.position_merge.PositionOutput`) — `TrodesPosV1` is a part-table source for `PositionOutput`. Re-populating inserts a **new `merge_id`** in `PositionOutput` whose part-row points at the new `TrodesPosV1` key. Old `merge_id` for the `default` run is untouched.

So the unit of "differs" downstream is **a new `merge_id` in `PositionOutput`**, not a mutation of the old one.

## What inherits from `PositionOutput` and therefore gets new rows if you re-run them

Anything that takes a `PositionOutput` `merge_id` as part of its key needs to be re-selected and re-populated against the new `merge_id`. Common consumers:

- **`PositionVideo`** — overlay videos rendered against position; will look smoother.
- **Linearization**: `IntervalLinearizedPosition` / `LinearizedPositionV1` (and its `LinearizedPositionOutput` merge table). Linearization snaps 2-D position to a track graph; smoothing changes the linearized trace, especially around track-segment transitions.
- **Decoding**:
  - `ClusterlessDecodingV1` — selection takes a `position_merge_id`. New row needed.
  - `SortedSpikesDecodingV1` — same.
  - Any state-space / clusterless / sorted decoding output downstream (posteriors, state probabilities, MAP estimates) will differ — these depend on speed for encoding-model gating and on position for the encoding model itself.
- **Ripple / SWR analyses** that *gate on speed* (e.g., `RippleTimes` consumers that filter by immobility): the **set of detected ripple events can change** because the speed threshold is applied to the *smoothed* speed. With heavier smoothing, brief speed transients get suppressed, so you typically get *more* events passing an "immobility" gate.
- **Place-field / tuning-curve tables** that use position+speed (anything that bins occupancy or filters running epochs by a speed threshold).
- **Trial / behavior tables** that derive run epochs or trajectory bouts from speed crossings — boundaries shift because speed is smoother.

## What does NOT change

- `RawPosition` / `IntervalPositionInfo` upstream of `TrodesPosSelection` — these are the raw inputs and don't depend on params.
- Anything in the **DLC** branch (`DLCPosV1`) unless you also re-populated DLC; DLC is a separate source of `PositionOutput`.
- Spike sorting, LFP, ripple *detection* (the LFP-band ripple events themselves are unchanged; only ripple *gating/labeling* by speed changes).
- The old `default` rows — they are still in the DB. You haven't overwritten anything.

## Practical "what is different in the numbers"

`default_smooth_50` vs `default` (assuming `default_smooth_50` adds a ~50-sample moving-window or Gaussian smoother to position before differentiation):

- **Position (x, y)**: small differences, mostly at sharp turns and tracking jitter. RMS difference is sub-pixel to a few pixels.
- **Head orientation**: smoothed — fewer 360-deg flips at low speed.
- **Speed**: this is where the change is largest. Peaks are lower, troughs are higher, the trace is visibly less spiky. Any speed-threshold-based filtering (running vs immobile, ripple gating, place-field occupancy) will change membership.
- **Velocity vector**: same story as speed; direction is more stable.

## How to actually inspect the diff

```python
from spyglass.position.v1.position_trodes_position import TrodesPosV1
from spyglass.position.position_merge import PositionOutput

key_default = {"nwb_file_name": nwb, "interval_list_name": iv,
               "trodes_pos_params_name": "default"}
key_smooth  = {**key_default, "trodes_pos_params_name": "default_smooth_50"}

df_default = (TrodesPosV1 & key_default).fetch1_dataframe()
df_smooth  = (TrodesPosV1 & key_smooth ).fetch1_dataframe()

# Aligned on time index — compare:
(df_smooth[["head_speed"]] - df_default[["head_speed"]]).describe()
```

And to find the new merge entry:

```python
PositionOutput.TrodesPosV1 & key_smooth   # gives the new merge_id
```

## TL;DR table

| Table | Differs? | Why |
|---|---|---|
| `TrodesPosParams` | no (just contains both param sets) | params table |
| `TrodesPosSelection` | new row added | params name is in PK |
| `TrodesPosV1` | new row, different values | smoothing applied |
| `PositionOutput` (merge) | new `merge_id` | new part-row |
| `LinearizedPositionV1` (if re-run) | yes | depends on position |
| `ClusterlessDecodingV1` / `SortedSpikesDecodingV1` (if re-run) | yes | uses position+speed |
| Ripple-times consumers gated on speed (if re-run) | yes — event set may change | speed threshold applied to smoothed speed |
| Place-field / occupancy tables (if re-run) | yes | speed gating + position bins |
| Raw / LFP / spike sorting | no | upstream / unrelated |
| Old `default` rows | no — still present | DJ keys are immutable, you have both |

## Caveats / unknowns

- The exact contents of `default_smooth_50` depend on what's in your `TrodesPosParams` table. The name strongly implies a 50-sample smoothing window (commonly Gaussian sigma=50 ms or window length 50), but the actual `params` blob is the source of truth — `(TrodesPosParams & {"trodes_pos_params_name": "default_smooth_50"}).fetch1("params")` to confirm.
- "Re-populate" downstream tables don't auto-cascade in DataJoint; you have to call `populate()` on each consumer with the new key (or with no restriction, which will pick up the new selection rows). Until you do, the *only* thing that has new values is `TrodesPosV1` + the new `PositionOutput` merge entry.
- If you literally tried to *update* the existing `TrodesPosSelection` row's `trodes_pos_params_name` (e.g., via `update1`), DataJoint will refuse because it's a primary key field — you must `insert` a new row.
