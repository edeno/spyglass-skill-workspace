## `LFPSelection` — what kind of table is it?

### DataJoint tier: `dj.Manual`

In Spyglass (`spyglass.lfp.v1.lfp.LFPSelection`), `LFPSelection` is a **DataJoint Manual table** (`@schema` + `class LFPSelection(SpyglassMixin, dj.Manual)`). That means **you (the user) are responsible for inserting rows into it directly** — it is *not* auto-populated by `.populate()`. Manual tables are how Spyglass collects the upstream "I want to compute X with these inputs/parameters" choices from you before a downstream Computed table runs.

So among your four options:

- ❌ Lookup (`dj.Lookup`) — used for fixed reference data like parameter presets that ship with the package.
- ❌ Computed (`dj.Computed`) — populated automatically by a `make()` method.
- ❌ Imported (`dj.Imported`) — populated automatically from external files (e.g. NWB ingest).
- ✅ **Manual (`dj.Manual`) — you `.insert1(...)` into it yourself.**

### Spyglass role: it's a **Selection** table (not a parameter table)

Within Spyglass's own vocabulary, manual tables play one of two roles, and `LFPSelection` is squarely the first:

| Role | What it holds | Naming convention | Example |
|---|---|---|---|
| **Selection table** | A combination of upstream keys that says "compute this thing on this data with these parameters". Primary key is composed of foreign keys to other tables. No new parameter values are defined here. | `<Thing>Selection` | `LFPSelection`, `LFPArtifactDetectionSelection`, `SpikeSortingSelection` |
| **Parameter table** | The actual parameter values (filter coefficients, thresholds, sorter options). Usually a `dj.Manual` or `dj.Lookup` whose primary key is a single name string and whose secondary attribute is a blob/dict of params. | `<Thing>Parameters` / `<Thing>Params` | `FirFilterParameters`, `LFPElectrodeGroup` (electrode list), `ArtifactDetectionParameters` |

`LFPSelection`'s primary key is the cross-product of its upstream keys — typically `LFPElectrodeGroup` (which electrodes), `IntervalList` (which time interval, e.g. a run epoch), and `FirFilterParameters` (which filter to apply). It does *not* itself define any new parameter values; it just **selects** an existing combination of (electrodes × interval × filter) that you want `LFPV1` to actually compute.

### What this means for your workflow

The pattern you follow is:

1. Make sure the upstream tables already have the rows you want to reference:
   - `LFPElectrodeGroup` (and `LFPElectrodeGroup.LFPElectrode` part table) — defines which electrodes go into this LFP.
   - `IntervalList` — the time interval over which to compute.
   - `FirFilterParameters` — the filter preset (e.g. the standard `'LFP 0-400 Hz'` filter that ships with Spyglass).
2. **Insert one row into `LFPSelection`** that picks one key from each of those upstream tables. Roughly:

   ```python
   from spyglass.lfp.v1.lfp import LFPSelection, LFPV1

   key = {
       "nwb_file_name": nwb_file_name,
       "lfp_electrode_group_name": "test",
       "target_interval_list_name": "01_s1",
       "filter_name": "LFP 0-400 Hz",
       "filter_sampling_rate": 30_000,
   }
   LFPSelection.insert1(key, skip_duplicates=True)
   ```
3. Then call `LFPV1.populate(key)` — `LFPV1` is the **Computed** table, it reads your selection row and does the actual filtering/decimation work.

So: insert into `LFPSelection` directly. Don't try to insert into `LFPV1` — that one populates itself from your selection.

### Quick way to confirm on your install

```python
from spyglass.lfp.v1.lfp import LFPSelection
print(type(LFPSelection()).__mro__)   # will show dj.Manual
LFPSelection.heading                  # shows the primary key = upstream FKs only
```

If `dj.Manual` shows up in the MRO and the heading is all foreign keys with no `*_params` blob, you've confirmed both answers: **Manual table, Selection role**.
