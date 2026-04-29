# Inspecting why `Electrode` carries `probe_*` columns

You don't need to read the source — DataJoint exposes the schema graph
on every table class. Two complementary calls give you the full
picture:

## 1. What columns does `Electrode` carry?

```python
from spyglass.common import Electrode

# Every attribute on the table, including ones inherited via FKs:
Electrode.heading
# Or as a dict keyed by column name:
Electrode().heading.attributes
```

`heading` is DataJoint's resolved column list. The `probe_*` fields you
are seeing (`probe_id`, `probe_shank`, `probe_electrode`) appear here
even though `Electrode.definition` doesn't list them by name —
DataJoint copies the primary key of any FK target into the child's
heading. That's why columns "appear out of nowhere": they're inherited
from a parent table.

For each attribute you can also see whether it is part of the primary
key, whether it is nullable, and which type it is:

```python
for name, attr in Electrode().heading.attributes.items():
    print(name, "PK" if attr.in_key else "  ",
          "NULL" if attr.nullable else "    ",
          attr.type)
```

That alone will already show you that `probe_id`, `probe_shank`,
`probe_electrode` are **secondary** (not in PK) and **nullable**.

## 2. Which tables contributed those columns?

```python
Electrode.parents()             # list of parent table names (strings)
Electrode.parents(as_objects=True)  # parent table classes
```

`parents()` lists every table whose primary key is referenced by a
foreign key in `Electrode.definition`. You'll see at least:

- `ElectrodeGroup` — the primary parent (above the `---` divider, so
  its PK becomes part of `Electrode`'s PK).
- `Probe.Electrode` — note the dotted name: this is the **part table**
  `Electrode` *of the master table* `Probe`, not `Probe` itself. Its
  PK (`probe_id`, `probe_shank`, `probe_electrode`) is what showed up
  in `heading`.
- `BrainRegion` — contributing `region_id`.

A nice one-liner to confirm the link:

```python
import datajoint as dj
dj.Diagram(Electrode) - 1 + 1   # show 1 hop up and down
# or just:
dj.Diagram(Electrode)
```

You can also walk the FK metadata directly if you want to see the
declaration flags (nullable / primary):

```python
# Foreign-key declarations as DataJoint sees them:
Electrode.foreign_keys           # newer DJ; on older versions:
Electrode.heading.foreign_keys   # equivalent path
```

Each entry tells you the referenced table, whether it's a primary
(above-`---`) FK or secondary (below-`---`) FK, and whether the
attribute is nullable.

## What you'll find — and why

Putting `heading` and `parents()` together you'll see:

- `Probe.Electrode` is a **secondary** (below-`---`) **nullable**
  foreign key on `Electrode`. In the actual definition this is the
  one-line declaration `-> [nullable] Probe.Electrode`.
- "Secondary" means the `probe_*` columns are *not* part of
  `Electrode`'s primary key — `Electrode` is keyed by
  `(nwb_file_name, electrode_group_name, electrode_id)` (inherited
  from `ElectrodeGroup`), not by probe identity.
- "Nullable" means an `Electrode` row is allowed to have NULL in
  `probe_id` / `probe_shank` / `probe_electrode`. So if a session is
  ingested without probe metadata in its NWB file, `Electrode` still
  populates — the probe link is optional.
- The FK points at the **part table** `Probe.Electrode`, not at
  `Probe` directly. `Probe.Electrode` is the per-contact part of the
  `Probe` master, and its PK is `(probe_id, probe_shank,
  probe_electrode)`. That is exactly the triple of `probe_*` columns
  you noticed in `Electrode`.

So the "why" is: Spyglass wants every electrode contact to *optionally*
identify which physical probe contact it corresponds to, but doesn't
want to *require* probe metadata for ingestion. A nullable secondary
FK to the `Probe.Electrode` part table expresses exactly that — the
columns ride along in `Electrode`'s heading via FK inheritance, but
each row may leave them NULL.

## Quick reference — what to run

```python
from spyglass.common import Electrode
import datajoint as dj

Electrode.heading                        # all columns (inherited included)
Electrode().heading.attributes           # same, dict form
Electrode.parents()                      # who contributed those columns
dj.Diagram(Electrode)                    # visual neighborhood
```

`heading` answers "what columns are there"; `parents()` answers "where
did they come from". Together they let you verify FK relationships
without opening `common_ephys.py`.
