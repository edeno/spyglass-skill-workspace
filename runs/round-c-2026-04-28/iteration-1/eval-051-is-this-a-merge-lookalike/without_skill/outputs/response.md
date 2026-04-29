## Short answer

This is not a Spyglass bug. `MuaEventsV1` is **not a merge table** — it is a regular `dj.Computed` table, so it doesn't have `merge_get_part`, `merge_restrict`, or any of the other `merge_*` helpers. The `*V1` (and `*Output`) suffixes are project naming conventions, not a guarantee that a class inherits from `_Merge`.

## Why it raises `AttributeError`

`merge_get_part` is a method defined on Spyglass's `Merge` / `_Merge` base class (`spyglass.utils.dj_merge_tables`). Only tables that inherit from `_Merge` get those helpers. If you look at the actual class definition:

```python
# src/spyglass/mua/v1/mua.py:63
@schema
class MuaEventsV1(SpyglassMixin, dj.Computed):
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

It's a plain `dj.Computed` with `SpyglassMixin`. No merge machinery. So calling `merge_get_part` on it correctly raises `AttributeError`.

## The five (and only five) actual merge masters in Spyglass

These are the classes that inherit from `_Merge` and therefore expose `merge_get_part`, `merge_restrict`, `merge_fetch`, `merge_view`, etc.:

| Class | File |
|---|---|
| `SpikeSortingOutput` | `src/spyglass/spikesorting/spikesorting_merge.py` |
| `LFPOutput` | `src/spyglass/lfp/lfp_merge.py` |
| `PositionOutput` | `src/spyglass/position/position_merge.py` |
| `LinearizedPositionOutput` | `src/spyglass/linearization/merge.py` |
| `DecodingOutput` | `src/spyglass/decoding/decoding_merge.py` |

Anything else — even if it ends in `Output` or `V1` — is not a merge.

## Common merge "lookalikes" (NOT merges)

These names look like they should be merges but aren't:

- `MuaEventsV1` — `dj.Computed`
- `CurationV1` — `dj.Manual`
- `LFPV1` — `dj.Computed` (it's a *part* of the `LFPOutput` merge, not a merge itself)
- `TrodesPosV1`, `DLCPosV1` — `dj.Computed` parts that feed into `PositionOutput`
- `RippleTimesV1` — `dj.Computed`
- Every `*Selection` table — these are upstream `dj.Manual` tables, never merges

The pattern: a `*V1` table is usually a **source** that gets registered as a part-table under a `*Output` merge master, not a merge itself.

## How to actually query `MuaEventsV1`

Since `MuaEventsV1` is just a computed table, restrict it directly with the standard DataJoint `&` operator using its actual primary-key fields. Its PK comes from the upstream FKs in its definition: `mua_param_name`, `nwb_file_name` + `sorted_spikes_group_name` (from `SortedSpikesGroup`), `pos_merge_id` (the projected `merge_id` from `PositionOutput`), and `detection_interval` (the projected `interval_list_name` from `IntervalList`).

```python
from spyglass.mua.v1.mua import MuaEventsV1

# Restrict directly — no merge_* method needed
(MuaEventsV1 & {'nwb_file_name': 'j1620210710_.nwb'}).fetch(as_dict=True)
```

If you want to be more selective, add more PK fields:

```python
key = {
    'nwb_file_name': 'j1620210710_.nwb',
    'mua_param_name': 'default',
    # ...sorted_spikes_group_name, pos_merge_id, detection_interval
}
(MuaEventsV1 & key).fetch1()
```

To see exactly what keys exist, just print the table:

```python
MuaEventsV1() & {'nwb_file_name': 'j1620210710_.nwb'}
```

## Programmatic check: "is this thing a merge table?"

Two equivalent ways:

```python
from spyglass.utils.dj_merge_tables import Merge, is_merge_table
from spyglass.mua.v1.mua import MuaEventsV1
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput

isinstance(MuaEventsV1(), Merge)        # False
isinstance(SpikeSortingOutput(), Merge)  # True

# or the helper
is_merge_table(MuaEventsV1())            # False
is_merge_table(SpikeSortingOutput())     # True
```

You can also just inspect the MRO:

```python
'_Merge' in [c.__name__ for c in type(MuaEventsV1()).__mro__]  # False
```

## Takeaway

- `merge_*` methods exist only on classes that subclass `_Merge`.
- In Spyglass, that's exactly five classes: `SpikeSortingOutput`, `LFPOutput`, `PositionOutput`, `LinearizedPositionOutput`, `DecodingOutput`.
- Don't trust suffixes — `*V1` and `*Output` are conventions; check the base class (or `isinstance(t(), Merge)`) when in doubt.
- For `MuaEventsV1`, just use a normal `&` restriction with the table's PK fields.
