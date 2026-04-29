## There is no DataJoint restriction that filters on `speed_threshold`

`speed_threshold` is **not** a heading column on `RippleParameters`. The table's heading is just:

- `ripple_param_name` (PK, varchar)
- `ripple_param_dict` (longblob)

`speed_threshold` lives **nested inside the `ripple_param_dict` longblob**, two levels deep:

```
ripple_param_dict["ripple_detection_params"]["speed_threshold"]
```

The blob shape is documented in `skills/spyglass/references/ripple_pipeline.md` § RippleParameters, and the authoritative consumer is `RippleTimesV1.make` at `src/spyglass/ripple/v1/ripple.py:207-224`, which fetches `ripple_param_dict`, pulls out `ripple_detection_params`, and `**`-splats it into the detector. That `make()` is the source of truth for what's actually inside the blob — verify against an existing row if you need a runtime cross-check:

```python
(RippleParameters & {}).fetch('ripple_param_dict', limit=1, as_dict=True)[0]
```

### Why `RippleParameters & {"speed_threshold": ...}` won't work

DataJoint restrictions only see attributes that appear in the table's `heading`. Blob fields are opaque pickled bytes from the server's perspective — there is no SQL predicate to peer inside them. Worse, an unknown key in a dict-restriction is silently dropped (this is the same shape as Common Mistake #6 on merge masters): `RippleParameters & {"speed_threshold": 4.0}` would just return the **whole table**, which is a silent-wrong-count footgun rather than an error.

### What to do instead — fetch then filter in Python

```python
from spyglass.ripple.v1 import RippleParameters

rows = RippleParameters.fetch(as_dict=True)
matches = [
    r for r in rows
    if r["ripple_param_dict"]["ripple_detection_params"]["speed_threshold"] < 4.0
]

# the PKs of the matching rows
matching_param_names = [r["ripple_param_name"] for r in matches]
```

If you then want a relation restricted to those names so you can join it downstream:

```python
hits = RippleParameters & [{"ripple_param_name": n} for n in matching_param_names]
```

### One robustness note

The default presets (`"default"` and `"default_trodes"`, inserted by `RippleParameters().insert_default()`) both ship with `speed_threshold = 4.0`. If your instance has only those two presets, **strict** `< 4.0` will return nothing — you may want `<= 4.0` depending on intent. Also, custom rows added by other users may omit the `ripple_detection_params` sub-dict or omit `speed_threshold`, so a defensive variant is:

```python
def below(row, cutoff):
    rdp = row["ripple_param_dict"].get("ripple_detection_params", {})
    st = rdp.get("speed_threshold")
    return st is not None and st < cutoff

matches = [r for r in rows if below(r, 4.0)]
```

### Pointers

- Blob shape + parameter semantics: `skills/spyglass/references/ripple_pipeline.md` § RippleParameters (covers each key in `ripple_detection_params` and the direction-of-effect of `speed_threshold`).
- Why blob keys vary per pipeline (and route blob-shape questions to the consumer's `make()`): `skills/spyglass/references/feedback_loops.md`.
- Source of truth for what's inside the blob: `RippleTimesV1.make` at `src/spyglass/ripple/v1/ripple.py:207-224`.
