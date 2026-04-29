# Why `fetch1` returns 14 rows

## What the error is telling you

`fetch1` is strict: it raises `DataJointError` unless the restriction
collapses the table to **exactly one row**. The message
`fetch1 should only be called on one tuple, but 14 were returned`
literally means your restriction
`(PositionOutput & {'nwb_file_name': 'j1620210710_.nwb'})` matches
14 rows, not 1. This is a cardinality (too-loose-restriction) bug,
not a missing-data or schema bug.

Your assumption — that `nwb_file_name` uniquely identifies "the
position" for a session — is the thing to revisit. It almost never
does in Spyglass.

## Why one session has 14 PositionOutput rows

`PositionOutput` is a **merge table**, not a leaf result table. In
Spyglass, position data can come from multiple upstream pipelines,
and `PositionOutput` is the union across all of them. The part
tables under `PositionOutput` (in
`spyglass/position/position_merge.py`) include:

- `PositionOutput.TrodesPosV1` — Trodes-derived (LED tracking) position
- `PositionOutput.DLCPosV1` — DeepLabCut-derived position
- `PositionOutput.CommonPos` — legacy / common-framework position
- `PositionOutput.ImportedPose` — pose imported directly from NWB

For a single `nwb_file_name` you can easily accumulate many rows
because the primary key of each upstream table includes more than
just the NWB file. Typical extra keys:

- `interval_list_name` — one row per epoch / run interval (a session
  often has 4–8 of these: sleep1, run1, sleep2, run2, …).
- A pipeline-specific parameter set name, e.g.
  `trodes_pos_params_name`, `dlc_pos_params_name` — one row per
  parameter set you've populated.
- Pipeline-specific upstream keys (DLC model, project, epoch, …).

Multiply "epochs × parameter sets × pipelines that have been run on
this session" and 14 rows for one NWB file is completely normal.
`PositionOutput` is then a merge across all of those, keyed by an
opaque `merge_id` (UUID) — which is what guarantees uniqueness, not
`nwb_file_name`.

## Step 1 — discover what those 14 rows actually are

**Don't guess** which pipeline / parameter set you want. Look first.
The merge table provides `merge_restrict` for exactly this:

```python
from spyglass.position import PositionOutput

key = {'nwb_file_name': 'j1620210710_.nwb'}

# Show all PositionOutput rows for this session, with the part-table
# (source) each merge_id came from.
PositionOutput.merge_restrict(key)
```

That will print 14 rows annotated with which part table each
`merge_id` resolves to. If `merge_restrict` doesn't expand the way
you want, you can also do:

```python
rows = (PositionOutput & key).fetch(as_dict=True)
for r in rows:
    print(r)            # shows merge_id + source bookkeeping
```

From that output, identify which row(s) you want. Common decision
points:

- Which pipeline produced it (Trodes vs DLC vs ImportedPose vs
  CommonPos)? **Don't assume Trodes.** The prompt doesn't say, and
  picking the wrong one silently gives you the wrong trajectory.
- Which `interval_list_name` (which epoch)?
- Which parameter set name, if multiple exist for that pipeline?

## Step 2 — narrow to exactly one row

You have two clean options. Pick based on whether you already know
the source pipeline.

### Option A — source-agnostic via `merge_id`

Once you've identified the `merge_id` you want from Step 1, this
works regardless of which part table it lives in:

```python
target_merge_id = '...'    # from the discovery step above
df = (PositionOutput & {'merge_id': target_merge_id}).fetch1_dataframe()
```

This is the recommended pattern when you're writing reusable code
that should work no matter which upstream pipeline produced the
position.

### Option B — fully-specified key into the part table

If you know the source, restrict on that part table's full primary
key. For example, **if** Step 1 shows your row came from
`TrodesPosV1`:

```python
key = {
    'nwb_file_name': 'j1620210710_.nwb',
    'interval_list_name': 'pos 1 valid times',   # the epoch you want
    'trodes_pos_params_name': '<the params name you populated>',
}
df = (PositionOutput.TrodesPosV1 & key).fetch1_dataframe()
```

Or, **if** Step 1 shows DLC, the equivalent key uses
`dlc_pos_params_name` plus the DLC-specific upstream keys. The
point is: don't hardcode `trodes_pos_params_name` (or any
particular pipeline) until the discovery step has confirmed which
pipeline you're actually pulling from.

If `merge_restrict` returns more than one row even after you add
`interval_list_name` and a params name, list the columns of the
part table (`PositionOutput.TrodesPosV1.heading.primary_key`, etc.)
and add whichever primary-key fields are still unconstrained.

## Why the previous code looked right but wasn't

`{'nwb_file_name': ...}` is a perfectly valid restriction — it just
doesn't uniquely identify a row in a merge table. `fetch1` is doing
its job by refusing to silently pick one of 14 candidates. The fix
is always: **discover first, then restrict to a single
`merge_id` (or a fully-specified part-table key)**, and only then
call `fetch1` / `fetch1_dataframe`.

## TL;DR

- Cardinality error: your restriction matches 14 rows, `fetch1`
  needs 1.
- `PositionOutput` is a merge over Trodes / DLC / CommonPos /
  ImportedPose part tables, and each carries `interval_list_name`
  plus a pipeline-specific params name in its primary key —
  `nwb_file_name` alone is never unique there.
- Run `PositionOutput.merge_restrict({'nwb_file_name': ...})` first
  to see what those 14 rows are and which source they come from.
- Then either grab the specific `merge_id` (source-agnostic) or
  restrict the right part table with its full key (source-specific).
  Don't assume Trodes vs DLC without checking.
