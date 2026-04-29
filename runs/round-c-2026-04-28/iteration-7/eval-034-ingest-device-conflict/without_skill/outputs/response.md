# `PopulateException: Data acquisition device properties (system, adc_circuit) do not match`

## What's happening

This is *not* a complaint about the structure or shape of the device object you put in the NWB file — your `Device` is fine. It's a **deduplication / conflict check** in Spyglass's common-device ingestion path.

The relevant table is `DataAcquisitionDevice` in `spyglass.common.common_device`. When Spyglass ingests an NWB file via `Session.populate()` (specifically the `_insert_from_nwbfile` helper for that table), it does the following for each NWB `Device` it finds:

1. It pulls the `name` of the device out of the NWB file (e.g. `"SpikeGadgets"`, `"Trodes"`, `"Intan"`, etc.).
2. It uses that **name as the primary key** in `DataAcquisitionDevice`.
3. It looks up auxiliary properties — typically `data_acquisition_device_system`, `data_acquisition_device_amplifier`, and `adc_circuit` — either from `device.description` parsing, from your `franklab_default_device` config, or from values you've manually inserted into the lookup tables.
4. **If a row with that device name already exists, Spyglass compares the incoming property values to the stored ones. If any non-PK column differs, it raises `PopulateException` with exactly the message you're seeing**, naming the columns that disagree (here: `system` and `adc_circuit`).

So the rejection isn't about the *shape* of the device — it's that Spyglass already has a `DataAcquisitionDevice` row keyed by the same name, and the existing row's `data_acquisition_device_system` / `adc_circuit` values do not match the values your new NWB implies.

## Why "tutorial NWB" hits this

A few common causes, in rough order of likelihood:

1. **You ingested a different tutorial NWB earlier**, or a colleague did, and it inserted a `DataAcquisitionDevice` row with the same `name` (e.g. `"SpikeGadgets"`) but slightly different metadata. The new file has, say, `system="MCU"` and `adc_circuit="Intan"`, but the existing row has `system="SpikeGadgets"` and `adc_circuit=None`. Same name, different fields → conflict.
2. **Your NWB's device `description` parses differently** than what's already in the lookup table. Spyglass's `_add_device` / `_add_data_acquisition_device` logic tries to derive `system`, `amplifier`, `adc_circuit` from the description string and/or from the `ndx-franklab-novela` `DataAcqDevice` extension fields. If the description format changed between tutorial versions you'll get different parsed values for the same device name.
3. **Manual prior insert with placeholder values.** Someone called `DataAcquisitionDevice.insert1(...)` directly with the tutorial's device name and stub fields (e.g. `system="Other"`), and the tutorial NWB now claims a real value.
4. **Case / whitespace drift in `system` or `adc_circuit`** (e.g. `"SpikeGadgets"` vs `"Spike Gadgets"`, or `"Intan"` vs `"intan"`). Spyglass does string equality, not normalization.

## How to diagnose (read-only)

Open a Python session against your DataJoint database and look at what's actually stored vs what your NWB carries.

```python
from spyglass.common import DataAcquisitionDevice
import pynwb

# 1. What's already in the DB for this device name?
DataAcquisitionDevice()                  # see all rows
# Or restrict to the suspected name:
(DataAcquisitionDevice
 & {"data_acquisition_device_name": "<name from your NWB>"}).fetch1()
# Note the values of: data_acquisition_device_system,
#                     data_acquisition_device_amplifier,
#                     adc_circuit

# 2. What does your NWB actually say?
with pynwb.NWBHDF5IO("/path/to/tutorial.nwb", "r", load_namespaces=True) as io:
    nwb = io.read()
    for name, dev in nwb.devices.items():
        print(name, type(dev).__name__, dev.description)
        # If it's an ndx_franklab_novela.DataAcqDevice, also print:
        for attr in ("system", "amplifier", "adc_circuit"):
            print(" ", attr, getattr(dev, attr, "<not set>"))
```

The conflict is whatever pair `(stored value, NWB value)` differs across `system` and `adc_circuit`.

## Fixes

Pick the one that matches the *truth* about the device, then apply it. The conflict is a real-data integrity check, so don't paper over it.

### Option A — your NWB has the wrong / stale metadata, the DB row is correct
Edit the NWB before ingestion so its device matches what the DB says. With `pynwb` you can either rewrite the file or, more commonly, fix it at the source script that built the NWB. If you used `ndx-franklab-novela`'s `DataAcqDevice`, set `system=`, `amplifier=`, `adc_circuit=` to match the stored row.

### Option B — the DB row is wrong / stub, your NWB is correct
Update the existing `DataAcquisitionDevice` row in place. Because `name` is the PK, you don't delete and reinsert (that would cascade-delete dependents); you update the non-PK columns:

```python
from spyglass.common import DataAcquisitionDevice
key = {"data_acquisition_device_name": "<name>"}
DataAcquisitionDevice.update1({**key,
                               "data_acquisition_device_system": "<correct>",
                               "adc_circuit": "<correct>"})
```

If the row has no downstream dependents yet, you can also `(DataAcquisitionDevice & key).delete()` and let `populate()` re-insert from the NWB.

### Option C — they're genuinely different devices that happen to share a name
Rename one. The PK is the device name string, so two physically different acquisition systems must have distinct names. Edit the NWB to give the new device a unique `name` (e.g. append a rig or date suffix) and re-ingest.

### Option D — you don't care about the auxiliary fields for a tutorial run
You can pre-populate `DataAcquisitionDevice` with the values your NWB carries *before* calling `Session.populate()`, or wipe the conflicting row (only safe if nothing downstream references it). For tutorials specifically, a clean DB / fresh schema reset is often the fastest path:

```python
# Last-resort, tutorial-only: wipe and re-ingest.
(DataAcquisitionDevice & {"data_acquisition_device_name": "<name>"}).delete()
```

Don't do this on a shared production DB without checking dependents (`DataAcquisitionDevice.descendants()`).

## TL;DR

The error is Spyglass refusing to silently overwrite a previously-ingested `DataAcquisitionDevice` row whose `system` / `adc_circuit` disagree with what your tutorial NWB claims. Inspect both sides (`DataAcquisitionDevice.fetch()` vs the NWB's `device` fields), decide which is canonical, then either fix the NWB, `update1` the DB row, or rename the device so it gets its own row.
