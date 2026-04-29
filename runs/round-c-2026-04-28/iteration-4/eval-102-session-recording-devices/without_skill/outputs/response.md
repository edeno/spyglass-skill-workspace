# What ephys recording devices were used in `j1620210710_.nwb`?

To determine the ephys recording devices used in `j1620210710_.nwb`, I would need to inspect the NWB file directly, since recording device metadata is stored within the file itself. Here is how I would approach it.

## Approach

NWB files store device information in two main places relevant to ephys:

1. **`nwbfile.devices`** — a dict of `Device` objects (the physical hardware: amplifiers, headstages, acquisition systems, probes).
2. **`nwbfile.electrode_groups`** — each `ElectrodeGroup` references the `Device` it belongs to. The electrodes table also has a `group` column linking each channel to its electrode group (and thus its device).

## Code to read the devices

```python
import pynwb

with pynwb.NWBHDF5IO("j1620210710_.nwb", mode="r", load_namespaces=True) as io:
    nwbfile = io.read()

    # 1. Top-level devices
    print("=== Devices ===")
    for name, device in nwbfile.devices.items():
        print(f"{name}: {type(device).__name__}")
        # Standard Device fields
        print(f"  description: {getattr(device, 'description', None)}")
        print(f"  manufacturer: {getattr(device, 'manufacturer', None)}")
        # ndx-franklab-novela Probe / DataAcqDevice extra fields
        for attr in ("probe_type", "probe_id", "num_shanks",
                     "contact_side_numbering", "contact_size",
                     "system", "amplifier", "adc_circuit"):
            if hasattr(device, attr):
                print(f"  {attr}: {getattr(device, attr)}")

    # 2. Electrode groups -> which device each group uses
    print("\n=== Electrode groups ===")
    for name, eg in nwbfile.electrode_groups.items():
        print(f"{name}: device={eg.device.name}, location={eg.location}")

    # 3. Per-electrode device usage (sanity check)
    if nwbfile.electrodes is not None:
        et = nwbfile.electrodes.to_dataframe()
        print("\n=== Electrodes by group ===")
        print(et.groupby(et["group"].apply(lambda g: g.name)).size())
```

## Spyglass-specific context

The filename `j1620210710_.nwb` follows the Frank Lab convention (`<subject><YYYYMMDD>_.nwb`, here subject `j16`, date `2021-07-10`). Frank Lab NWB files typically use the `ndx-franklab-novela` extension, which defines:

- **`DataAcqDevice`** — the acquisition system (commonly `"SpikeGadgets"` with system `"MCU"`/`"ECU"`, amplifier `"Intan"`, ADC `"Intan"`).
- **`Probe`** (subclass of `Device`) — the physical probe (e.g., `"tetrode_12.5"`, polymer probes, or NeuroPixels), with shanks and electrodes as sub-containers.
- **`Header`** device — a SpikeGadgets metadata blob, not a recording device per se.

For a typical Frank Lab tetrode recording from 2021, you would expect to see:

- One `DataAcqDevice` such as `SpikeGadgets` (Intan amplifier/ADC, MCU/ECU system).
- One or more `Probe` entries of type `tetrode_12.5` (32 tetrodes = 128 channels is the common rig configuration).

But I cannot confirm the actual contents of *this specific file* without opening it.

## What is unknown without the file

- The exact device names, manufacturers, probe types, and counts.
- Whether this session used tetrodes, polymer probes, or a mix.
- Sampling rate and channel count (in `ElectricalSeries.rate` / electrodes table length).

## If you have Spyglass ingested

If this NWB has been inserted into a Spyglass database, you can also query:

```python
from spyglass.common import Nwbfile, Probe, Electrode, ElectrodeGroup

nwb_file_name = "j1620210710_.nwb"

# Probes used in this session
(Probe & (Electrode & {"nwb_file_name": nwb_file_name})).fetch("KEY", as_dict=True)

# Electrode groups and their devices
(ElectrodeGroup & {"nwb_file_name": nwb_file_name}).fetch(as_dict=True)
```

`spyglass.common.Probe` stores `probe_type`, `probe_description`, `num_shanks`, and `contact_side_numbering`; `ElectrodeGroup` joins the device/probe to channels.

## Bottom line

I do not have access to `j1620210710_.nwb` in this environment, so I cannot enumerate the actual devices. Run the snippet above against the file (or query the Spyglass tables if it's ingested) and the `nwbfile.devices` dict plus `electrode_groups` will give you the authoritative answer. Based on Frank Lab conventions for that era, the most likely answer is **SpikeGadgets (Intan-based DAQ) + tetrode probes**, but treat that as a hypothesis until verified against the file.
