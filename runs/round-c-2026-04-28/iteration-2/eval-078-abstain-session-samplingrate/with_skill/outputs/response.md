No — that fetch1 will not work. `Session` does not have a `sampling_rate` column, so DataJoint will raise:

```
DataJointError: unknown attribute 'sampling_rate'
```

## Why

`Session` (in `spyglass.common.common_session`) is purely a session-metadata table. Its definition is:

```
-> Nwbfile
---
-> [nullable] Subject
-> [nullable] Institution
-> [nullable] Lab
session_id = NULL: varchar(200)
session_description: varchar(2000)
session_start_time: datetime
timestamps_reference_time: datetime
experiment_description = NULL: varchar(2000)
```

(`src/spyglass/common/common_session.py:19-34`). No ephys parameters live here.

You can verify this yourself — `Session.heading` is the canonical primitive for "what columns does this table actually have?":

```python
from spyglass.common import Session

print(Session.heading)              # full schema
print(Session.heading.names)        # just the column names — quick membership check
# 'sampling_rate' in Session.heading.names  -> False
# Session.describe() also prints the source definition
```

## Where `sampling_rate` actually lives

The raw-ephys sampling rate is a secondary attribute on `Raw` (in `spyglass.common.common_ephys`):

```
-> Session
---
-> IntervalList
raw_object_id: varchar(40)
sampling_rate: float    # Sampling rate calculated from data, in Hz
comments: varchar(2000)
description: varchar(2000)
```

(`src/spyglass/common/common_ephys.py:276-285`). Because `Raw`'s primary key is just `-> Session` (i.e. `nwb_file_name`), restricting on the file alone is unique, so `fetch1` is safe:

```python
from spyglass.common import Raw

rate = (Raw & {"nwb_file_name": "j1620210710_.nwb"}).fetch1("sampling_rate")
```

That returns the float directly (Hz). If you'd rather pull it from the underlying NWB ElectricalSeries via the SpyglassMixin path, `Raw().fetch_nwb({"nwb_file_name": "j1620210710_.nwb"})[0]["raw"].rate` works too — same value, just routed through the NWB object.

I haven't run this against your DB, so I'm not asserting a numeric Hz value — `Raw.heading` confirms the column type is `float`, but the actual rate for `j1620210710_.nwb` needs a fetch.
