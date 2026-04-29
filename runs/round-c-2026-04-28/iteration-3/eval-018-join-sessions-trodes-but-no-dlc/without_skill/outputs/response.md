# Sessions with Trodes position but not DLC

You want the set difference: sessions present in `TrodesPosV1` but absent from `DLCPosV1`. In DataJoint there are two ways to express this — a Python `set` difference on fetched primary keys, or a DataJoint antijoin (`-`). The set-difference form is the most portable and is what I'd reach for first.

## Recommended: Python set difference on `nwb_file_name`

```python
from spyglass.position.v1 import TrodesPosV1, DLCPosV1

trodes_sessions = set(TrodesPosV1.fetch("nwb_file_name"))
dlc_sessions    = set(DLCPosV1.fetch("nwb_file_name"))

needs_dlc = trodes_sessions - dlc_sessions

print(f"{len(needs_dlc)} sessions with Trodes pos but no DLC pos:")
for nwb in sorted(needs_dlc):
    print(" ", nwb)
```

Why this works:

- `.fetch("nwb_file_name")` on each table returns a 1-D array of NWB file names where that pipeline has been populated.
- Wrapping each in `set(...)` and subtracting gives you exactly the sessions that have a Trodes row but no DLC row.
- This is robust to the two tables having different secondary attributes (which they do — both inherit `analysis_file_name` from `AnalysisNwbfile` and have their own `*_object_id` columns).

If a single NWB file can have multiple Trodes entries (different intervals / parameter sets) and you want session-level granularity, the `set()` already deduplicates — you'll get one row per unique `nwb_file_name`.

If you want richer per-row info (e.g. interval, params) for the missing sessions, you can restrict back:

```python
missing = TrodesPosV1 & [{"nwb_file_name": n} for n in needs_dlc]
missing.fetch("KEY", as_dict=True)   # full primary keys
```

## What about the DataJoint antijoin `-`?

It's tempting to write:

```python
# DON'T — this raises
(TrodesPosV1 - DLCPosV1).fetch("nwb_file_name")
```

That looks like the natural DataJoint way to say "Trodes minus DLC", and conceptually it is. **But bare `TrodesPosV1 - DLCPosV1` will raise a `DataJointError`** at query-build time. The reason: DataJoint's `-` (and `*`) operators refuse to combine two query expressions when they share a *non-primary* attribute that is a foreign-key dependency, because it can't tell whether you meant to join on it or not.

In this case both tables:

- inherit `analysis_file_name` (via `-> AnalysisNwbfile`) as a secondary attribute, and
- carry NWB `*_object_id` secondary columns with the same names on both sides.

DataJoint sees those as ambiguous overlap and refuses the antijoin.

The fix is to project both sides down to just their primary keys before subtracting. `.proj()` with no arguments keeps only the primary-key attributes, so the only attribute the two sides still share is `nwb_file_name` — and that's a primary-key attribute on both, which is the well-defined antijoin case:

```python
needs_dlc = set((TrodesPosV1.proj() - DLCPosV1.proj()).fetch("nwb_file_name"))
```

This works, but it's less obvious than the `set()` form, and you have to remember the `.proj()` on **both** sides. For one-off questions like this, the `set()`-difference form is easier to read and harder to get wrong.

## Things to watch out for

- **Session granularity vs. row granularity.** `TrodesPosV1` and `DLCPosV1` are typically keyed on more than just `nwb_file_name` (they include intervals and parameter set names). "Sessions where Trodes ran but DLC didn't" usually means *no DLC row at all for that NWB file* — that's what the `set` over `nwb_file_name` gives you. If instead you mean "for this exact interval + epoch combination", you'd compare on the full primary key (still doable with set difference of `KEY` dicts, or with the `.proj()` antijoin restricted to common PK attributes).
- **Don't use `*` (inner join) here.** `TrodesPosV1 * DLCPosV1` would give you sessions where *both* ran, which is the opposite of what you want.
- **Upstream filtering.** If you only care about sessions that *should* have DLC (e.g. behavior epochs, certain rigs), restrict `TrodesPosV1` first by joining/restricting to `IntervalList` or whatever metadata table identifies those epochs, then take the set difference.

## TL;DR

```python
needs_dlc = set(TrodesPosV1.fetch("nwb_file_name")) - set(DLCPosV1.fetch("nwb_file_name"))
```

Simple, portable, no DataJoint operator gotchas. Use the `.proj() - .proj()` antijoin only if you have a specific reason to keep the work server-side.
