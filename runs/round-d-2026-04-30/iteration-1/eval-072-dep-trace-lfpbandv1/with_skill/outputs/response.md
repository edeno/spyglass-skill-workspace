# Upstream tables required for `LFPBandV1.populate(key)`

There are two layers of "upstream":

1. **Static FK ancestors** — what DataJoint walks when it computes the ancestor closure of `LFPBandV1`. Every one of these must have a matching row for the FKs to resolve.
2. **Runtime-fetched parents** — tables whose rows `LFPBandV1.make()` reads with `(Table & key).fetch_nwb()` / `.fetch1(...)`. These are *not* declared as FKs of `LFPBandV1`, but `make()` raises if their rows are missing.

For `LFPBandV1.populate(key)` to actually succeed you need **both**.

All evidence below is cited to `src/spyglass/...` in your local checkout.

---

## 1. Direct FK parents of `LFPBandV1`

From `lfp/analysis/v1/lfp_band.py:290-297`:

```
LFPBandV1
  -> LFPBandSelection      # PK FK
  ---
  -> AnalysisNwbfile       # secondary FK
  -> IntervalList          # secondary FK
```

So three direct parents: `LFPBandSelection`, `AnalysisNwbfile`, `IntervalList`.

## 2. `LFPBandSelection` parents (and its part table)

From `lfp/analysis/v1/lfp_band.py:22-39`:

```
LFPBandSelection
  -> LFPOutput.proj(lfp_merge_id='merge_id')                   # PK FK to LFPOutput merge master
  -> FirFilterParameters                                       # PK FK
  -> IntervalList.proj(target_interval_list_name=...)          # PK FK (renamed)
  lfp_band_sampling_rate: int

  class LFPBandElectrode (part):
      -> LFPBandSelection
      -> LFPElectrodeGroup.LFPElectrode                        # PK FK
```

So before you can even insert the selection (and therefore before populate has anything to compute), you need rows in: `LFPOutput` (merge master), `FirFilterParameters`, `IntervalList` (under the `target_interval_list_name`), and `LFPElectrodeGroup.LFPElectrode` part rows for every electrode in the selection.

## 3. `LFPOutput` and its source tables

`LFPOutput` is the LFP merge master (`lfp/lfp_merge.py:16-44`). For a `LFPBandV1` row to populate, the merge entry in `LFPOutput` has to point to *one* of its three part-table sources:

