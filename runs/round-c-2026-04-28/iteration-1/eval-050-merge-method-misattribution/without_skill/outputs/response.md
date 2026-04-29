## Short answer

No — `get_restricted_merge_ids(...)` is **not** a general method on Spyglass merge tables. It is defined only on `SpikeSortingOutput`, not on the shared `_Merge` base class that `PositionOutput`, `LFPOutput`, `DecodingOutput`, and `LinearizedPositionOutput` all inherit from. Calling it on `PositionOutput` will raise `AttributeError: 'PositionOutput' object has no attribute 'get_restricted_merge_ids'`.

For `PositionOutput`, the right tools are the base `_Merge` methods that every Spyglass merge master inherits: **`merge_restrict`** and **`merge_get_part`** (no `sources=` kwarg needed).

---

## Why the spikesorting example doesn't transfer

If you look at the class hierarchy in `spyglass/utils/dj_merge_tables.py`, the merge-table superclass `_Merge` provides the common surface:

- `merge_restrict(restriction)` — returns a virtual-merged view of the master + all parts, restricted by `restriction`.
- `merge_get_part(restriction, ...)` — returns the native part table(s) corresponding to the restriction.
- `merge_view`, `merge_fetch`, `merge_delete`, etc.

`get_restricted_merge_ids` lives on `SpikeSortingOutput` (`src/spyglass/spikesorting/spikesorting_merge.py` around line 111), where it wraps a sorting-pipeline-specific resolution: it walks `SpikeSortingSelection` / `MetricCurationSelection` / `CurationV1` / `ArtifactDetection` to map an "interpretable" key (session, sort group, interval, artifact params, …) onto the `merge_id`s that exist for both the v0 and v1 sorting pipelines — hence the `sources=['v0', 'v1']` kwarg. None of that machinery exists for position, LFP, decoding, or linearization, which is why the helper isn't on the base class.

Because `PositionOutput` doesn't inherit it from anywhere, Python raises `AttributeError` at attribute-lookup time. That's good news for you: it fails loudly instead of silently returning the wrong thing.

Same fate awaits `LFPOutput().get_restricted_merge_ids(...)`, `DecodingOutput().get_restricted_merge_ids(...)`, and `LinearizedPositionOutput().get_restricted_merge_ids(...)`. Only `SpikeSortingOutput` has it.

Don't try to "fix" this by subclassing or monkey-patching `PositionOutput` — the spikesorting helper is intentionally tied to the sorting pipeline schema and would not give meaningful results elsewhere. Use the base methods instead.

---

## What to do for `PositionOutput`

### 1. Get all `merge_id`s for a session (across all sources)

```python
from spyglass.position import PositionOutput

session_key = {'nwb_file_name': 'j1620210710_.nwb'}

merge_ids = (
    PositionOutput.merge_restrict(session_key)
    .fetch('merge_id')
)
```

`merge_restrict` does the union over all the part tables (e.g. `TrodesPosV1`, `DLCPosV1`, `CommonPos`, …) and lets DataJoint apply your restriction across whichever parts have those attributes. You get back the `merge_id` UUIDs you can use as keys downstream.

### 2. Across many sessions

The restriction is just a normal DataJoint restriction, so a list of dicts or an `IN` clause works fine:

```python
session_keys = [
    {'nwb_file_name': 'j1620210710_.nwb'},
    {'nwb_file_name': 'j1620210711_.nwb'},
    # ...
]

merge_ids = (
    PositionOutput.merge_restrict(session_keys)
    .fetch('merge_id')
)
```

or

```python
restr = 'nwb_file_name in ("j1620210710_.nwb", "j1620210711_.nwb")'
merge_ids = PositionOutput.merge_restrict(restr).fetch('merge_id')
```

### 3. When you want a single source's part table

If your restriction is narrow enough to pick a single source (e.g. you're filtering down to a specific `trodes_pos_params_name` and `interval_list_name`), use `merge_get_part` to drop down into the native part table:

```python
key = {
    'nwb_file_name': 'j1620210710_.nwb',
    'interval_list_name': 'pos 0 valid times',
    'trodes_pos_params_name': 'default',
}
part_key = PositionOutput.merge_get_part(key).fetch1('KEY')
# part_key now has merge_id + the part-table primary key
```

If your restriction matches multiple sources and you want all of them back, pass `multi_source=True`:

```python
parts = PositionOutput.merge_get_part(session_key, multi_source=True)
```

---

## TL;DR

| Want                                                           | Use                                                          |
| -------------------------------------------------------------- | ------------------------------------------------------------ |
| `merge_id`s for some sessions on `PositionOutput`              | `PositionOutput.merge_restrict(restr).fetch('merge_id')`     |
| The native part-table row(s) for a narrow restriction          | `PositionOutput.merge_get_part(restr)` (`.fetch1('KEY')` if unique) |
| The same on `LFPOutput`, `DecodingOutput`, `LinearizedPositionOutput` | Same two methods — they're inherited from `_Merge`           |
| The sorting-pipeline–aware helper                              | Only `SpikeSortingOutput.get_restricted_merge_ids(key, sources=[...])`; nowhere else |

So your line should be:

```python
merge_ids = PositionOutput.merge_restrict({'nwb_file_name': 'j1620210710_.nwb'}).fetch('merge_id')
```

— not `PositionOutput().get_restricted_merge_ids(...)`, which will `AttributeError`.
