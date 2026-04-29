# Reading TimeSeries timestamps from an NWB file with pynwb

This is a plain pynwb task — no Spyglass involved — so you only need `pynwb.NWBHDF5IO` plus a path into the file's behavior container.

## Minimal example

```python
from pynwb import NWBHDF5IO

path = "/data/test.nwb"

with NWBHDF5IO(path, mode="r") as io:
    nwbfile = io.read()

    # Behavioral events are conventionally stored under the
    # "behavior" processing module, often inside a BehavioralEvents
    # container. Adjust the names to match your file.
    behavior = nwbfile.processing["behavior"]
    events = behavior["BehavioralEvents"]            # NWBDataInterface
    ts = events["my_event_series"]                   # the TimeSeries

    timestamps = ts.timestamps[:]    # load into memory as a NumPy array
    # If you only want a slice, index directly without [:]:
    #   first_100 = ts.timestamps[:100]
```

`ts.timestamps[:]` materializes the dataset to a NumPy array. For very long series, slice instead of pulling the whole thing.

## A couple of things to check first

1. **Where the TimeSeries actually lives.** "Behavioral events as a TimeSeries" can be stored in a few places depending on who wrote the file:
   - `nwbfile.processing["behavior"]["BehavioralEvents"][<name>]` — the standard location for processed event series.
   - `nwbfile.acquisition[<name>]` — if it was written as raw acquisition.
   - `nwbfile.stimulus[<name>]` — if it was written on the stimulus side.

   Print the structure to find it:

   ```python
   with NWBHDF5IO(path, mode="r") as io:
       nwbfile = io.read()
       print(nwbfile)                       # top-level summary
       print(nwbfile.processing.get("behavior"))
       print(list(nwbfile.acquisition))
   ```

2. **`timestamps` vs `starting_time` + `rate`.** A `TimeSeries` stores time in *one* of two ways:
   - explicit `timestamps` (irregular sampling) — what you asked about.
   - `starting_time` + `rate` (regularly sampled) — `timestamps` will be `None`.

   Guard for both:

   ```python
   if ts.timestamps is not None:
       t = ts.timestamps[:]
   else:
       import numpy as np
       n = ts.data.shape[0]
       t = ts.starting_time + np.arange(n) / ts.rate
   ```

3. **Units.** `ts.timestamps_unit` is conventionally `"seconds"` (and `ts.starting_time_unit` likewise). Confirm before mixing with other time bases.

4. **Close the file when you're done.** Using `with NWBHDF5IO(...) as io:` handles that automatically. If you need the array to outlive the `with` block, copy it out (`timestamps = ts.timestamps[:]` already does, since `[:]` returns a NumPy array independent of the HDF5 dataset).

## If the file came from a Spyglass-managed location

(Mentioning this only because it's a common adjacent case.) Spyglass stores raw NWBs under `$SPYGLASS_BASE_DIR/raw/` and analysis NWBs under `$SPYGLASS_BASE_DIR/analysis/`. Reading them with raw pynwb as above works fine; you just don't get Spyglass's helpers (`fetch_nwb`, etc.). If `/data/test.nwb` is actually a Spyglass file and you'd rather go through the table layer, that's a different question — let me know.