- `LFPOutput.LFPV1` → `LFPV1` (the standard FIR-filtered path)
- `LFPOutput.ImportedLFP` → `ImportedLFP`
- `LFPOutput.CommonLFP` → `CommonLFP` (legacy; explicitly rejected by `set_lfp_band_electrodes`, `lfp_band.py:98`, but `LFPBandV1.make()` itself doesn't reject it)

The standard path (`LFPV1`) is by far the common case. Its FKs (`lfp/v1/lfp.py:44-55`):

```
LFPV1
  -> LFPSelection          # PK FK
  ---
  -> AnalysisNwbfile
  -> IntervalList
```

And `LFPSelection` (`lfp/v1/lfp.py:21-41`):

```
LFPSelection
  -> LFPElectrodeGroup
  -> IntervalList.proj(target_interval_list_name=...)
  -> FirFilterParameters
```

## 4. `LFPElectrodeGroup` and below

From `lfp/lfp_electrode.py:16-26`:

```
LFPElectrodeGroup
  -> Session
  lfp_electrode_group_name

  class LFPElectrode (part):
      -> LFPElectrodeGroup
      -> Electrode
```

## 5. `Electrode` / `ElectrodeGroup` and below

From `common/common_ephys.py:30-92`:

```
ElectrodeGroup
  -> Session
  electrode_group_name
  ---
  -> BrainRegion
  -> [nullable] Probe

Electrode
  -> ElectrodeGroup
  electrode_id
  ---
  -> [nullable] Probe.Electrode
  -> BrainRegion
```

`Probe.Electrode` is a part of `Probe` whose hierarchy is `Probe -> Probe.Shank -> Probe.Electrode` (`common/common_device.py:377-438`), and `Probe -> ProbeType` (`common_device.py:385`). They are nullable on `Electrode` / `ElectrodeGroup`, so they're only required if your session actually has a probe attached.

## 6. `Session` and what it pulls in

From `common/common_session.py:19-34`:

```
Session
  -> Nwbfile                  # PK FK
  ---
  -> [nullable] Subject
  -> [nullable] Institution
  -> [nullable] Lab
```

`Nwbfile` is a top-level Manual table (`common/common_nwbfile.py:45-52`). The lab/subject/institution links are nullable.

## 7. `IntervalList`, `AnalysisNwbfile`, `FirFilterParameters`

- `IntervalList` (`common/common_interval.py:24-32`): `-> Session` + `interval_list_name`. You need *two* `IntervalList` rows for a populate to make sense — the user-supplied `target_interval_list_name`, and the downstream "censored" interval that `LFPBandV1.make()` writes (`lfp_band.py:590-604`). The downstream one is created by `make()` itself; only the upstream `target_interval_list_name` has to pre-exist.
- `AnalysisNwbfile` (`common/common_nwbfile.py:630-641`): `-> Nwbfile`. The actual row for the band file is *created* by `LFPBandV1.make()` via `AnalysisNwbfile().create(...)` (`lfp_band.py:500, 584`); you don't pre-insert it.
- `FirFilterParameters` (`common/common_filter.py:32-70`): top-level Manual, no upstream FK. You need a row keyed by `(filter_name, filter_sampling_rate)` matching the upstream LFP's sampling rate (the helper `set_lfp_band_electrodes` derives `filter_sampling_rate` from the LFP's `lfp_sampling_rate`, `lfp_band.py:120-122, 220`).

## 8. Runtime-only requirement: `Raw`

This one does **not** show up in any FK graph rooted at `LFPBandV1`, but it is required for `LFPBandV1.populate(key)` to succeed via the `LFPV1` path:

`LFPV1.make()` reads `Raw` at runtime (`lfp/v1/lfp.py:68, 72-74`):

```python
rawdata = (Raw & nwbf_key).fetch_nwb()[0]["raw"]
sampling_rate, raw_interval_list_name = (Raw & nwbf_key).fetch1(
    "sampling_rate", "interval_list_name"
)
```

So if you also need to populate `LFPV1` first (which is the normal flow), `Raw` (`common/common_ephys.py:276-285`, `-> Session`, `-> IntervalList`) must have a row for that NWB file. If `LFPV1` is already populated and the corresponding `LFPOutput.LFPV1` merge row exists, then `LFPBandV1.make()` itself only opens the `LFPV1` analysis NWB file (`lfp_band.py:504`), not `Raw` — but the analysis file's existence is downstream of `Raw` having been there at the time `LFPV1` was populated.

This is a general pattern called out in the LFP reference: `Raw` is a "runtime-fetch handle, not a stored pipeline output" — static FK walks alone understate the inputs.

---

## Full upstream closure (deduped)

Combining all of the above, every table whose rows must exist in the database (directly or transitively) for `LFPBandV1.populate(key)` to succeed via the standard `LFPV1` path:

**Direct FK ancestors of `LFPBandV1`:**

