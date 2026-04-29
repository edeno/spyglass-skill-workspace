# `LFPElectrodeGroup` vs `LFPSelection`

These are not interchangeable — they live at different stages of the LFP
pipeline, and `LFPElectrodeGroup` must be populated **before**
`LFPSelection`, because `LFPSelection` has a foreign key into it.

## What each table represents

### `LFPElectrodeGroup` (in `spyglass.lfp.lfp_electrode`)

A **reusable bundle of electrodes** for a session that you intend to treat
together as an LFP group. It's a `dj.Manual` master table with a single
part table `LFPElectrodeGroup.LFPElectrode` that holds the actual
electrode IDs.

```python
# definition (paraphrased from the source)
LFPElectrodeGroup:
    -> Session
    lfp_electrode_group_name: varchar(200)

LFPElectrodeGroup.LFPElectrode:           # part table
    -> LFPElectrodeGroup
    -> Electrode
```

Per session you can have many groups (e.g. one per tetrode, one per
brain region, one "all CA1 channels", etc.), and each group can be
re-used by many downstream selections — different filters, different
intervals, different sampling rates — without re-declaring the channel
list each time.

### `LFPSelection` (in `spyglass.lfp.v1.lfp`)

The **per-`populate()` ticket** for LFPV1. It's a `dj.Manual` table whose
primary key is the *combination* of:

```python
LFPSelection:
    -> LFPElectrodeGroup                                # which channels
    -> IntervalList.proj(target_interval_list_name=...) # which time window
    -> FirFilterParameters                              # which FIR filter
    ---
    target_sampling_rate = 1000 : float
```

So one row of `LFPSelection` says: "take *this* electrode group, *these*
times, run *this* filter at *this* output rate." `LFPV1` (the computed
table) inherits `LFPSelection` 1:1 — `LFPV1.populate()` walks through
each `LFPSelection` row and produces filtered LFP for it.

## Order to insert

1. **First — create the electrode group.** The supported helper is
   `LFPElectrodeGroup.create_lfp_electrode_group(...)`, which is a
   staticmethod that inserts the master row *and* the per-electrode rows
   in `LFPElectrodeGroup.LFPElectrode` inside a transaction:

   ```python
   from spyglass.lfp.lfp_electrode import LFPElectrodeGroup

   LFPElectrodeGroup.create_lfp_electrode_group(
       nwb_file_name="mysession_.nwb",
       group_name="ca1_ref_group",
       electrode_list=[0, 1, 2, 3],   # electrode_ids that exist in Electrode
   )
   ```

   You *can* also `LFPElectrodeGroup.insert1(...)` followed by
   `LFPElectrodeGroup.LFPElectrode.insert([...])` by hand, but the
   helper validates the session, validates the electrode IDs against
   the `Electrode` table, dedupes, and wraps both inserts in a
   transaction — strongly preferred.

2. **Then — pick that group + interval + filter for one populate run.**

   ```python
   from spyglass.lfp.v1 import LFPSelection, LFPV1

   sel_key = {
       "nwb_file_name": "mysession_.nwb",
       "lfp_electrode_group_name": "ca1_ref_group",
       "target_interval_list_name": "01_s1",      # an existing IntervalList row
       "filter_name": "LFP 0-400 Hz",             # a FirFilterParameters row
       "filter_sampling_rate": 30000,             # match the Raw rate
       "target_sampling_rate": 1000,
   }
   LFPSelection.insert1(sel_key, skip_duplicates=True)

   LFPV1.populate(sel_key)
   ```

   Because `LFPSelection` has `-> LFPElectrodeGroup`, DataJoint will
   refuse `LFPSelection.insert1(...)` if the matching
   `(nwb_file_name, lfp_electrode_group_name)` row doesn't already
   exist in `LFPElectrodeGroup`. That's the foreign-key constraint
   enforcing the order.

## Mental model

- **`LFPElectrodeGroup` = "what channels to ever consider together."**
  Typically one (or a few) per session, defined once, reused.
- **`LFPSelection` = "compute LFP for *this* group on *this* interval
  with *this* filter, right now."** One row per intended `LFPV1.populate()`
  job. If you want to recompute the same channels with a different
  filter or on a different epoch, you add another `LFPSelection` row
  but you do **not** create a new `LFPElectrodeGroup`.

So: insert into `LFPElectrodeGroup` (via
`create_lfp_electrode_group`, which writes both the master and the
`LFPElectrodeGroup.LFPElectrode` part table) first, then
`LFPSelection.insert1(...)`, then `LFPV1.populate(...)`.
