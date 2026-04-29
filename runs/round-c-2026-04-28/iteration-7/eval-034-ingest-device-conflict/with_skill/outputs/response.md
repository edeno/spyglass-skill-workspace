# `PopulateException: Data acquisition device properties (system, adc_circuit) do not match`

## What's actually happening

This isn't about the device's *shape* (i.e. the schema or fields). It's
about an **identity collision on secondary attributes**.

Spyglass's `DataAcquisitionDevice` table is keyed on
`data_acquisition_device_name` (its primary key). The secondary
attributes — including `data_acquisition_device_system` and
`adc_circuit` — describe *what kind of device* that name refers to.

When `insert_sessions` walks your tutorial NWB:

1. It pulls a device out of `nwb.devices` (or the equivalent metadata
   block).
2. It builds a candidate row for `DataAcquisitionDevice` with that
   name and the secondary fields the NWB provides.
3. It looks up the existing DB row by `data_acquisition_device_name`.
4. A row **already exists** with that same name, but its `system` and
   `adc_circuit` values **differ** from what the NWB carries.

Spyglass refuses to silently overwrite or accept the mismatch — it
raises `PopulateException`. So the ingestion isn't rejecting the
device's structure; it's rejecting the claim that two different
configurations are the same device.

This is documented in the ingestion reference as a common error and is
"common when tutorial NWBs ship with different canonical metadata than
the lab DB" — exactly your situation. Your DB already has a
`DataAcquisitionDevice` populated (likely by a previous lab session or
a prior tutorial run), and the new tutorial NWB labels its device with
the same `data_acquisition_device_name` but slightly different
secondary metadata.

## Diagnose it: see exactly which row(s) clash

Pull the existing row and compare to what the NWB is asserting:

```python
from spyglass.common import DataAcquisitionDevice

# Inspect what's in the DB
DataAcquisitionDevice()                 # all rows
# or, if you know the name from the error / NWB:
DataAcquisitionDevice & {
    "data_acquisition_device_name": "<name from NWB>"
}
```

And read the NWB side directly so you know what Spyglass *would* have
inserted:

```python
import pynwb
with pynwb.NWBHDF5IO("<your_tutorial.nwb>", "r") as io:
    nwb = io.read()
    for name, dev in nwb.devices.items():
        print(name, type(dev).__name__, vars(dev))
```

Compare `system` and `adc_circuit` between the two — those are the
fields the exception called out, so those are the ones that disagree.

## Fix it: pick one of three paths, in order of preference

### 1. Make the NWB match the DB (preferred for tutorial files)

If the existing DB row is correct for your lab, regenerate or rewrite
the tutorial NWB so its device metadata (`system`, `adc_circuit`)
matches. Then re-ingest with `reinsert=True` if the file already
landed partially:

```python
import spyglass.data_import as sgi
sgi.insert_sessions("my_tutorial.nwb", reinsert=True)
```

`reinsert=True` is destructive — it cascades through everything FK'd
to the `Nwbfile` row. Read the "What `reinsert=True` actually does"
note in the ingestion reference before pulling the trigger; if the
ingestion never got past the device step, there shouldn't be much
downstream to lose, but verify with `Session & {"nwb_file_name":
nwb_copy_file_name}` first.

### 2. Rename the device per-session

If the tutorial *should* register a distinct device (it actually is a
different rig/system, or you want it isolated for a sandbox run),
rename it in the NWB before ingesting so it gets its own row:

```python
# in the NWB authoring step, change e.g.
#   device_name = "DataAcquisitionDevice1"
# to
#   device_name = "DataAcquisitionDevice1_tutorial"
```

Then pre-insert the new row explicitly (idempotent, safe to re-run):

```python
from spyglass.common import DataAcquisitionDevice

DataAcquisitionDevice.insert1(
    {
        "data_acquisition_device_name": "DataAcquisitionDevice1_tutorial",
        "data_acquisition_device_system": "<system from your NWB>",
        "adc_circuit": "<adc_circuit from your NWB>",
        # ...other secondary fields per the table heading
    },
    skip_duplicates=True,
)
```

Confirm the schema before inserting — `DataAcquisitionDevice.heading`
will print the exact attribute names and types so you don't guess.

### 3. Do **not** delete the existing DB row to "force" the match

I want to flag this explicitly because it's tempting and it's the
wrong move:

```python
# DO NOT do this
(DataAcquisitionDevice & {"data_acquisition_device_name": name}).delete()
```

Other ingested sessions almost certainly FK to that
`DataAcquisitionDevice` row. Cautious-delete on a SpyglassMixin will
fight you on this (and rightly), and `super_delete` would cascade-
remove evidence linking real recordings to their hardware. Keep the
DB row authoritative; change the NWB side or rename.

## Why it tripped you specifically

Two recurring patterns produce this error with tutorial files:

- **Tutorial NWBs from upstream Spyglass / LorenFrankLab repos** ship
  with canonical device names like `"DataAcquisitionDevice1"` that
  collide with whatever your lab inserted under the same name during
  prior setup or notebook runs.
- **Spec drift between Spyglass versions**: a newer Spyglass may
  populate `adc_circuit` from a field that older NWB authoring
  scripts left blank or set to a different string. The DB still has
  the older row from when you first set up.

Either way, the path is the same: identify the conflicting fields
with the queries above, then choose match-the-DB (rewrite NWB) or
isolate-the-tutorial (rename device).

## After you fix it

Re-ingest, then verify the device landed and was associated with the
session — remembering Spyglass appends `_` to the filename on
ingestion (the "copy filename" rule):

```python
from spyglass.common import Session, DataAcquisitionDevice
from spyglass.utils.nwb_helper_fn import get_nwb_copy_filename

nwb_copy_file_name = get_nwb_copy_filename("my_tutorial.nwb")

Session & {"nwb_file_name": nwb_copy_file_name}
DataAcquisitionDevice & {
    "data_acquisition_device_name": "<the name from the NWB>"
}
```

If the `Session` row appears, the device step passed.
