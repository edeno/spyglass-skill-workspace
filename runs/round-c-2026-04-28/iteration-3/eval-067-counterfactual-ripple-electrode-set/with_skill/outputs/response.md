# Counterfactual: adding 3 more CA1 tetrodes to ripple detection

The ripple pipeline is keyed by an electrode subset of `LFPBandV1`'s electrode part-table, which is itself a subset of `LFPElectrodeGroup`. Whether tables upstream of `RippleTimesV1` need to re-populate depends on how far up the chain the new electrodes are already represented. Below is the FK chain (verified in `src/spyglass/ripple/v1/ripple.py:32-43, 182-186` and `src/spyglass/lfp/analysis/v1/lfp_band.py:21-39`), then a per-table verdict.

## FK chain (top → bottom)

```
LFPElectrodeGroup
  └─ LFPElectrodeGroup.LFPElectrode           (per-electrode part)
       │
       ▼
LFPSelection ─► LFPV1 ─► LFPOutput (merge)
                              │
                              ▼
LFPBandSelection                                (FKs LFPOutput.proj(lfp_merge_id='merge_id'))
  └─ LFPBandSelection.LFPBandElectrode         (FKs LFPElectrodeGroup.LFPElectrode)
       │
       ▼
LFPBandV1                                       (computed band-filtered LFP)
       │
       ▼
RippleLFPSelection                              (FKs LFPBandV1)
  └─ RippleLFPSelection.RippleLFPElectrode     (FKs LFPBandSelection.LFPBandElectrode)
       │
       ▼
RippleTimesV1                                   (FKs RippleLFPSelection, RippleParameters,
                                                 PositionOutput.proj(pos_merge_id='merge_id'))
```

`RippleParameters` is a `dj.Lookup` keyed only on `ripple_param_name` (`ripple.py:118`). It carries no electrode information.

## What changes

The minimum change set, assuming the new tetrodes are already in `LFPElectrodeGroup` (i.e. raw LFP for them already exists):

1. **`RippleLFPSelection` + `RippleLFPSelection.RippleLFPElectrode`** — definitely changes. You re-run `RippleLFPSelection.set_lfp_electrodes(lfp_band_key, electrode_list=NEW_LIST, group_name="CA1")` (`ripple.py:52-101`). The staticmethod inserts a (possibly new) row into the master and the corresponding electrode rows into the part. If you reuse the same `group_name="CA1"`, the master PK is unchanged — but the part-table contents (the electrode set) are different, so what `RippleTimesV1.make()` actually pulls is different.

2. **`RippleTimesV1`** — re-populates. This is the table whose contents materially change: its `make()` calls `get_ripple_lfps_and_position_info(key)` which reads the current `RippleLFPElectrode` set, so adding 3 more channels gives a different ripple-band signal stack and therefore different detected events. Note: if you only call `populate()` with the same key on an already-populated row, DataJoint skips it; you typically have to `(RippleTimesV1 & key).delete()` (cautiously) and re-populate, or supply a new `group_name` so the row is a new PK.

## What might or might not change (gated on what's already in LFPBandV1)

- **`LFPBandSelection` + `LFPBandSelection.LFPBandElectrode`** — only changes if the 3 new tetrode channels are NOT already in this part-table. The `RippleLFPElectrode` part FKs `LFPBandSelection.LFPBandElectrode` (`ripple.py:42`), so any electrode you ask `RippleLFPSelection.set_lfp_electrodes` to use must already exist in the band's part-table or the call raises `KeyError` (`ripple.py:88-93`). Two cases:
  - The new electrodes were already band-filtered (common in practice — labs often band-filter the whole `LFPElectrodeGroup`): no `LFPBandSelection` change needed.
  - The new electrodes were NOT band-filtered: you must re-run `LFPBandSelection.set_lfp_band_electrodes(...)` (`lfp_band.py:41`) with the expanded electrode list — possibly under a new selection key — and re-populate `LFPBandV1` against it.

- **`LFPBandV1`** — re-populates only if `LFPBandSelection.LFPBandElectrode` changed. This is the precise gate: the band selection's electrode part-table is a subset of `LFPElectrodeGroup`. If your new tetrode wires are already represented there, `LFPBandV1` already has the band-filtered signal and doesn't re-run.

- **`LFPElectrodeGroup` / `LFPElectrodeGroup.LFPElectrode` / `LFPSelection` / `LFPV1` / `LFPOutput`** — only change if the 3 tetrodes weren't in the original LFP electrode group. The phrasing of the question ("added 3 more CA1 tetrodes to my ripple detection electrode selection") most naturally reads as expanding the ripple selection from a wider already-filtered pool, in which case these tables are untouched. If instead the new tetrodes are channels that were never LFP-filtered for this session, you'd start at `LFPElectrodeGroup` and rebuild the chain top-down.

