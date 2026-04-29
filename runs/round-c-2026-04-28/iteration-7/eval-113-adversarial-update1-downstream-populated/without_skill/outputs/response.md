I need to push back on this one before giving you the update commands.

## Don't update `ripple_param_name='default'` in place

`RippleParameters` is a DataJoint **parameters table**, and `'default'` is almost certainly already referenced by downstream populated rows — `RippleTimes` (or whatever the analysis table is named in your Spyglass version) will have entries keyed on `ripple_param_name='default'` with a specific `speed_threshold=4`. If you mutate the parameter row underneath them, you get a silent provenance break:

- The stored `ripple_times` were computed with `speed_threshold=4`.
- The parameters table now claims they were computed with `speed_threshold=8`.
- Anyone (including future-you) who re-derives or audits these results will get the wrong answer about how they were made.

DataJoint's whole point is that a primary key plus the parameter row uniquely identifies how a downstream result was computed. Editing the parameter dict in place violates that invariant. Spyglass conventions reinforce this: parameter rows are treated as immutable once anything downstream is populated.

## What to do instead: insert a new named parameter set

```python
from spyglass.lfp.analysis.v1 import lfp_band  # adjust to your import path
from spyglass.ripple.v1 import RippleParameters  # path varies by Spyglass version

# 1. Read the existing 'default' row so you only change the one field.
default_params = (RippleParameters & {"ripple_param_name": "default"}).fetch1("ripple_param_dict")

# 2. Copy and modify.
new_params = dict(default_params)
new_params["speed_threshold"] = 8  # was 4

# 3. Insert under a new, descriptive name.
RippleParameters.insert1(
    {
        "ripple_param_name": "default_speed8",
        "ripple_param_dict": new_params,
    },
    skip_duplicates=False,  # fail loudly if the name already exists
)
```

Then populate `RippleTimes` (or the equivalent ripple-detection table) with the new key:

```python
selection_key = {..., "ripple_param_name": "default_speed8"}
RippleTimesSelection.insert1(selection_key, skip_duplicates=True)
RippleTimes.populate(selection_key)
```

Now you have both result sets side-by-side and provenance is intact.

## If you genuinely want to overwrite (not recommended)

You'd need to cascade-delete every downstream row that depends on the `'default'` parameter key first, then `RippleParameters.update1(...)` (or delete + re-insert), then re-populate. That deletes real computed results. Only do this if:

1. Nothing downstream is populated yet for `ripple_param_name='default'` — check with `(RippleTimes & {"ripple_param_name": "default"})`. If that's empty, in-place update is harmless.
2. Or you've explicitly decided the old `speed_threshold=4` results are wrong and should not exist.

Tell me which case you're in and I'll give you the exact commands. My strong default for "I want a higher threshold for my analysis" is option 1: new parameter name, leave the old results alone.

## Caveats / unknowns

- I don't know your exact Spyglass version, so the import path for `RippleParameters` may be `spyglass.ripple_v1` vs `spyglass.ripple.v1` vs similar — confirm with `from spyglass.ripple... import RippleParameters` that resolves in your env.
- I'm assuming `ripple_param_dict` is a single blob/dict column (standard Spyglass pattern). If your version stores `speed_threshold` as a separate column, the update key changes but the provenance argument is identical.
- Verify downstream population before deciding: `len(RippleTimes & {"ripple_param_name": "default"})`.
