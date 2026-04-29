## Not a Spyglass bug — `MuaEventsV1` isn't a merge table

The `AttributeError` is correct: `MuaEventsV1` does not have `merge_get_part` because it does not inherit from `_Merge`. It's a plain `dj.Computed` table with its own multi-field primary key.

Source check (`src/spyglass/mua/v1/mua.py:63`):

```python
@schema
class MuaEventsV1(SpyglassMixin, dj.Computed):    # <-- dj.Computed, not _Merge
    definition = """
    -> MuaEventsParameters
    -> SortedSpikesGroup
    -> PositionOutput.proj(pos_merge_id='merge_id')
    -> IntervalList.proj(detection_interval='interval_list_name')
    ---
    -> AnalysisNwbfile
    mua_times_object_id : varchar(40)
    """
```

Its real PK fields are `mua_param_name`, `nwb_file_name`, `sorted_spikes_group_name`, `pos_merge_id`, and `detection_interval` — note the two projected-FK renames (`pos_merge_id` from `PositionOutput.merge_id`, and `detection_interval` from `IntervalList.interval_list_name`). You restrict it directly with `&`, no `merge_*` methods involved.

## The actual five merge masters

Only these five Spyglass tables inherit from `_Merge` and carry `merge_id` as their only PK column:

| Merge master | Source |
|---|---|
| `SpikeSortingOutput` | `src/spyglass/spikesorting/spikesorting_merge.py:34` |
| `LFPOutput` | `src/spyglass/lfp/lfp_merge.py:16` |
| `PositionOutput` | `src/spyglass/position/position_merge.py:24` |
| `LinearizedPositionOutput` | `src/spyglass/linearization/merge.py:13` |
| `DecodingOutput` | `src/spyglass/decoding/decoding_merge.py:19` |

These — and only these — respond to `merge_get_part`, `merge_restrict`, `merge_delete`, etc.

## The `*V1` / `*Output` suffix is convention, not a contract

Spyglass naming is informal: a `*V1` suffix marks a versioned pipeline implementation, and an `*Output` suffix marks a merge master. Neither is enforced — there are several lookalikes that share the suffix shape but aren't merges. Confirmed lookalikes that you'd have to `& {...}`-restrict directly (no `merge_*` methods):

- `MuaEventsV1` — `dj.Computed` (`mua/v1/mua.py:63`)
- `CurationV1` — `dj.Manual` (`spikesorting/v1/curation.py:30`)
- `LFPV1`, `TrodesPosV1`, `DLCPosV1`, `RippleTimesV1`, `ClusterlessDecodingV1`, `SortedSpikesDecodingV1` — all `dj.Computed`
- Every `*Selection` table (`SpikeSortingSelection`, `LFPSelection`, `RippleLFPSelection`, …) — all `dj.Manual`
- `IntervalLinearizedPosition` — `dj.Computed`

Note the related naming asymmetry on the spike-sorting v1 side: there is no `SpikeSortingV1` class — the v1 sorting Computed table is just named `SpikeSorting`. Users coming from the v0 → v1 migration often expect a `V1` suffix that isn't there.

## Correct call for your case

For `MuaEventsV1`, restrict by its actual PK fields (or any subset) directly — it's an ordinary `dj.Computed` table:

```python
from spyglass.mua.v1.mua import MuaEventsV1

# Discover what's there for this NWB file
rows = (MuaEventsV1 & {'nwb_file_name': 'j1620210710_.nwb'}).fetch(as_dict=True)

# To narrow further (e.g., for fetch1), add the other PK fields:
key = {
    'nwb_file_name': 'j1620210710_.nwb',
    'mua_param_name': 'default',
    'sorted_spikes_group_name': '<your group>',
    'pos_merge_id':              '<your position merge_id>',  # NOT 'merge_id'
    'detection_interval':        '<your interval_list_name>', # NOT 'interval_list_name'
}
(MuaEventsV1 & key).fetch1()
```

Two gotchas to flag while you're here, since `MuaEventsV1` foreign-keys into two merge tables and one renamed interval:

1. The PositionOutput FK is renamed via `.proj(pos_merge_id='merge_id')` — when building keys for `MuaEventsV1`, use `pos_merge_id`, not `merge_id`. Resolve it through the merge master:
   ```python
   from spyglass.position import PositionOutput
   pos_merge_id = (PositionOutput.merge_get_part(session_key)
                   .fetch1('KEY'))['merge_id']
   key['pos_merge_id'] = pos_merge_id
   ```
2. Similarly, the IntervalList FK is renamed to `detection_interval` (not `interval_list_name`).

## Programmatic check: "is this a merge table?"

```python
from spyglass.utils.dj_merge_tables import Merge
from spyglass.mua.v1.mua import MuaEventsV1
from spyglass.position import PositionOutput

isinstance(MuaEventsV1(),  Merge)   # False  — dj.Computed, no merge_* methods
isinstance(PositionOutput(), Merge) # True   — actual merge master
```

Equivalent quick check on the heading: a merge master's `primary_key` is exactly `['merge_id']`. Anything else (multiple PK fields, or a single non-`merge_id` PK) is not a merge.

```python
MuaEventsV1.heading.primary_key
# ['nwb_file_name', 'mua_param_name', 'sorted_spikes_group_name',
#  'pos_merge_id', 'detection_interval']
PositionOutput.heading.primary_key
# ['merge_id']
```

So: not a Spyglass bug, just a naming lookalike. `merge_*` methods only exist on `SpikeSortingOutput`, `LFPOutput`, `PositionOutput`, `LinearizedPositionOutput`, and `DecodingOutput`.
