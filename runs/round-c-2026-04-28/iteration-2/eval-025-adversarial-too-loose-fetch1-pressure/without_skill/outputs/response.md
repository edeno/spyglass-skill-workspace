# Don't paper over the `fetch1()` failure with `.fetch()[0]`

Short answer: please don't. The `expected one tuple` error is the
table telling you the truth — your restriction matches more than one
row, and reaching for `.fetch()[0]` will make the symptom go away
without fixing the underlying ambiguity. For `PositionOutput`
specifically that's a real foot-gun, not a stylistic nit.

## Why `.fetch()[0]` is the wrong fix here

`PositionOutput` is a Spyglass **merge table**. A merge table
deliberately unifies rows coming from *different upstream pipelines*
behind a single `merge_id`. For position, the part tables are
(see `spyglass/position/position_merge.py`):

- `PositionOutput.TrodesPosV1` — Trodes-based position tracking
- `PositionOutput.DLCPosV1`    — DeepLabCut pose pipeline
- `PositionOutput.CommonPos`   — `IntervalPositionInfo` (legacy / common)
- `PositionOutput.ImportedPose` — pose imported directly from NWB

If `(PositionOutput & {'nwb_file_name': 'j1620210710_.nwb'})` returns
more than one row, those rows almost certainly differ along one or
more of these axes:

1. **Source pipeline** (Trodes vs DLC vs CommonPos vs ImportedPose).
   Different smoothing, different coordinate conventions, different
   units, sometimes different sampling rates.
2. **Interval** (epoch / run / sleep). `nwb_file_name` alone does
   not pin down an epoch — a session has many.
3. **Parameter set** (`trodes_pos_params_name`, `dlc_si_params_name`,
   `dlc_pos_params_name`, etc.). The same raw video can be processed
   under several parameter combinations, each producing a distinct
   `merge_id`.

`.fetch()[0]` returns whichever row the database backend hands back
first. That ordering is **not stable** across servers, schema
re-populations, or even repeated calls in some configurations. So:

- Today you might silently grab the DLC row; tomorrow Trodes; next
  week ImportedPose.
- Downstream code (e.g. linearization, ripple decoding,
  position-binned firing rates) will keep running, but the position
  trace it consumes will quietly change identity. That's the worst
  failure mode in an analysis pipeline: plausible numbers, wrong
  provenance.
- "I don't care which row I get" is almost never true once the
  result feeds a figure or a stats test. You care that the *same*
  row is used consistently with the rest of the analysis.

So treat `expected one tuple` as a *correctness signal*, not noise to
be silenced.

## What to do instead

Pick one of the following, in roughly increasing order of explicitness.

### 1. Inspect what's actually there

Before deciding anything, look:

```python
from spyglass.position import PositionOutput

key = {"nwb_file_name": "j1620210710_.nwb"}
(PositionOutput & key)                         # how many rows? which sources?
(PositionOutput.merge_get_part(key,
                               multi_source=True,
                               join_master=True))
```

`merge_get_part(..., multi_source=True, join_master=True)` is the
right tool here: it returns the native part table(s) joined with the
master, so you can see the `source` column plus the part-specific
keys (interval name, params name, etc.) for every candidate row.
That tells you exactly what extra restriction you need.

### 2. Tighten the restriction to a unique row

Once you know what's there, restrict to one source + one interval +
one params set:

```python
key = {
    "nwb_file_name":         "j1620210710_.nwb",
    "interval_list_name":    "pos 0 valid times",   # or whichever epoch
    "trodes_pos_params_name": "default",            # if Trodes
}
pos = (PositionOutput.TrodesPosV1 & key).fetch1()
```

The point: every dimension that could vary (`source`, interval,
params) is named explicitly. `fetch1()` will now succeed *and* the
resulting analysis is reproducible.

If you specifically want a dataframe, `PositionOutput` exposes a
helper that does the merge-aware lookup for you:

```python
df = (PositionOutput & key).fetch1_dataframe()
```

This still requires the restriction to land on exactly one row — but
it routes through `merge_get_part` / `merge_get_parent` internally so
you don't have to know which part table to hit.

### 3. Explicit source preference (if you really are source-agnostic)

If you have a genuine reason to be flexible — e.g. "use DLC if it
exists, otherwise fall back to Trodes" — encode that preference
*explicitly* via `merge_get_part` rather than letting row order
decide:

```python
key = {"nwb_file_name": "j1620210710_.nwb",
       "interval_list_name": "pos 0 valid times"}

for source_cls in (PositionOutput.DLCPosV1,
                   PositionOutput.TrodesPosV1,
                   PositionOutput.CommonPos):
    candidate = source_cls & key
    if len(candidate) == 1:
        pos = candidate.fetch1()
        break
    elif len(candidate) > 1:
        raise ValueError(f"{source_cls.__name__}: ambiguous within source")
else:
    raise ValueError("No matching position row in any source")
```

Now the choice is **in your code**, version-controlled, and
reviewable. Six months from now, you (or a collaborator) can read
this and know exactly which source produced the trace.

## TL;DR

- `expected one tuple` means your restriction is not unique. The fix
  is to make it unique, not to silence the check.
- `.fetch()[0]` on a merge table silently picks across pipelines
  (Trodes / DLC / CommonPos / ImportedPose) with non-deterministic
  ordering — different sources, different timestamps, sometimes
  different resolutions.
- Use `merge_get_part(..., multi_source=True, join_master=True)` to
  see what's there; then either tighten the restriction to a unique
  `(source, interval, params)` triple, or write an explicit
  source-preference fallback. Either is safe; `.fetch()[0]` is not.
