# Upstream dependencies of `LFPBandV1`

For `LFPBandV1.populate(key)` to succeed, every ancestor of `LFPBandV1` in the DataJoint dependency graph must already have the matching entries the `key` resolves to. Below is the full upstream tree, walked from `LFPBandV1` outward, derived from the table `definition`s in the local Spyglass source.

## 1. Direct parents (from the `definition` block)

`LFPBandV1` (`spyglass.lfp.analysis.v1.lfp_band.LFPBandV1`, schema `lfp_band_v1`):

```
-> LFPBandSelection              # the LFP band selection (the populate key)
---
-> AnalysisNwbfile               # output analysis NWB file
-> IntervalList                  # final interval list of valid times
lfp_band_object_id: varchar(40)
```

So its direct upstream tables are:

- `LFPBandSelection` (in `spyglass.lfp.analysis.v1.lfp_band`, schema `lfp_band_v1`)
- `AnalysisNwbfile` (in `spyglass.common.common_nwbfile`, schema `common_nwbfile`)
- `IntervalList` (in `spyglass.common.common_interval`, schema `common_interval`)

Note: `AnalysisNwbfile` and `IntervalList` are referenced in the secondary attributes — `make()` creates the analysis file and writes a "lfp band ... Hz" interval list during populate, then inserts. So you don't have to pre-populate those rows yourself for `LFPBandV1`; `make()` does it. The rows you must have *before* calling populate are the ones referenced in the primary key, i.e. all ancestors of `LFPBandSelection`.

## 2. `LFPBandSelection` (Manual) — the populate key

```
-> LFPOutput.proj(lfp_merge_id='merge_id')   # the LFP merge id to be filtered
-> FirFilterParameters                        # the filter
-> IntervalList.proj(target_interval_list_name='interval_list_name')
lfp_band_sampling_rate: int
---
min_interval_len = 1.0: float
```

Plus its part table:

```
LFPBandSelection.LFPBandElectrode:
  -> LFPBandSelection
  -> LFPElectrodeGroup.LFPElectrode
  reference_elect_id = -1: int
```

So directly upstream of `LFPBandSelection` (and its part):

- `LFPOutput` (the LFP merge table, `spyglass.lfp.lfp_merge`, schema `lfp_merge`)
- `FirFilterParameters` (`spyglass.common.common_filter`, schema `common_filter`)
- `IntervalList` (`spyglass.common.common_interval`, schema `common_interval`)
- `LFPElectrodeGroup.LFPElectrode` (part of `LFPElectrodeGroup`, `spyglass.lfp.lfp_electrode`, schema `lfp_electrode`)

## 3. `LFPOutput` (merge table) and its sources

```
LFPOutput:
  merge_id: uuid
  ---
  source: varchar(32)
```

with part tables:

- `LFPOutput.LFPV1`  -> `LFPV1`
- `LFPOutput.ImportedLFP` -> `ImportedLFP`
- `LFPOutput.CommonLFP` -> `common_ephys.LFP`

For a given `lfp_merge_id`, exactly one of those part tables holds the underlying row, and that part's parent must exist. Most users go through `LFPV1`:

### `LFPV1` (`spyglass.lfp.v1.lfp.LFPV1`, schema `lfp_v1`)

```
-> LFPSelection
---
-> AnalysisNwbfile
-> IntervalList
lfp_object_id: varchar(40)
lfp_sampling_rate: float
```

### `LFPSelection` (`spyglass.lfp.v1.lfp.LFPSelection`, schema `lfp_v1`)

```
-> LFPElectrodeGroup
-> IntervalList.proj(target_interval_list_name='interval_list_name')
-> FirFilterParameters
---
target_sampling_rate = 1000 : float
```

So upstream of `LFPV1`:

- `LFPSelection`
  - `LFPElectrodeGroup` (and its part `LFPElectrode`)
  - `IntervalList`
  - `FirFilterParameters`
- `AnalysisNwbfile` (created by `LFPV1.make`)
- `IntervalList` (interval list `lfp_<group>_<target_interval>_valid_times` written by `make`)

`LFPV1.make` also reads from `Raw` (`spyglass.common.common_ephys.Raw`) — not a foreign key in `LFPV1`'s definition, but Raw must exist for the session, otherwise `LFPV1.populate` fails (and you wouldn't have an `LFPOutput.LFPV1` row).

Alternatives instead of `LFPV1`: `ImportedLFP` or `common_ephys.LFP` (legacy `CommonLFP`). Each has its own ancestor chain; the chain below for `LFPV1` is the standard path.

## 4. `LFPElectrodeGroup` and `LFPElectrode`

`LFPElectrodeGroup` (`spyglass.lfp.lfp_electrode`, schema `lfp_electrode`):

```
-> Session
lfp_electrode_group_name: varchar(200)
```

Part table:

```
LFPElectrodeGroup.LFPElectrode:
  -> LFPElectrodeGroup
  -> Electrode
```

So upstream:

- `Session` (`spyglass.common.common_session.Session`)
- `Electrode` (`spyglass.common.common_ephys.Electrode`)

## 5. Bottom of the stack — common tables

- `Electrode` -> `ElectrodeGroup` (+ `BrainRegion`, optional `Probe.Electrode`)
- `ElectrodeGroup` -> `Session` (+ `BrainRegion`, optional `Probe`)
- `Raw` (used by `LFPV1.make`) -> `Session`, `IntervalList`
- `Session` -> `Nwbfile` (+ optional `Subject`, `Institution`, `Lab`)
- `IntervalList` -> `Session`
- `AnalysisNwbfile` -> `Nwbfile`
- `Nwbfile` — root (Manual table holding the NWB file path)
- `FirFilterParameters` — root (no FKs)
- `BrainRegion` — Lookup, no FK upstream

