**No — that restriction is partial-PK, and `populate()` will run over every combination of the missing PK fields under the new params name, not just one downstream analysis.**

## Why it isn't enough

`RippleTimesV1`'s primary key has **three** FK components, not just `ripple_param_name`. From the source (`src/spyglass/ripple/v1/ripple.py:182-190`):

```python
@schema
class RippleTimesV1(SpyglassMixin, dj.Computed):
    definition = """
    -> RippleLFPSelection
    -> RippleParameters
    -> PositionOutput.proj(pos_merge_id='merge_id')
    ---
    -> AnalysisNwbfile
    ripple_times_object_id : varchar(40)
    """
```

So the full PK is:

- `RippleLFPSelection`'s PK (which itself expands to `LFPBandV1`'s PK + `group_name`, `ripple/v1/ripple.py:33-37`)
- `ripple_param_name` (from `RippleParameters`)
- `pos_merge_id` (the projected `merge_id` from `PositionOutput`)

`RippleTimesV1.populate({'ripple_param_name': 'tighter_thresh'})` leaves `RippleLFPSelection` and `pos_merge_id` unrestricted. DataJoint will compute the cross-product of *every* `RippleLFPSelection` row × *every* `PositionOutput` `merge_id` × the new param name and try to populate all of them. That is almost certainly not what you want — you'll burn compute on (and write rows for) electrode-group / position-source combinations you never intended to reprocess.

## Verify before you run

Don't trust my recall — confirm the full PK in your environment:

```bash
python skills/spyglass/scripts/code_graph.py describe RippleTimesV1
```

or in your Python session:

```python
RippleTimesV1.heading.primary_key
```

You should see the three FK groups expanded out (LFPBand fields, `group_name`, `ripple_param_name`, `pos_merge_id`).

## Build a fully-scoped populate_key

Mirror the canonical pattern from `32_Ripple_Detection.ipynb` — restrict to one specific `RippleLFPSelection` row and one specific `pos_merge_id`, then add your new param name:

```python
from spyglass.position import PositionOutput
from spyglass.ripple.v1 import RippleLFPSelection, RippleTimesV1

# 1. Resolve the specific RippleLFPSelection row you want to recompute.
#    rip_sel_key should be the same fully-scoped key you used the first
#    time (LFPBandV1 PK + group_name).
rip_sel_key = (RippleLFPSelection & lfp_band_key & {
    "group_name": "CA1",
}).fetch1("KEY")

# 2. Resolve pos_merge_id through the appropriate PositionOutput part
#    (TrodesPosV1 / DLCPosV1) — restricting the master directly by
#    nwb_file_name silently returns the whole merge table.
pos_merge_id = (PositionOutput.TrodesPosV1 & {
    "nwb_file_name": nwb_file_name,
    "interval_list_name": position_interval_list_name,
    "trodes_pos_params_name": trodes_pos_params_name,
}).fetch1("merge_id")

# 3. Build the full populate key.
populate_key = {
    **rip_sel_key,                       # RippleLFPSelection PK
    "ripple_param_name": "tighter_thresh",
    "pos_merge_id": pos_merge_id,        # specific PositionOutput merge_id
}

# 4. Sanity-check scope before populating — should be exactly 1.
print(len((RippleTimesV1.key_source & populate_key)))

RippleTimesV1.populate(populate_key, display_progress=True)
```

Two correctness gates worth re-stating (both apply to your re-run, not just the first populate):

1. **Don't restrict `PositionOutput` directly** by `nwb_file_name` / `interval_list_name` — those aren't on the merge master's heading and the restriction is silently dropped. Go through `PositionOutput.TrodesPosV1` (or `.DLCPosV1`) to resolve `pos_merge_id`.
2. **Include `trodes_pos_params_name`** (or DLC params) when resolving the position part — `(nwb_file_name, interval_list_name)` alone can match multiple param rows.

## Also: insert the new params row first

`tighter_thresh` has to exist in `RippleParameters` before `populate()` will find any work to do for it:

```python
from spyglass.ripple.v1 import RippleParameters

RippleParameters.insert1({
    "ripple_param_name": "tighter_thresh",
    "ripple_param_dict": {
        "speed_name": "head_speed",
        "ripple_detection_algorithm": "Kay_ripple_detector",
        "ripple_detection_params": {
            "speed_threshold": 4.0,
            "minimum_duration": 0.015,
            "zscore_threshold": 3.0,   # tighter than default 2.0
            "smoothing_sigma": 0.004,
            "close_ripple_threshold": 0.0,
        },
    },
})
```

(Direction note: in `RippleParameters`, `speed_threshold` is the immobility cutoff — *raising* it loosens the immobility filter and admits more events. To get fewer/cleaner SWRs you'd lower `speed_threshold` and/or raise `zscore_threshold`. See `references/ripple_pipeline.md` "Parameter semantics".)

## References

- `src/spyglass/ripple/v1/ripple.py:182-190` — `RippleTimesV1` definition (the three-FK PK)
- `skills/spyglass/references/ripple_pipeline.md` — full canonical example with the same `populate_key` shape
- `skills/spyglass/references/destructive_operations.md` — post-update populate scope