| Table | Source | Role |
|---|---|---|
| `LFPBandSelection` | `lfp/analysis/v1/lfp_band.py:22` | direct PK parent |
| `LFPBandSelection.LFPBandElectrode` (part) | `lfp_band.py:34` | per-electrode reference config |
| `LFPOutput` (merge master) | `lfp/lfp_merge.py:16` | parent of LFPBandSelection |
| `LFPOutput.LFPV1` (part) | `lfp_merge.py:23` | resolves merge_id to LFPV1 |
| `LFPV1` | `lfp/v1/lfp.py:45` | source of the LFP being band-filtered |
| `LFPSelection` | `lfp/v1/lfp.py:21` | parent of LFPV1 |
| `LFPElectrodeGroup` | `lfp/lfp_electrode.py:16` | parent of LFPSelection + part-table source |
| `LFPElectrodeGroup.LFPElectrode` (part) | `lfp_electrode.py:22` | parent of LFPBandSelection.LFPBandElectrode |
| `Electrode` | `common/common_ephys.py:73` | parent of LFPElectrodeGroup.LFPElectrode |
| `ElectrodeGroup` | `common/common_ephys.py:31` | parent of Electrode |
| `Session` | `common/common_session.py:19` | parent of ElectrodeGroup, IntervalList, Raw, LFPElectrodeGroup |
| `Nwbfile` | `common/common_nwbfile.py:45` | parent of Session and AnalysisNwbfile |
| `AnalysisNwbfile` | `common/common_nwbfile.py:630` | secondary FK on LFPV1 and LFPBandV1 (auto-created in `make`) |
| `IntervalList` | `common/common_interval.py:24` | secondary FK + `target_interval_list_name` parent on LFPSelection / LFPBandSelection |
| `FirFilterParameters` | `common/common_filter.py:32` | filter parent on LFPSelection and LFPBandSelection |
| `BrainRegion` | `common/common_region.py:9` | required FK on ElectrodeGroup and Electrode (Lookup) |

**Conditionally required (nullable FKs, populated when present):**

| Table | Source | Role |
|---|---|---|
| `Probe`, `Probe.Shank`, `Probe.Electrode` | `common/common_device.py:377, 390, 428` | nullable on ElectrodeGroup/Electrode; required if your session has a probe |
| `ProbeType` | `common/common_device.py:335` | parent of Probe |
| `DataAcquisitionDevice` | (referenced from Probe, nullable) | nullable on Probe |
| `Subject`, `Institution`, `Lab` | `common/common_subject.py`, `common/common_lab.py` | nullable on Session |

**Runtime-fetched (not in FK graph but required for `LFPV1.populate` upstream):**

| Table | Source | Role |
|---|---|---|
| `Raw` | `common/common_ephys.py:276` | `LFPV1.make()` reads raw data + sampling rate at runtime |

---

## How to verify this for your own DB

If you want to verify the actual upstream rows for your `key`, two tools:

```bash
# Static graph (FK closure):
python skills/spyglass/scripts/code_graph.py upstream LFPBandV1 --max-depth 10

# Runtime / live DB (does the row exist?):
python skills/spyglass/scripts/db_graph.py upstream LFPBandV1 --restrict '<your key>'
```

The static `code_graph upstream` will give you exactly the FK-derived list above; the live one tells you which rows are actually present for *your* key. The runtime-only `Raw` dependency won't appear in either graph (it isn't FK-linked) — that's why the LFP reference flags it explicitly.

---

## Practical "have I got everything?" checklist for one `key`

Before calling `LFPBandV1.populate(key)`:

1. `Nwbfile & {"nwb_file_name": f}` — 1 row.
2. `Session & {"nwb_file_name": f}` — 1 row.
3. `IntervalList & {"nwb_file_name": f, "interval_list_name": target_interval_list_name}` — 1 row.
4. `Raw & {"nwb_file_name": f}` — 1 row (only strictly required if `LFPV1` not yet populated).
5. `ElectrodeGroup`, `Electrode` populated for `f`.
6. `LFPElectrodeGroup` + `LFPElectrodeGroup.LFPElectrode` rows for the group used.
7. `FirFilterParameters & {"filter_name": ..., "filter_sampling_rate": raw_sr}` for `LFPV1` AND `FirFilterParameters & {"filter_name": ..., "filter_sampling_rate": lfp_sampling_rate}` for `LFPBandV1`.
8. `LFPSelection` row for the LFP, populated → `LFPV1` row, populated → `LFPOutput.LFPV1` part row exists.
9. `LFPBandSelection` row + `LFPBandSelection.LFPBandElectrode` part rows inserted (use `set_lfp_band_electrodes(...)`, `lfp_band.py:41`).

If any of those is missing you'll get an FK error from `insert1`, or `make()` will raise on the `fetch1` / `fetch_nwb` of the missing row.
