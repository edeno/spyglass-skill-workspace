# No — `get_restricted_merge_ids` is `SpikeSortingOutput`-only

That helper is **not** on the `_Merge` base. It's defined only on `SpikeSortingOutput` (see `src/spyglass/spikesorting/spikesorting_merge.py:111`). The other four merge masters — `PositionOutput`, `LFPOutput`, `DecodingOutput`, `LinearizedPositionOutput` — do not inherit it, so:

```python
PositionOutput().get_restricted_merge_ids({"nwb_file_name": "j1620210710_.nwb"})
# AttributeError: 'PositionOutput' object has no attribute 'get_restricted_merge_ids'
```

Important: this is a hard `AttributeError`, **not** a silent wrong-data return. That's actually the friendly outcome — you get told immediately rather than getting plausible-looking-but-wrong `merge_id`s.

The reason it's not portable: `SpikeSortingOutput.get_restricted_merge_ids` wraps a sorting-specific "resolve session + sort-group + artifact-filter → merge_ids" flow (with `sources=`, `restrict_by_artifact=` kwargs that mean things only for sorted spikes). That flow doesn't generalize to position, LFP, or decoding outputs, which is why it lives on the one master and not on the base.

## What to use on `PositionOutput` instead

Use the base `_Merge` methods that every master has — `merge_restrict` (and `merge_get_part` when you need the specific part-table). No `sources=` kwarg needed; `merge_restrict` already walks all the part tables.

### Pattern 1 — get all `PositionOutput` `merge_id`s for one session, all sources

```python
from spyglass.position.position_merge import PositionOutput

merge_ids = (
    PositionOutput
    .merge_restrict({"nwb_file_name": "j1620210710_.nwb"})
    .fetch("merge_id")
)
```

This returns merge_ids across `TrodesPosV1`, `DLCPosV1`, `CommonPos`, `ImportedPose` — whatever was inserted for that session.

### Pattern 2 — many sessions at once

`merge_restrict` accepts a list of dicts the same way `&` does, so the natural shape is:

```python
nwb_files = ["j1620210710_.nwb", "j1620210711_.nwb", "j1620210712_.nwb"]

per_session = {
    f: PositionOutput.merge_restrict({"nwb_file_name": f}).fetch("merge_id")
    for f in nwb_files
}
```

A single `PositionOutput.merge_restrict([{"nwb_file_name": f} for f in files]).fetch("merge_id")` also works if you don't need to keep the per-session grouping. Either way, **don't** do `(PositionOutput & {"nwb_file_name": f}).fetch("merge_id")` — the master's only PK column is `merge_id`, so DataJoint silently drops the unknown `nwb_file_name` restriction and you get the entire table back.

### Pattern 3 — when the restriction picks exactly one source

If your restriction narrows to a single part table (e.g. you also constrain `interval_list_name` and `trodes_pos_params_name`), `merge_get_part` resolves directly to that part:

```python
key = {
    "nwb_file_name": "j1620210710_.nwb",
    "interval_list_name": "pos 0 valid times",
    "trodes_pos_params_name": "default",
}
merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
df = (PositionOutput & merge_key).fetch1_dataframe()
```

`merge_get_part` raises `ValueError: Found multiple potential parts: [...]` if your restriction matches more than one source — pass `multi_source=True` if that's what you want.

## Don't subclass or monkeypatch

Don't add `get_restricted_merge_ids` to `PositionOutput` (subclass, monkeypatch, or edit `src/spyglass/...`). Three reasons:

1. It would couple position code to spike-sorting-specific kwargs (`sources=`, `restrict_by_artifact=`) that don't have meaning for position data.
2. Edits to the installed package desync your DB schema from what other labs run, and `pip install -e .` silently reverts them anyway.
3. The base `merge_restrict` / `merge_get_part` already cover the use case in two lines and work uniformly across all five merge masters.

## TL;DR

| What you tried | What to do instead |
|---|---|
| `PositionOutput().get_restricted_merge_ids({"nwb_file_name": f})` → `AttributeError` | `PositionOutput.merge_restrict({"nwb_file_name": f}).fetch("merge_id")` |
| Wanting `sources=["v1"]` | Drop it — `merge_restrict` already spans all part tables; further-restrict with `& 'source = "TrodesPosV1"'` if you want only one |
| Resolving one row to a fetchable key | `merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")` |

The same advice applies to `LFPOutput`, `DecodingOutput`, and `LinearizedPositionOutput` — none of them have `get_restricted_merge_ids` either; use `merge_restrict` / `merge_get_part` on all four.
