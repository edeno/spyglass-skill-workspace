# Filtering `RippleParameters` by `speed_threshold < 4.0`

## Short answer

You can't write a DataJoint restriction like
`RippleParameters & "speed_threshold < 4.0"` for this case. The reason is
that `speed_threshold` is **not a column in the `RippleParameters` heading
at all** — it lives inside a Python dict that's stored as a `BLOB`
("longblob") attribute on each row. DataJoint restrictions only operate on
the heading (the SQL columns); they cannot reach inside a serialized blob.

The correct pattern is **fetch every row, deserialize the blob, then
filter in Python**.

## What the table actually looks like

`spyglass.ripple.v1.ripple.RippleParameters` is defined as:

```python
class RippleParameters(SpyglassMixin, dj.Lookup):
    definition = """
    ripple_param_name : varchar(80)   # a name for this set of parameters
    ----
    ripple_param_dict : BLOB          # dictionary of parameters
    """
```

So the heading has exactly two attributes:

- `ripple_param_name` — primary key, a name string.
- `ripple_param_dict` — a single Python dict, pickled into MySQL as a blob.

`speed_threshold` is a *key inside that dict*, two levels deep. The dict's
shape is (per `RippleParameters.insert_default` and the docstring around
lines 110–136 of `ripple/v1/ripple.py`):

```python
{
    "speed_name": "head_speed",
    "ripple_detection_algorithm": "Kay_ripple_detector",
    "ripple_detection_params": {
        "speed_threshold": 4.0,        # <-- the value you want to filter on
        "minimum_duration": 0.015,
        "zscore_threshold": 2.0,
        "smoothing_sigma": 0.004,
        "close_ripple_threshold": 0.0,
    },
}
```

That nested layout is what the consumer expects, too: `RippleTimesV1.make`
fetches the dict and passes `ripple_detection_params` straight into the
detection algorithm as `**kwargs` (see `ripple/v1/ripple.py` ~ line 207–224):

```python
ripple_params = (
    RippleParameters & {"ripple_param_name": key["ripple_param_name"]}
).fetch1("ripple_param_dict")

ripple_detection_algorithm = ripple_params["ripple_detection_algorithm"]
ripple_detection_params    = ripple_params["ripple_detection_params"]
...
ripple_times = RIPPLE_DETECTION_ALGORITHMS[ripple_detection_algorithm](
    ...,
    **ripple_detection_params,
)
```

So `RippleTimesV1.make` is the authoritative reader of the blob shape — if
you ever doubt what's actually inside `ripple_param_dict`, that's the
function to look at, plus an example row:

```python
example = (RippleParameters & {}).fetch(
    "ripple_param_dict", limit=1, as_dict=True
)[0]
print(example)
```

## Why a DataJoint restriction can't do this

DataJoint translates restrictions into SQL `WHERE` clauses on the table's
columns. `ripple_param_dict` is a `BLOB` — MySQL stores the *bytes* of a
pickled Python dict; the server has no idea those bytes contain a
`"ripple_detection_params"` sub-dict with a `"speed_threshold"` float. So
none of these work:

```python
RippleParameters & "speed_threshold < 4.0"                  # No such column
RippleParameters & {"speed_threshold": 4.0}                 # Same — KeyError-ish
RippleParameters & "ripple_param_dict.speed_threshold < 4"  # Not SQL
```

This is a general DataJoint property, not a Spyglass quirk: you can only
restrict on heading attributes (primary key parts and ordinary
non-blob/non-attach columns).

## The pattern that does work: fetch, deserialize, filter in Python

```python
from spyglass.ripple.v1.ripple import RippleParameters

rows = RippleParameters.fetch(as_dict=True)

low_speed_rows = [
    r for r in rows
    if r["ripple_param_dict"]
        .get("ripple_detection_params", {})
        .get("speed_threshold", float("inf")) < 4.0
]

# Just the names, if that's what you want:
low_speed_names = [r["ripple_param_name"] for r in low_speed_rows]
```

Notes on the snippet:

- `RippleParameters` is small (a `dj.Lookup` table of named parameter
  sets), so fetching all rows is cheap. Don't worry about the table-scan
  cost the way you would for a `dj.Computed` results table.
- `.get(..., {})` and `.get(..., float("inf"))` guard against rows that
  predate `speed_threshold` being part of the schema, or use a different
  detection algorithm whose params dict is shaped differently. Drop the
  guards if you're sure every row uses the Kay detector layout.
- If you want a one-liner restriction back into DataJoint to feed
  downstream queries, build it from the names you found:

  ```python
  matching = RippleParameters & [
      {"ripple_param_name": r["ripple_param_name"]} for r in low_speed_rows
  ]
  ```

## TL;DR

- `speed_threshold` is a **blob-internal** field, not a heading column, so
  no DataJoint restriction string can target it.
- Layout: `ripple_param_dict["ripple_detection_params"]["speed_threshold"]`.
- Verify the layout for your own rows by reading one back
  (`fetch("ripple_param_dict", limit=1, as_dict=True)`) or by reading
  `RippleTimesV1.make` in `spyglass/ripple/v1/ripple.py`, which is the
  consumer that defines what keys must be present.
- Filter pattern: `fetch(as_dict=True)` → list-comprehension on the
  deserialized dict → optionally rebuild a restriction from the matching
  primary keys.
