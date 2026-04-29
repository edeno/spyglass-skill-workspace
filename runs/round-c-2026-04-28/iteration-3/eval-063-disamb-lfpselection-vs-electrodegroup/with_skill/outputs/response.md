They are **not** interchangeable, and the order is fixed: `LFPElectrodeGroup` must exist **before** you can `LFPSelection.insert1(...)`. Here's the split:

## `LFPElectrodeGroup` — the reusable electrode bundle

Defined in `spyglass/lfp/lfp_electrode.py` as a `dj.Manual` master with a part table:

```python
@schema
class LFPElectrodeGroup(SpyglassMixin, dj.Manual):
    definition = """
    -> Session
    lfp_electrode_group_name: varchar(200)
    """
    class LFPElectrode(SpyglassMixin, dj.Part):
        definition = """
        -> LFPElectrodeGroup
        -> Electrode
        """
```

- PK: `nwb_file_name`, `lfp_electrode_group_name`.
- The **part table** `LFPElectrodeGroup.LFPElectrode` adds one row per electrode in the group (it FKs `Electrode`).
- It just says "for this session, the bundle named X consists of these electrode_ids." No filter, no interval, no sampling rate.
- It's reusable: one group can drive several different LFP runs (different intervals, different filters).

**Build it with the helper, not by hand.** `LFPElectrodeGroup.create_lfp_electrode_group` (`lfp/lfp_electrode.py:28-129`) validates the session, validates each electrode_id against `Electrode`, and inserts master + part inside one transaction so you can't half-create a group:

```python
from spyglass.lfp import LFPElectrodeGroup

LFPElectrodeGroup.create_lfp_electrode_group(
    nwb_file_name=nwb_file,
    group_name="my_lfp_group",
    electrode_list=[0, 1, 2, 3],
)
```

## `LFPSelection` — one populate run's parameters

Defined in `spyglass/lfp/v1/lfp.py:21`:

```python
@schema
class LFPSelection(SpyglassMixin, dj.Manual):
    definition = """
    -> LFPElectrodeGroup
    -> IntervalList.proj(target_interval_list_name='interval_list_name')
    -> FirFilterParameters
    ---
    target_sampling_rate = 1000 : float
    """
```

- PK = `(nwb_file_name, lfp_electrode_group_name, target_interval_list_name, filter_name, filter_sampling_rate)` — the electrode group **plus** which interval to filter **plus** which FIR filter to apply.
- It's a foreign key into `LFPElectrodeGroup`, so the group **must already be inserted** or `LFPSelection.insert1` raises an FK error. That's the ordering you're asking about.
- One `LFPSelection` row corresponds to one `LFPV1.populate(key)` run (`LFPV1` FKs `LFPSelection` directly, `lfp/v1/lfp.py:48-49`).

```python
from spyglass.lfp.v1 import LFPSelection, LFPV1

key = {
    "nwb_file_name": nwb_file,
    "lfp_electrode_group_name": "my_lfp_group",          # must exist in LFPElectrodeGroup
    "target_interval_list_name": "02_r1",                 # must exist in IntervalList
    "filter_name": "LFP 0-400 Hz",                        # must exist in FirFilterParameters
    "filter_sampling_rate": raw_sampling_rate,            # must match Raw's sampling rate
    "target_sampling_rate": 1000,
}
LFPSelection.insert1(key, skip_duplicates=True)
LFPV1.populate(key)
```

## So the flow you should follow

```
1. LFPElectrodeGroup.create_lfp_electrode_group(...)
       -> writes LFPElectrodeGroup (master)
       -> writes LFPElectrodeGroup.LFPElectrode (part, one row per electrode)

2. LFPSelection.insert1({...group_name + interval + filter + rates...})
       -> one row = one upcoming populate run

3. LFPV1.populate(key)
       -> FIR-filters Raw down to target_sampling_rate, writes the analysis NWB
```

Mental model: **`LFPElectrodeGroup` = "which channels"** (a reusable electrode bundle, written once per intended LFP analysis), **`LFPSelection` = "which channels × which time interval × which filter × which output rate"** (one row per populate run). You can have several `LFPSelection` rows pointing at the same `LFPElectrodeGroup` (e.g., the same tetrode bundle filtered over different epochs, or with different filters), but you cannot have an `LFPSelection` without first inserting the group it references.

Two correctness gates worth flagging while you're here:
- `target_interval_list_name` must already exist in `IntervalList` for that nwb_file, or `LFPSelection.insert1` raises a cryptic FK error. Confirm with `IntervalList & {"nwb_file_name": nwb_file}` first.
- `filter_sampling_rate` must match the actual `Raw` sampling rate — `LFPV1.make()` looks up the FIR filter by that rate (`lfp/v1/lfp.py:107-114`). Derive it instead of hard-coding 30000:
  ```python
  from spyglass.common import Raw
  raw_sampling_rate = int(np.round(
      (Raw & {"nwb_file_name": nwb_file}).fetch1("sampling_rate")
  ))
  ```

References: `spyglass/lfp/lfp_electrode.py:16-129` (group + helper), `spyglass/lfp/v1/lfp.py:21-55` (selection + computed table).
