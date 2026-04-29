# Why `Electrode` carries `probe_*` columns, and how to verify it from Python

Two complementary commands together tell the whole story. Run both:

```python
from spyglass.common import Electrode

# (1) The columns Electrode actually carries (what you're seeing)
Electrode().heading.attributes        # dict: name -> Attribute (full info)
# or, equivalently for a quick look:
Electrode.heading                     # printable summary
Electrode.heading.primary_key         # just the PK fields
Electrode.heading.secondary_attributes  # everything below the `---`

# (2) Where those columns come from — the FK declarations
Electrode.parents()                   # table NAMES of every parent (PK + secondary FKs)
Electrode.parents(as_objects=True)    # FreeTable objects you can introspect
```

**Why both?** `heading.attributes` shows the *flattened* schema — every column the table carries, including ones inherited from foreign keys. `parents()` shows the *declarations* that contributed those columns. The `probe_*` fields you noticed live in `heading.attributes` because of one specific FK that shows up in `parents()`. Looking at only one of the two leaves you guessing which parent contributed which column.

You can also run `Electrode.describe()` to see the literal `definition` string with the `-> ...` lines and the `---` divider preserved — that's the most direct way to read the FK declarations without opening the source.

## What you'll find

`Electrode.parents()` lists two parents:

- `ElectrodeGroup` — primary parent (above the `---`); contributes `nwb_file_name` and `electrode_group_name` to Electrode's primary key.
- `Probe.Electrode` — **the part table** of `Probe`, not `Probe` itself. This is the source of your `probe_*` columns.

`heading.attributes` will show `electrode_id` plus the inherited PK fields as primary, and a block of secondary attributes that includes `probe_id`, `probe_shank`, `probe_electrode` (inherited from `Probe.Electrode`'s PK) alongside Electrode's own non-PK fields like `region_id`, `name`, `x`, `y`, `z`, `filtering`, `impedance`, `bad_channel`, `x_warped`, `y_warped`, `z_warped`, `contacts`.

## What the declaration actually looks like

In `src/spyglass/common/common_ephys.py:73-92`, the relevant lines of `Electrode.definition` are:

```text
-> ElectrodeGroup                  # primary FK (above ---)
electrode_id: int                  # own PK field
---
-> [nullable] Probe.Electrode      # secondary, nullable FK (below ---)
-> BrainRegion                     # secondary FK (below ---)
...
```

So the link to probes is `-> [nullable] Probe.Electrode` (file `src/spyglass/common/common_ephys.py:78`), and it sits **below** the `---` divider. Two things follow from that single line:

1. **Secondary, not primary.** Because the line is below `---`, `Probe.Electrode`'s primary keys (`probe_id`, `probe_shank`, `probe_electrode`) become *secondary* attributes of `Electrode`. They appear in `Electrode.heading` (which is exactly why you see `probe_*` columns when you query Electrode), but they are not part of Electrode's primary key. Electrode's PK stays `(nwb_file_name, electrode_group_name, electrode_id)`.
2. **Nullable.** The `[nullable]` modifier means a row in `Electrode` is allowed to have `NULL` for those `probe_*` fields. That's deliberate: it lets a session whose NWB file lacks probe metadata still ingest into `Electrode` — `make()` just leaves `probe_id`/`probe_shank`/`probe_electrode` unset for those rows. With a non-nullable FK, the whole `Electrode.populate()` would fail for any session missing probe metadata.

A common confusion: there is **no** `-> Probe` declaration on `Electrode`. The link is to the *part table* `Probe.Electrode` (defined in `src/spyglass/common/common_device.py:428` as `class Electrode(SpyglassIngestion, dj.Part)` inside `Probe`). Part tables in DataJoint are first-class FK targets, and depending on `Probe.Electrode` rather than `Probe` is what gives `Electrode` rows a specific physical contact (probe + shank + contact id), not just a probe instance.

`ElectrodeGroup` separately has its own `-> [nullable] Probe` (the master, not the part) at `common_ephys.py:38` — that's where the probe-instance link lives. The two probe-related FKs in this schema target different things on purpose: `ElectrodeGroup` says "this group of channels is on this physical probe instance"; `Electrode` says "this individual contact corresponds to this entry in the probe's contact map".

## Sanity-check loop (no source reading required)

```python
from spyglass.common import Electrode

# Are the columns I see actually there?
print(sorted(Electrode().heading.attributes))

# Which fields are PK vs secondary?
print("PK:        ", Electrode.heading.primary_key)
print("Secondary: ", Electrode.heading.secondary_attributes)

# Which declarations contributed those columns?
print(Electrode.parents())                  # names
for p in Electrode.parents(as_objects=True):
    print(p.full_table_name, "->", p.heading.primary_key)

# And the literal definition (shows `---` divider and `[nullable]`)
print(Electrode.describe())
```

If `probe_id`, `probe_shank`, `probe_electrode` show up in `secondary_attributes` (not `primary_key`) and `Probe.Electrode`'s full table name appears in `parents()`, you've confirmed the connection without touching the source. `Electrode.describe()` is the single most informative call here — it reproduces the `definition` string verbatim, including the `---` divider and the `[nullable]` annotation, so you can read the FK declaration directly.

If you'd rather not start a Python session, the skill's bundled source-graph helper gives the same answer offline (each attribute carries `in_pk: true|false` so PK vs secondary is unambiguous):

```bash
python skills/spyglass/scripts/code_graph.py describe Electrode --json
```
