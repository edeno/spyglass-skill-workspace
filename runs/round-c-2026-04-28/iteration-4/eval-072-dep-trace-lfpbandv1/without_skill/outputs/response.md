# Upstream tables `LFPBandV1` transitively depends on

Reconstructed from the Spyglass schema (`src/spyglass/lfp/analysis/v1/lfp_band.py` and the LFP/common chain it pulls from). Walking foreign keys upstream from a populated `LFPBandV1` row:

## Direct parent
- `LFPBandSelection`

## `LFPBandSelection` parents
- `LFPOutput` (merge table)
- `FirFilterParameters`
- `IntervalList`

## `LFPOutput` (parts — the row points to exactly one)
- `LFPOutput.LFPV1`  → `LFPV1`
- `LFPOutput.ImportedLFP` → `ImportedLFP`

## `LFPV1` parents
- `LFPSelection`

## `LFPSelection` parents
- `LFPElectrodeGroup`
- `IntervalList`
- `FirFilterParameters`

## `LFPElectrodeGroup` parents (incl. part `LFPElectrodeGroup.LFPElectrode`)
- `Electrode`
- `Nwbfile`

## `IntervalList` parents
- `Session`

## `Electrode` parents
- `ElectrodeGroup`
- `Probe.Electrode`  → `Probe`
- `BrainRegion`

## `ElectrodeGroup` parents
- `Session`
- `Probe`

## `Probe` parents
- `ProbeType`
- `Probe.Shank`, `Probe.Electrode` (part tables of `Probe` itself)

## `Session` parents (incl. part tables `Session.Experimenter`, `Session.DataAcquisitionDevice`)
- `Nwbfile`
- `Subject`
- `LabMember`
- `Lab`
- `Institution`
- `DataAcquisitionDevice`
- `CameraDevice`

## `DataAcquisitionDevice` parents
- `DataAcquisitionDeviceSystem`
- `DataAcquisitionDeviceAmplifier`

## Roots
- `Nwbfile` (PK = `nwb_file_name`; no FK parents)

---

## Flat list (transitive upstream set)

- `LFPBandSelection`
- `LFPOutput` (+ `LFPOutput.LFPV1`, `LFPOutput.ImportedLFP`)
- `LFPV1`
- `ImportedLFP`
- `LFPSelection`
- `LFPElectrodeGroup` (+ `LFPElectrodeGroup.LFPElectrode`)
- `FirFilterParameters`
- `IntervalList`
- `Electrode`
- `ElectrodeGroup`
- `Probe` (+ `Probe.Electrode`, `Probe.Shank`)
- `ProbeType`
- `BrainRegion`
- `Session` (+ `Session.Experimenter`, `Session.DataAcquisitionDevice`)
- `Nwbfile`
- `Subject`
- `LabMember`
- `Lab`
- `Institution`
- `DataAcquisitionDevice`
- `DataAcquisitionDeviceSystem`
- `DataAcquisitionDeviceAmplifier`
- `CameraDevice`

---

## Caveat / verification

This list is reconstructed from training-time recall of the Spyglass schema, not from a live `dj.Diagram` walk. The exact set drifts across Spyglass versions — minor part-tables and lookup tables (especially around `Lab`/`Institution`/device parts and any `ImportedLFP` analog) may differ on your install.

To confirm against your actual schema:

```python
import datajoint as dj
from spyglass.lfp.analysis.v1 import LFPBandV1

# Visual: show 20 levels of ancestors
dj.Diagram(LFPBandV1) - 20

# Programmatic: walk the FK graph
conn = LFPBandV1.connection
deps = conn.dependencies
deps.load()

def ancestors(table_full_name, seen=None):
    seen = seen or set()
    for parent in deps.parents(table_full_name):
        if parent in seen:
            continue
        seen.add(parent)
        ancestors(parent, seen)
    return seen

names = ancestors(LFPBandV1.full_table_name)
for n in sorted(names):
    print(n)
```

That gives you the authoritative, version-correct set for the row you actually have.
