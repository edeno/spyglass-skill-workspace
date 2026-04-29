# Resolving the Trodes-position `merge_id`

`PositionOutput` is a merge master (its only PK column is `merge_id`),
so you cannot find this row by restricting the master with
`nwb_file_name` / `interval_list_name` / `trodes_pos_params_name` —
those fields don't live on the master and DataJoint will silently
drop them, returning the whole table. The right call is
`PositionOutput.merge_get_part(...)`, which walks the part tables
(here, `PositionOutput.TrodesPosV1`) and finds the one row that
matches the upstream key.

The three fields you have are exactly the full primary key of
`TrodesPosV1` (verified in
`src/spyglass/position/v1/position_trodes_position.py`), so the
restriction is unique — `fetch1` is safe without a separate `len`
check.

```python
from spyglass.position.position_merge import PositionOutput

upstream_key = {
    "nwb_file_name": "j1620210710_.nwb",
    "interval_list_name": "02_r1",
    "trodes_pos_params_name": "default",
}

merge_id = (
    PositionOutput
    .merge_get_part(upstream_key)      # classmethod — pass the restriction in
    .fetch1("merge_id")                # scalar UUID — answers the prompt directly
)
print(merge_id)
```

If you'd rather have the full primary-key dict (handy when feeding
the result into another merge-aware helper), swap the last line for
`fetch1("KEY")` — on a merge master that returns just
`{"merge_id": <uuid>}`:

```python
merge_key = PositionOutput.merge_get_part(upstream_key).fetch1("KEY")
# {"merge_id": UUID('...')}
# downstream:
df = (PositionOutput & merge_key).fetch1_dataframe()
```

## Why not `(PositionOutput & upstream_key).fetch1("merge_id")`?

That's the canonical merge-master footgun. The master's heading is
just `merge_id` (+ `source` as a secondary), so DataJoint silently
discards the unknown attributes in `upstream_key` and `&` returns the
whole table — `fetch1` then fails with "expected one tuple, got N",
or worse, succeeds against the wrong row if the table happens to
have one entry. Always go through `merge_get_part` (or
`merge_restrict`) when the fields you have live on a part table.

## Why not `(PositionOutput.TrodesPosV1 & upstream_key).fetch1("merge_id")`?

That actually works — the part table carries both the upstream PK
and `merge_id`. But `merge_get_part` is the documented portable
shape that survives the source moving between parts (e.g., if a row
later got re-inserted via `CommonPos` instead of `TrodesPosV1`, the
part-table query would silently miss it while `merge_get_part` still
resolves through whichever part holds it). Prefer the merge-aware
form.

## Defensive variant if you're not sure the row exists

If the user hasn't actually populated the merge for this session
yet, `merge_get_part` raises
`ValueError: Found 0 potential parts: []`. Pre-check:

```python
hits = PositionOutput.merge_get_part(upstream_key, return_empties=True)
# or, more directly:
n = len(PositionOutput.TrodesPosV1 & upstream_key)
assert n == 1, f"expected exactly one TrodesPosV1 row, got {n}"
merge_id = PositionOutput.merge_get_part(upstream_key).fetch1("merge_id")
```

If `n == 0`, the upstream `TrodesPosV1` may have been populated but
never inserted into `PositionOutput` — re-run the merge insert step
from the Trodes-position pipeline before retrying.
