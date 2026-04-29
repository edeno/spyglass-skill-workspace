# Primary key of the `Electrode` table

In Spyglass (and any DataJoint table), you can introspect the primary key directly off the class — DataJoint exposes it as the `primary_key` attribute, which returns the list of PK field names.

## One-liner to verify

```python
from spyglass.common import Electrode; print(Electrode.primary_key)
```

(or, if `Electrode` is already imported in the session, just `Electrode.primary_key`.)

## Field names

The primary key of `Electrode` consists of three fields:

1. `nwb_file_name`
2. `electrode_group_name`
3. `electrode_id`

## Why these three (and not others)

`Electrode`'s definition starts with `-> ElectrodeGroup` followed by a new PK attribute `electrode_id`. Because PKs are inherited transitively through `->` references in the PK section:

- `ElectrodeGroup` itself has `-> Session` plus `electrode_group_name`, and `Session` contributes `nwb_file_name`.
- So `Electrode` inherits `nwb_file_name` (from `Session` via `ElectrodeGroup`) and `electrode_group_name` (from `ElectrodeGroup`), then adds its own `electrode_id`.

The order is set by inheritance: `nwb_file_name`, `electrode_group_name`, `electrode_id`.

Note that `Electrode` also has a `-> BrainRegion` reference, but that one lives **below** the `---` separator in the table definition, so `region_id` is a secondary (non-primary) foreign key — it is **not** part of the primary key. Same for `-> [nullable] Probe.Electrode`. Only references that appear above the `---` contribute to the PK.

## Other quick ways to confirm

```python
Electrode.heading.primary_key   # same list, via the heading object
Electrode.describe()            # prints the full table definition; PK fields are above the ---
Electrode.heading               # full heading; PK attributes are flagged
```
