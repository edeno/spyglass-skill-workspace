# Next step after inserting a `TrodesPosSelection` row

Run `TrodesPosV1.populate(key)`. That is step 3 of the canonical Trodes flow (params → selection → populate). The populate handler runs the computation and, on success, auto-inserts the resulting row into the `PositionOutput` merge table via `PositionOutput._merge_insert(...)` (defined at `position/v1/position_trodes_position.py:241`), so you do not insert into `PositionOutput` yourself.

```python
from spyglass.position.v1 import TrodesPosV1

key = {
    "nwb_file_name": nwb_file,
    "interval_list_name": "pos 1 valid times",
    "trodes_pos_params_name": "default",
}
TrodesPosV1.populate(key)
```

## Then fetch through the merge layer

Once populate succeeds, do not fetch from `TrodesPosV1` directly for downstream work — go through `PositionOutput` so that anything depending on "position for this session/interval/params" is source-agnostic (Trodes vs DLC vs imported pose):

```python
from spyglass.position import PositionOutput

merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
position_df = (PositionOutput & merge_key).fetch1_dataframe()
# columns: position_x, position_y, orientation, velocity_x, velocity_y, speed

# Trodes-specific helper, available through the merge:
video_path = (PositionOutput & merge_key).fetch_video_path()
```

## Cardinality / verification notes

- `merge_get_part(key)` returns a relation, not a row — the `.fetch1("KEY")` call is what enforces "exactly one match". If your `key` is partial (e.g. only `nwb_file_name`), it will raise; add PK fields (`interval_list_name`, `trodes_pos_params_name`) until the restriction is unique. This is the pre-`fetch1` cardinality check from the skill's feedback loops.
- Do not write `PositionOutput & {"nwb_file_name": nwb_file}` — `PositionOutput`'s only PK is `merge_id`, so the `nwb_file_name` attr is silently dropped and you get the whole merge table back. Use `merge_restrict(...)` / `merge_get_part(...)` instead (Common Mistake #6).
- If `TrodesPosV1.populate(key)` errors, the usual diagnosis is that `RawPosition` for that `(nwb_file_name, interval_list_name)` has not been ingested, or `TrodesPosParams` has no row for `trodes_pos_params_name` — check `RawPosition & key` and `TrodesPosParams & {"trodes_pos_params_name": ...}` first.

## What's downstream of `PositionOutput`

If your end goal is one of these, populating `TrodesPosV1` is the prerequisite and the next layer keys off `PositionOutput` (typically via a `merge_id` from `merge_get_part(...).fetch1("KEY")`):

- Linearization (`IntervalLinearizedPosition` and friends) — takes a `PositionOutput` merge row plus a track graph.
- Decoding (clusterless or sorted-spikes) — consumes a `PositionOutput` merge row as the behavioral covariate.
- Any custom analysis joining position to spikes / LFP / ripples.

## Sources

- `skills/spyglass/references/position_trodes_v1_pipeline.md` — pipeline flow, canonical example, fetch pattern.
- `position/v1/position_trodes_position.py:241` — `_merge_insert` into `PositionOutput` inside the Trodes populate handler.
- `position/v1/position_trodes_position.py:278` — `fetch_video_path` on the Trodes part table (reachable via the merge).
- `skills/spyglass/references/position_pipeline.md` — `PositionOutput` umbrella / per-source method matrix (for DLC vs Trodes vs imported pose).
