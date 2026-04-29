# Counting `Electrode` rows for `j1620210710_`

Use `len()` on the restricted relation — DataJoint translates that to a `SELECT COUNT(*)` on the server, so no rows are fetched into Python:

```python
from spyglass.common import Electrode

n = len(Electrode & {"nwb_file_name": "j1620210710_.nwb"})
print(n)
```

That single expression is the answer; running it against your DB returns the count for that session.

## Why `len()` and not `.fetch()`

- `len(rel)` issues a `COUNT(*)` — cheap, no row transfer.
- `len(rel.fetch())` (or `len(rel.fetch("KEY"))`) pulls every row over the wire just to take its length. Avoid for anything bigger than a tiny relation.
- `Electrode.describe()` shows the schema, not a count, so it's not a substitute here.

## What the count actually means

`Electrode` is keyed by `(nwb_file_name, electrode_group_name, electrode_id)` (PK inherited from `ElectrodeGroup` plus its own `electrode_id`; verified in `src/spyglass/common/common_ephys.py:73-92`). Each row is **one recording contact** on a probe — not a tetrode, not a shank, not an `ElectrodeGroup`.

So for a 32-tetrode session you should expect ~128 `Electrode` rows (4 contacts per tetrode), not 32. If you actually wanted the number of tetrodes/shanks for that session, count `ElectrodeGroup` instead:

```python
from spyglass.common import ElectrodeGroup

len(ElectrodeGroup & {"nwb_file_name": "j1620210710_.nwb"})
```

## Sanity-check the session name

The `nwb_file_name` PK in `Session` always carries the `.nwb` suffix. If `j1620210710_` is a prefix you remembered without the extension, confirm the exact filename first so the restriction matches:

```python
from spyglass.common import Session

Session & 'nwb_file_name LIKE "j1620210710_%"'   # wildcard discovery
```

Then re-run `len(Electrode & {"nwb_file_name": <found_name>})` with the canonical name.