## 6. Consolidated checklist — what must exist in the DB before `LFPBandV1.populate(key)`

For the `key` to resolve, every row below must already be present:

1. `Nwbfile` row for the session's `nwb_file_name`.
2. `Session` row for that `nwb_file_name`. (Brings in `Subject`, `Institution`, `Lab` if non-null.)
3. `BrainRegion` rows for any electrode group / electrode regions (auto-added by `ElectrodeGroup.make` / `Electrode.make`).
4. Optionally `Probe` / `Probe.Electrode` rows (nullable in `ElectrodeGroup` / `Electrode`).
5. `ElectrodeGroup` rows for that session.
6. `Electrode` rows for that session.
7. `IntervalList` rows for that session, including:
   - the raw-data valid times entry used by `Raw` (typically `"raw data valid times"`),
   - the user-specified `target_interval_list_name` you passed into `LFPSelection` and again into `LFPBandSelection`,
   - the `lfp_<group>_<target>_valid_times` entry that `LFPV1.make` writes (auto-created during the LFP populate, must be present before `LFPBandV1.populate`).
8. `Raw` row for the session (so `LFPV1.make` can pull raw data).
9. `FirFilterParameters` rows for both:
   - the LFP filter at the raw sampling rate (used by `LFPV1.make`), and
   - the band filter at the LFP sampling rate (used by `LFPBandV1.make` — `filter_sampling_rate` in the band selection equals the LFP sampling rate, see `LFPBandSelection.set_lfp_band_electrodes`).
10. `LFPElectrodeGroup` row for the session, plus `LFPElectrodeGroup.LFPElectrode` rows for every channel you want filtered.
11. `LFPSelection` row referencing the LFPElectrodeGroup, IntervalList target, and FirFilterParameters.
12. `LFPV1` row populated for that selection (`LFPV1.populate(...)`).
13. `LFPOutput` row (and `LFPOutput.LFPV1` part row) — `LFPV1.make` inserts this for you at the end of populate.
14. `AnalysisNwbfile` rows — `LFPV1.make` and `LFPBandV1.make` create these themselves; you don't pre-populate.
15. `LFPBandSelection` master row + `LFPBandSelection.LFPBandElectrode` part rows (use `LFPBandSelection.set_lfp_band_electrodes(...)` to insert both atomically).

If steps 1-14 are done and step 15 has a row matching `key`, then `LFPBandV1.populate(key)` has everything it needs.

## 7. How to verify on a live database

Once your `dj_local_conf.json` is loaded and you've imported `LFPBandV1`, the cleanest live verification is DataJoint's diagram and ancestor APIs:

```python
from spyglass.lfp.analysis.v1.lfp_band import LFPBandV1
import datajoint as dj

# Visual: full upstream graph
dj.Diagram(LFPBandV1) - 4   # show ancestors up to depth 4

# Programmatic: every ancestor full-table-name
for name in LFPBandV1.ancestors():
    print(name)

# For a specific populated key, restrict each ancestor and confirm non-empty:
key = (LFPBandV1 & "your restriction").fetch1("KEY")
for tbl in [LFPBandSelection, LFPOutput, LFPV1, LFPSelection,
            LFPElectrodeGroup, LFPElectrodeGroup.LFPElectrode,
            FirFilterParameters, IntervalList, Electrode, ElectrodeGroup,
            Raw, Session, Nwbfile]:
    print(tbl.__name__, len(tbl & key))
```

`LFPBandV1.ancestors()` (DataJoint built-in) is authoritative — it returns every table whose entries `LFPBandV1` transitively depends on, including parts and merge-table parts. The list above is what you should see, modulo the alternative LFP sources (`ImportedLFP`, `common_ephys.LFP`) in the `LFPOutput` merge that you may or may not be using.

## Source references

- `/Users/edeno/Documents/GitHub/spyglass/src/spyglass/lfp/analysis/v1/lfp_band.py` — `LFPBandSelection`, `LFPBandSelection.LFPBandElectrode`, `LFPBandV1`
- `/Users/edeno/Documents/GitHub/spyglass/src/spyglass/lfp/lfp_merge.py` — `LFPOutput` and its part tables
- `/Users/edeno/Documents/GitHub/spyglass/src/spyglass/lfp/v1/lfp.py` — `LFPSelection`, `LFPV1`
- `/Users/edeno/Documents/GitHub/spyglass/src/spyglass/lfp/lfp_electrode.py` — `LFPElectrodeGroup`, `LFPElectrodeGroup.LFPElectrode`
- `/Users/edeno/Documents/GitHub/spyglass/src/spyglass/common/common_ephys.py` — `ElectrodeGroup`, `Electrode`, `Raw`
- `/Users/edeno/Documents/GitHub/spyglass/src/spyglass/common/common_session.py` — `Session`
- `/Users/edeno/Documents/GitHub/spyglass/src/spyglass/common/common_nwbfile.py` — `Nwbfile`, `AnalysisNwbfile`
- `/Users/edeno/Documents/GitHub/spyglass/src/spyglass/common/common_interval.py` — `IntervalList`
- `/Users/edeno/Documents/GitHub/spyglass/src/spyglass/common/common_filter.py` — `FirFilterParameters`
