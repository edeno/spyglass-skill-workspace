# Prerequisites for `RippleTimesV1.populate()`

`RippleTimesV1` is a Computed table whose foreign keys are declared at `src/spyglass/ripple/v1/ripple.py:184–186` as:

- `-> RippleLFPSelection`
- `-> RippleParameters`
- `-> PositionOutput.proj(pos_merge_id='merge_id')`

Each of those FKs is itself the tip of an upstream chain that must already have rows. Walking the chain backward, here is the full set of tables that must contain matching rows before `RippleTimesV1.populate(key)` will produce output for your session.

## Direct parents of `RippleTimesV1`

1. **`RippleLFPSelection`** (and its part `RippleLFPSelection.RippleLFPElectrode`) — populated via `RippleLFPSelection.set_lfp_electrodes(lfp_band_key, electrode_list=..., group_name="CA1")` (`ripple.py:53`). The static method writes both the master and the part in one call.

2. **`RippleParameters`** — Lookup table; call `RippleParameters().insert_default()` (`ripple.py:144`) to insert the `"default"` and `"default_trodes"` presets, or insert your own `ripple_param_name` row.

3. **`PositionOutput`** (merge master) with a row reachable via the appropriate part table — typically `PositionOutput.TrodesPosV1` or `PositionOutput.DLCPosV1`. The merge key arrives at `RippleTimesV1` projected as `pos_merge_id`. Do not restrict the merge master directly by `nwb_file_name` — resolve `merge_id` through the part.

## Upstream of `RippleLFPSelection`

`RippleLFPSelection` itself foreign-keys to `LFPBandV1`, and its part FKs to `LFPBandSelection.LFPBandElectrode`. So you also need rows in:

4. **`LFPBandSelection`** and **`LFPBandSelection.LFPBandElectrode`** — selection rows for the band filter.

5. **`LFPBandV1`** — populated **with a ripple-band filter**. `RippleLFPSelection.validate_key` rejects any band whose `filter_name` does not contain `"ripple"` (`ripple.py:46–50`). The canonical filter is `filter_name="Ripple 150-250 Hz"` with `band_edges=[140, 150, 250, 260]`.

6. **`FirFilterParameters`** — must contain the ripple-band filter row (registered via `FirFilterParameters().add_filter(...)`) before `LFPBandV1` can populate.

7. **`LFPOutput`** (merge master) with an upstream LFP source — typically **`LFPV1`** (and its **`LFPSelection`** / **`LFPElectrodeGroup`** / **`LFPElectrodeGroup.LFPElectrode`** rows). `LFPBandSelection` foreign-keys to `LFPOutput` via `lfp_merge_id`.

## Upstream of `PositionOutput`

For the position branch, the part you choose dictates the chain. For Trodes (most common):

8. **`PositionOutput.TrodesPosV1`** ← **`TrodesPosV1`** (Computed) ← **`TrodesPosSelection`** ← **`RawPosition`** + **`TrodesPosParams`** (`position/v1/position_trodes_position.py:113`).

For DLC, the analogous chain ends at `PositionOutput.DLCPosV1` and the DLC pipeline upstream.

## Common-to-everything

9. **`Session`** (and therefore a successful `insert_sessions(...)` for the NWB file), plus **`IntervalList`** entries for both the ripple target interval and the position interval. `RippleTimesV1.make()` intersects the LFP-band interval with the position interval at run time (`ripple.py:288`); both must exist.

10. **`Electrode`** / **`ElectrodeGroup`** / **`BrainRegion`** — populated by NWB ingestion; you'll restrict against these to choose CA1 wires for `electrode_list`.

## Quick checklist before calling `RippleTimesV1.populate(key)`

```text
Session  +  IntervalList (ripple_target_interval, position_interval)
   |
   +-- LFPElectrodeGroup(.LFPElectrode) -> LFPSelection -> LFPV1 -> LFPOutput
   |        |
   |        +-- FirFilterParameters("Ripple 150-250 Hz")
   |        +-- LFPBandSelection(.LFPBandElectrode) -> LFPBandV1
   |             |
   |             +-- RippleLFPSelection(.RippleLFPElectrode)   [via set_lfp_electrodes]
   |
   +-- RawPosition + TrodesPosParams -> TrodesPosSelection -> TrodesPosV1 -> PositionOutput
   |
   +-- RippleParameters  [insert_default()]
```

If any of those rows is missing, `populate()` will either silently produce zero new rows (the upstream restriction matches nothing) or raise on the FK / `validate_key` / `fetch1` step. Verify each tier with a quick `len(Table & key)` before calling `populate`.

## Sources consulted

- `/Users/edeno/Documents/GitHub/spyglass-skill/skills/spyglass/SKILL.md`
- `/Users/edeno/Documents/GitHub/spyglass-skill/skills/spyglass/references/ripple_pipeline.md`
- Cited line numbers refer to `src/spyglass/ripple/v1/ripple.py` and `src/spyglass/position/v1/position_trodes_position.py` in the Spyglass repo (as recorded in the reference file).
