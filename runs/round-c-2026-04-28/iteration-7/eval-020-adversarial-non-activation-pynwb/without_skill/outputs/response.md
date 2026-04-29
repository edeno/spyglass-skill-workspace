# Reading TimeSeries timestamps from an NWB file with pynwb

Open the file with `NWBHDF5IO` in read mode, navigate to the `TimeSeries` object, and access its `.timestamps` attribute. The timestamps come back as an HDF5 dataset; slice with `[:]` to materialize them as a NumPy array.

## Minimal example

```python
from pynwb import NWBHDF5IO

path = "/data/test.nwb"

with NWBHDF5IO(path, mode="r", load_namespaces=True) as io:
    nwbfile = io.read()

    # Behavioral TimeSeries are typically stored under a BehavioralEvents
    # container inside the "behavior" processing module. Adjust the names
    # below to match your file.
    ts = nwbfile.processing["behavior"].data_interfaces["BehavioralEvents"].time_series["my_event"]

    timestamps = ts.timestamps[:]   # shape (n_samples,), seconds from session_start_time
    data = ts.data[:]               # the event values themselves, if you need them

print(timestamps.shape, timestamps.dtype)
print(timestamps[:5])
```

Important: do everything that touches `ts.timestamps` / `ts.data` *inside* the `with` block. Once `io` closes, the underlying HDF5 file is closed and lazy datasets become unreadable. If you need the array later, copy it with `[:]` (which you already did above) before leaving the block.

## If you don't know where the TimeSeries lives

NWB files don't have a single fixed location for behavioral TimeSeries. Common spots:

- `nwbfile.acquisition[name]` — raw acquired signals.
- `nwbfile.processing["behavior"].data_interfaces[...]` — processed behavior; often a `BehavioralEvents`, `BehavioralTimeSeries`, or `BehavioralEpochs` container that itself holds one or more `TimeSeries` in `.time_series`.
- `nwbfile.stimulus[name]` — stimulus presentations.

Quick reconnaissance:

```python
from pynwb import NWBHDF5IO

with NWBHDF5IO("/data/test.nwb", mode="r", load_namespaces=True) as io:
    nwbfile = io.read()

    print("acquisition:", list(nwbfile.acquisition.keys()))
    print("stimulus:   ", list(nwbfile.stimulus.keys()))
    print("processing: ", list(nwbfile.processing.keys()))

    if "behavior" in nwbfile.processing:
        bmod = nwbfile.processing["behavior"]
        print("behavior interfaces:", list(bmod.data_interfaces.keys()))
        for name, iface in bmod.data_interfaces.items():
            # Containers like BehavioralEvents wrap TimeSeries in `.time_series`
            if hasattr(iface, "time_series"):
                print(f"  {name}.time_series: {list(iface.time_series.keys())}")
```

## Two timing conventions to be aware of

A `TimeSeries` stores time in *one* of two ways:

1. **Explicit timestamps** — `ts.timestamps` is a 1-D array of times (seconds), one per sample. Use it directly:

   ```python
   t = ts.timestamps[:]
   ```

2. **Regularly sampled** — `ts.timestamps` is `None`, and time is reconstructed from `ts.starting_time` and `ts.rate` (Hz):

   ```python
   import numpy as np
   n = ts.data.shape[0]
   t = ts.starting_time + np.arange(n) / ts.rate
   ```

A safe helper that handles both:

```python
import numpy as np

def get_times(ts):
    if ts.timestamps is not None:
        return ts.timestamps[:]
    n = ts.data.shape[0]
    return ts.starting_time + np.arange(n) / ts.rate
```

Times are in **seconds**, measured from `nwbfile.session_start_time` (a timezone-aware `datetime`). `ts.timestamps_unit` should report `"seconds"`; if it doesn't, treat that as a red flag and inspect the file before trusting the values.

## Common gotchas

- **Reading after the `with` block closes** — silent `Closed file` errors. Materialize with `[:]` inside the block.
- **`load_namespaces=True`** — needed so any custom NWB extensions (e.g. `ndx-events`, `ndx-franklab-novela`) used by the file load their type definitions before `io.read()`. Without it, extension-typed objects can fail to instantiate.
- **`timestamps` vs `data` length** — for a `TimeSeries` they should match along the first axis. If they don't, the file is malformed; run `nwbinspector /data/test.nwb` or `python -m pynwb.validate /data/test.nwb` to confirm.
- **Behavioral *events* vs behavioral *time series*** — if what you actually have is discrete event times (e.g. lick onsets, reward delivery), they may live in an `ndx-events` `Events` / `LabeledEvents` object rather than a plain `TimeSeries`. Those expose `.timestamps` similarly, but the container API is slightly different — check `type(iface).__name__` if the `.time_series` attribute isn't there.
