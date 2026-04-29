# Ephys recording devices for `j1620210710_.nwb`

## Where this lives

A session can have **multiple** data-acquisition (ephys recording) devices,
so Spyglass does not store device on `Session` directly. The mapping lives
in the `Session.DataAcquisitionDevice` **part table**, declared in
`src/spyglass/common/common_session.py:56-61`:

```python
class DataAcquisitionDevice(SpyglassIngestion, dj.Part):  # noqa: F811
    definition = """
    # Part table linking Session to multiple DataAcquisitionDevice entries.
    -> Session
    -> DataAcquisitionDevice
    """
```

Key facts (verified from source):

- The part table inherits `nwb_file_name` from `-> Session` and `data_acquisition_device_name` from `-> DataAcquisitionDevice` (`src/spyglass/common/common_device.py:60-67`).
- `DataAcquisitionDevice` itself is a `dj.Manual` lookup keyed only by `data_acquisition_device_name` — it has **no** `nwb_file_name` column, so do not try to restrict it directly by session.
- Restrict the part table by `nwb_file_name` instead, and use `.fetch()` (not `.fetch1()`) since one session can map to several devices.

## The query

```python
from spyglass.common import Session, DataAcquisitionDevice

nwb_file = "j1620210710_.nwb"

# Names of all ephys acquisition devices used in this session
device_names = (
    Session.DataAcquisitionDevice & {"nwb_file_name": nwb_file}
).fetch("data_acquisition_device_name")

print(device_names)  # array, possibly more than one
```

To pull the full device records (system, amplifier, adc_circuit) joined in:

```python
(
    DataAcquisitionDevice
    & (Session.DataAcquisitionDevice & {"nwb_file_name": nwb_file})
).fetch(as_dict=True)
```

Or as a single relational expression (join part table to its device parent
and pick fields from both):

```python
(
    Session.DataAcquisitionDevice * DataAcquisitionDevice
    & {"nwb_file_name": nwb_file}
).fetch(
    "data_acquisition_device_name",
    "data_acquisition_device_system",
    "data_acquisition_device_amplifier",
    "adc_circuit",
    as_dict=True,
)
```

## Common-mistake guardrails for this query

- Don't write `Session.fetch1("device")` or `Session.fetch1("data_acquisition_device_name")` — `Session`'s heading has no such column (see the `Session` definition at `common_session.py:19-34`).
- Don't write `DataAcquisitionDevice & {"nwb_file_name": nwb_file}` — `DataAcquisitionDevice`'s only PK is `data_acquisition_device_name`; restricting by an unknown attribute silently returns the whole table (Common Mistake #6 in the skill's SKILL.md, "silent no-op on merge masters" — same shape applies to any table whose heading lacks the field).
- Don't reach for `.fetch1()`. Sessions are explicitly designed to hold *multiple* device rows (see the comment in the `Session` definition: "each session can have multiple ... data acquisition devices"). Use `.fetch()`.

## What's actually stored for this NWB file

I cannot return the concrete device names from the live database in this
sandbox — `db_graph.py find-instance` (the canonical runtime check) and
any other Python invocation against the configured DataJoint connection
were not permitted to execute here. To resolve the names yourself, run
either of these from a session with `$SPYGLASS_SRC` set and DataJoint
credentials configured:

```bash
python skills/spyglass/scripts/db_graph.py find-instance \
    --class spyglass.common.Session.DataAcquisitionDevice \
    --restrict '{"nwb_file_name": "j1620210710_.nwb"}' \
    --json
```

or interactively:

```python
from spyglass.common import Session
(Session.DataAcquisitionDevice & {"nwb_file_name": "j1620210710_.nwb"}).fetch(
    "data_acquisition_device_name"
)
```

Cardinality check before trusting the result:

```python
rel = Session.DataAcquisitionDevice & {"nwb_file_name": "j1620210710_.nwb"}
print(len(rel))                       # 0 → not ingested; >=1 → use .fetch()
```

If `len(rel) == 0`, the session row hasn't been ingested into `Session`
yet (or this NWB filename isn't registered in `Nwbfile`); confirm with
`Nwbfile & {"nwb_file_name": "j1620210710_.nwb"}` and, if missing, run
the ingestion path in `references/ingestion.md`.