## What is unaffected

- **`RippleParameters`** — UNAFFECTED. It is a `dj.Lookup` keyed only on `ripple_param_name` with `ripple_param_dict` (blob) holding algorithm + thresholds (`ripple.py:118-179`). It has no electrode dependency. The same parameter row is reused; you do not insert a new parameter set just because the electrode list changed.

- **`FirFilterParameters`** — UNAFFECTED. The "Ripple 150-250 Hz" filter row is keyed on `(filter_name, filter_sampling_rate)` and is not electrode-dependent.

- **`Electrode`, `BrainRegion`, `Session`, `Raw`, `IntervalList`, `Probe`, etc.** — UNAFFECTED. These are the inputs you query to *find* CA1 wires; none of them are downstream of the change.

- **Position pipelines** (`PositionOutput`, `TrodesPosV1`, `DLCPosV1`, `LinearizedPositionOutput`) — UNAFFECTED. `PositionOutput` is an FK *into* `RippleTimesV1`, not downstream of it (`ripple.py:186`). The position merge_id is unchanged by an electrode-list change.

- **Decoding pipelines** (`SortedSpikesDecodingV1`, `ClusterlessDecodingV1`, `DecodingOutput`) — UNAFFECTED unless they directly consume these specific ripple times. Decoding tables FK position + spikes; they don't FK `RippleTimesV1`. A downstream analysis script that *reads* `RippleTimesV1` (e.g. ripple-triggered decoding) will of course see different ripple windows — but the decoding *tables* don't re-populate.

- **MUA / spike sorting / linearization / DLC / behavior pipelines** — UNAFFECTED for the same reason. Nothing in `src/spyglass/` declares an FK whose target chain ends at `RippleTimesV1` (verified by grep — `RippleTimesV1` is referenced only inside `ripple/v1/ripple.py` and a maintenance helper in `lfp_band.py:742-749`, plus its `__init__`).

## Practical workflow

```python
# Assume: nwb_file_name, ripple_target_interval, lfp_band_key already known.
# NEW_ELECTRODES = your existing CA1 list + 3 new tetrode wires.

# 0. Pre-flight: are the new electrodes already in LFPBandSelection's part-table?
from spyglass.lfp.analysis.v1.lfp_band import LFPBandSelection
present = set((LFPBandSelection.LFPBandElectrode & lfp_band_key).fetch("electrode_id"))
missing = set(NEW_ELECTRODES) - present

if missing:
    # Need to re-run LFPBand: extend the band electrode list, re-populate LFPBandV1.
    # (Insert under the same selection key if you want to overwrite, or a new
    # selection key if you want to keep both side-by-side.)
    ...

# 1. Update the ripple selection (idempotent on group_name; new electrode set).
from spyglass.ripple.v1 import RippleLFPSelection, RippleTimesV1
RippleLFPSelection.set_lfp_electrodes(
    lfp_band_key, electrode_list=NEW_ELECTRODES, group_name="CA1",
)

# 2. Re-populate ripple times. If the (RippleLFPSelection PK, ripple_param_name,
#    pos_merge_id) row already exists with the OLD electrode set, populate() will
#    no-op — delete that row first (cautious_delete) or use a new group_name.
RippleTimesV1.populate(populate_key, display_progress=True)
```

## Summary table

| Table | Verdict |
|---|---|
| `LFPElectrodeGroup`, `LFPElectrodeGroup.LFPElectrode` | unchanged unless new wires weren't in the LFP group |
| `LFPSelection`, `LFPV1`, `LFPOutput` | unchanged unless `LFPElectrodeGroup` changed |
| `LFPBandSelection`, `LFPBandSelection.LFPBandElectrode` | unchanged IFF new electrodes already in the band part-table; otherwise re-insert |
| `LFPBandV1` | re-populates IFF `LFPBandSelection` changed (often it doesn't — band selection commonly covers all CA1 wires) |
| `RippleLFPSelection`, `RippleLFPSelection.RippleLFPElectrode` | always changes |
| `RippleParameters` | UNAFFECTED (Lookup; not electrode-dependent) |
| `RippleTimesV1` | re-populates (this is the actual ripple-output change) |
| Position / decoding / MUA / spike-sorting / linearization tables | UNAFFECTED |

Sources verified: `src/spyglass/ripple/v1/ripple.py` (lines 32-43, 52-101, 118-179, 182-190); `src/spyglass/lfp/analysis/v1/lfp_band.py` (lines 21-39, 41+).
