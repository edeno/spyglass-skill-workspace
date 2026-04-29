# Is `LFPBandV1` a compute table or an output table?

Short answer: **`LFPBandV1` is a compute table.** It is the V1 implementation of the LFP-band filtering step (band-pass filter applied to an upstream LFP series, typically to extract theta, ripple, gamma, etc.). You populate it yourself for each `(nwb_file_name, lfp_merge_id, filter_name, …)` key you care about — there is no upstream pipeline that fills it for you.

## Why "compute" and not "output"

In Spyglass, the convention is roughly:

- **Compute tables** — DataJoint `Computed` (or `Imported`) tables with a `make()` method. You call `.populate(key)` (usually after inserting a selection-table row) and the table writes its result row plus an analysis NWB file.
- **Output / merge tables** — `Merge` tables (subclass of `_Merge` / `SpyglassMixin`) that have **no `make()`**. They just hold a UUID per upstream source so downstream pipelines can consume "the LFP band result" without caring which version produced it. You **insert into them**, you don't populate them.

`LFPBandV1` is the former. In `spyglass.lfp.analysis.v1.lfp_band`:

- It's defined as a `dj.Computed` table with a `make(self, key)` that reads the upstream LFP, applies the band-pass filter described by `LFPBandSelection` / `FirFilterParameters`, writes a new analysis-NWB file with a filtered `ElectricalSeries`, and inserts the resulting row.
- There is a corresponding **selection table** `LFPBandSelection` (with a part table `LFPBandElectrode` for the channels, filter, ref, sampling-rate decimation, etc.). The standard recipe is: insert into `LFPBandSelection` → call `LFPBandV1.populate(key)`.
- The matching **output table** is the merge table `LFPBandOutput` (in `spyglass.lfp.lfp_band_merge` / `lfp_band_output`). It has a part `LFPBandV1` that just references `LFPBandV1`'s primary key. Downstream code (e.g. ripple detection, theta-phase locking) restricts and joins through `LFPBandOutput`, not through `LFPBandV1` directly.

So the rule of thumb:

| Layer | Class | What you do with it |
|---|---|---|
| Selection | `LFPBandSelection` (+ `LFPBandElectrode`) | Insert your params (filter, electrodes, target sampling rate, reference). |
| **Compute** | **`LFPBandV1`** | **`.populate(key)` after the selection row exists.** |
| Output / merge | `LFPBandOutput` | Insert the produced V1 key here so downstream pipelines can find it; this is also what you `restrict` / `merge_get_part` against when reading. |

## What this means for your decision

- If the band-filtered LFP you want **already exists** in the database for your session+filter+electrode set: just **read** it. You can pull the analysis NWB via either `(LFPBandV1 & key).fetch_nwb()` or, more idiomatically, through the merge table:
  ```python
  from spyglass.lfp.lfp_band_merge import LFPBandOutput  # or lfp_band_output, depending on version
  nwb = (LFPBandOutput & key).fetch_nwb()
  ```
- If it **doesn't exist yet** for the filter/electrodes you need, you populate it:
  ```python
  from spyglass.lfp.analysis.v1.lfp_band import LFPBandSelection, LFPBandV1
  from spyglass.lfp.lfp_band_merge import LFPBandOutput

  LFPBandSelection.set_lfp_band_electrodes(
      nwb_file_name=nwb_file_name,
      lfp_merge_id=lfp_merge_id,
      electrode_list=electrode_list,
      filter_name="Theta 5-11 Hz",         # must already exist in FirFilterParameters
      filter_sampling_rate=1000,
      reference_electrode_list=[-1],
      lfp_band_sampling_rate=200,
  )
  key = (LFPBandSelection & {...}).fetch1("KEY")
  LFPBandV1.populate(key)
  LFPBandOutput.insert1({"merge_id": ..., "source": "LFPBandV1", **key}, skip_duplicates=True)
  ```
  (In recent Spyglass the `LFPBandOutput` insert is wrapped for you — check the version you're on; some versions auto-insert into the merge table at the end of `LFPBandV1.make`.)

## Quick sanity checks you can run

To confirm on your install (rather than trusting me):

```python
import spyglass.lfp.analysis.v1.lfp_band as m
import datajoint as dj

print(type(m.LFPBandV1).__mro__)          # should include dj.Computed
print(hasattr(m.LFPBandV1, "make"))       # True  -> compute table
m.LFPBandV1.describe()                    # shows it depends on LFPBandSelection
```

And for the merge/output side:

```python
from spyglass.lfp.lfp_band_merge import LFPBandOutput
print(LFPBandOutput.parts())              # part tables include LFPBandV1
print(hasattr(LFPBandOutput, "make"))     # False -> not a compute table
```

If `LFPBandV1` shows `dj.Computed` + `make` and `LFPBandOutput` shows merge-style parts with no `make`, that's the split: **populate `LFPBandV1`, read through `LFPBandOutput`.**

## TL;DR

`LFPBandV1` = compute table — populate it (after filling `LFPBandSelection`). The corresponding *output* table is `LFPBandOutput`, which is where downstream pipelines look up the result. If you only want to consume an already-computed band-filtered LFP, restrict `LFPBandOutput` and `fetch_nwb()` from there; populate `LFPBandV1` only when the (filter, electrodes, reference, sampling rate) combo you need isn't already in the DB.
