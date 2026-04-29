# Finding the `merge_id` for Trodes position

In Spyglass, position results from different sources (Trodes, DLC, common
`IntervalPositionInfo`, imported pose) all funnel into a single merge
master, `PositionOutput`, in the `position_merge` schema. Each source has
its own *part* table under that master (e.g.
`PositionOutput.TrodesPosV1`), and the merge master's primary key is
just `merge_id` (a UUID).

The clean way to go from "Trodes-side keys" (`nwb_file_name`,
`interval_list_name`, `trodes_pos_params_name`) to a `merge_id` is the
`merge_get_part` classmethod that `_Merge` provides. It takes a
restriction expressed in the part's natural keys, figures out which
part table that restriction lands in, and hands you back that part
restricted appropriately. From there you fetch `merge_id`.

## Code

```python
from spyglass.position import PositionOutput

restriction = {
    "nwb_file_name": "j1620210710_.nwb",
    "interval_list_name": "02_r1",
    "trodes_pos_params_name": "default",
}

# Sanity check: should resolve to exactly one row in the Trodes part
part = PositionOutput.merge_get_part(restriction)
assert len(part) == 1, f"Expected 1 row, got {len(part)}: {part}"

merge_id = part.fetch1("merge_id")
print(merge_id)
```

`merge_id` is a `uuid.UUID`. If you'd rather have the full primary-key
dict (handy for chaining into other merge-aware helpers like
`PositionOutput.fetch_nwb` or `merge_restrict`), use:

```python
key = PositionOutput.merge_get_part(restriction).fetch1("KEY")
# -> {'merge_id': UUID('...')}
```

On a merge master `KEY` and `{"merge_id": ...}` are equivalent because
`merge_id` is the master's only primary-key attribute.

## Why this form

- `merge_get_part` is a **classmethod** — call it on `PositionOutput`,
  not on a pre-restricted relation. The restriction is its first
  argument; internally it iterates the part tables and picks the one
  whose attributes match.
- `fetch1("merge_id")` is the right call when you expect exactly one
  match and you want the scalar UUID (which is what the prompt asks
  for). If the restriction is ambiguous, `fetch1` will raise — the
  `assert len(part) == 1` above catches the same problem with a
  clearer message.
- Don't reach into the part table directly with
  `PositionOutput.TrodesPosV1 & restriction`. That works in this case
  but is brittle: it bypasses the merge-table's source dispatch, and
  you'd have to repeat the dispatch logic for every source. Going
  through `merge_get_part` is the maintained API.

## Sanity checks before trusting the result

1. Confirm the upstream selection actually exists and was populated:
   ```python
   from spyglass.position.v1 import TrodesPosV1
   TrodesPosV1 & restriction      # must be non-empty
   ```
   If empty, you haven't run `TrodesPosV1.populate(...)` yet, so
   nothing has been inserted into `PositionOutput` either.
2. Confirm uniqueness — `(nwb_file_name, interval_list_name,
   trodes_pos_params_name)` is the natural key for `TrodesPosV1`, so
   one row is expected. The `assert` above pins that.
3. If you want to see the merge entry itself:
   ```python
   PositionOutput & {"merge_id": merge_id}
   ```
