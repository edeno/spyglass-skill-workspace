# How many Electrode rows does `j1620210710_` have?

Spyglass uses DataJoint, where every table class behaves like a relation you can restrict and then ask for its length without materializing the rows. Use `len()` on the restricted relation:

```python
from spyglass.common import Electrode

n = len(Electrode & {"nwb_file_name": "j1620210710_.nwb"})
print(n)
```

`len(<relation>)` issues a `SELECT COUNT(*)` against the database — it does not pull all rows into Python the way `.fetch()` would. Equivalent forms:

```python
(Electrode & {"nwb_file_name": "j1620210710_.nwb"}).__len__()
# or, if you'd rather see it as a count call:
len(Electrode & "nwb_file_name = 'j1620210710_.nwb'")
```

Avoid this pattern (it pulls every row across the wire just to throw them away):

```python
# DON'T — fetches all rows then counts in Python
len((Electrode & {"nwb_file_name": "j1620210710_.nwb"}).fetch())
```

## What the count actually means

`common.Electrode` has one row **per recording contact**, keyed by `(nwb_file_name, electrode_group_name, electrode_id)`. So the number you get back is the total contact count for that session, not:

- the number of **ElectrodeGroups** (shanks / probes / tetrodes — those live in `ElectrodeGroup`),
- the number of **tetrodes** (one tetrode = one ElectrodeGroup with 4 contacts),
- the number of **shanks** or **probes**.

Concrete example: a 32-tetrode recording has 32 `ElectrodeGroup` rows but `4 × 32 = 128` `Electrode` rows. If you wanted tetrode/group counts instead, you'd restrict the matching upstream table:

```python
from spyglass.common import ElectrodeGroup
len(ElectrodeGroup & {"nwb_file_name": "j1620210710_.nwb"})
```

## Sanity-check it before trusting the number

If the count looks off, peek at a few rows to confirm the file actually ingested the way you expect:

```python
(Electrode & {"nwb_file_name": "j1620210710_.nwb"}).fetch(
    "electrode_group_name", "electrode_id", as_dict=True, limit=5
)
```

and verify the session is actually present in `Nwbfile` / `Session` first — if `j1620210710_.nwb` was never inserted, the count will silently be `0` rather than raising.
