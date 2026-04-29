## `LFPSelection` classification

**DataJoint tier:** **Manual** table.

**Spyglass role:** **Selection** table (not a parameter table).

So yes — you `insert1` rows into it yourself. That's exactly the workflow: insert a key into `LFPSelection`, then call `LFPV1.populate(key)` to fill the corresponding Computed downstream row.

Source: `spyglass.lfp.v1.LFPSelection` (defined in `src/spyglass/lfp/v1/lfp.py`); the LFP reference in this skill lists it as Manual at the "Step 2: Filter Raw Data" entry.

### Manual vs. Lookup vs. Computed vs. Imported (quick refresher)

- **Manual** — you write rows by hand (`.insert1`). User-driven choices.
- **Lookup** — small, mostly-static reference data (parameter sets, filter definitions). Inserted once per site, shared across users.
- **Computed** — populated by `.populate()` from upstream rows; rows produced by `make()`. You don't insert these directly.
- **Imported** — populated like Computed but the data comes from an external file (e.g. an NWB file) rather than being computed.

### Selection vs. Parameter (Spyglass conventions)

- **Parameter** tables hold *the knobs* — named bundles of arguments (e.g. `FirFilterParameters`, `LFPArtifactDetectionParameters`, `RippleParameters`). Typically Lookup tier. You insert a parameter row once per site and reuse it.
- **Selection** tables answer *"which inputs and which parameter set should the next populate run on?"* They cross-join an input identity (an `nwb_file_name` + an electrode group + an interval) with a parameter row. Typically Manual tier. You insert one row per (data, params) combination you want to populate.

`LFPSelection` is the textbook selection table: its primary key combines a session/electrode-group/interval (`nwb_file_name`, `lfp_electrode_group_name`, `target_interval_list_name`) with a filter spec (`filter_name`, `filter_sampling_rate`) plus a downstream output rate (`target_sampling_rate`). It doesn't *define* a filter — it *picks* one for one specific recording slice.

### What you actually insert

```python
from spyglass.lfp.v1 import LFPSelection, LFPV1

key = {
    "nwb_file_name": nwb_file,
    "lfp_electrode_group_name": "my_lfp_group",
    "target_interval_list_name": "02_r1",
    "filter_name": "LFP 0-400 Hz",       # must already exist in FirFilterParameters
    "filter_sampling_rate": 30000,        # must match Raw's sampling rate
    "target_sampling_rate": 1000,
}
LFPSelection.insert1(key, skip_duplicates=True)
LFPV1.populate(key)
```

Two foreign-key prerequisites that bite people on first run:

1. The `filter_name` + `filter_sampling_rate` row must exist in `FirFilterParameters` (Lookup, parameter table). For the broadband default, run `FirFilterParameters().create_standard_filters()` once.
2. The `target_interval_list_name` must exist in `IntervalList` for that `nwb_file_name`. Verify with `(IntervalList & {"nwb_file_name": nwb_file})` first or `LFPSelection.insert1` will throw a cryptic FK error.

Also: `filter_sampling_rate` must match the actual raw sampling rate. Don't hard-code 30000 — derive it:

```python
import numpy as np
from spyglass.common import Raw

raw_rate = int(np.round((Raw & {"nwb_file_name": nwb_file}).fetch1("sampling_rate")))
```

### Where the related tables sit, for contrast

| Table | Tier | Role |
| --- | --- | --- |
| `FirFilterParameters` | Lookup | **Parameter** (filter definitions) |
| `LFPElectrodeGroup` | Manual | Manual input (which electrodes) |
| `IntervalList` | Manual | Manual input (which time interval) |
| **`LFPSelection`** | **Manual** | **Selection** (combines the above) |
| `LFPV1` | Computed | Output of `populate()` from `LFPSelection` |
| `LFPOutput` | Manual (merge master) | Merge layer over `LFPV1` / `ImportedLFP` / `CommonLFP` |
