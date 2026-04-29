# `Electrode` primary key

## One-liner to verify

```python
from spyglass.common import Electrode
Electrode.primary_key
```

DataJoint exposes the PK fields as a plain `list[str]` on the class itself
(equivalent to `Electrode.heading.primary_key`). No restriction or fetch
is needed — this is a schema introspection, so it works whether or not the
table has any rows.

## Field names (exactly three)

```python
['nwb_file_name', 'electrode_group_name', 'electrode_id']
```

That's the full PK — no other fields.

## Why those three (and not `region_id`)

Source: `spyglass/common/common_ephys.py:73` —

```python
class Electrode(SpyglassMixin, dj.Imported):
    definition = """
    -> ElectrodeGroup
    electrode_id: int                      # the unique number for this electrode
    ---
    -> [nullable] Probe.Electrode
    -> BrainRegion
    name = "": varchar(200)
    ...
    """
```

Reading the DataJoint definition:

- Everything **above** the `---` divider is the primary key.
- `-> ElectrodeGroup` inherits `ElectrodeGroup`'s PK, which is
  `(nwb_file_name, electrode_group_name)` — so `Electrode` picks up both.
- `electrode_id: int` is `Electrode`'s own added PK field.
- Everything **below** `---` is a secondary attribute. That includes the
  FK `-> BrainRegion` (which adds `region_id` as a *secondary* dependent
  attribute, not a PK component), plus `name`, `x`, `y`, `z`, `filtering`,
  `impedance`, `bad_channel`, the `_warped` coords, and `contacts`.

So `region_id` is a foreign key to `BrainRegion` but is **not** part of
`Electrode`'s primary key — a single electrode is identified by which NWB
file and electrode group it belongs to plus its `electrode_id`, regardless
of what brain region it ends up tagged with.

## Related introspection one-liners

```python
Electrode.primary_key          # ['nwb_file_name', 'electrode_group_name', 'electrode_id']
Electrode.heading.names        # all fields (PK + secondary)
Electrode.heading.secondary_attributes  # everything below the --- divider
Electrode.describe()           # prints the full schema definition
```
