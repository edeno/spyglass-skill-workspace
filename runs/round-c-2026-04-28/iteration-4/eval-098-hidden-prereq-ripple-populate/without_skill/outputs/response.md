# Prerequisites for populating `RippleTimesV1`

`RippleTimesV1` lives in `spyglass.ripple.v1.ripple` and sits near the end of a chain of LFP- and position-derived tables. To populate it for the first time, every table upstream in its `make()` dependency graph must already have rows for the keys you intend to use.

Below are the tables that must already be populated. I've grouped them by which sub-pipeline they belong to.

## 1. The ripple-band LFP must already exist

`RippleTimesV1` is a downstream consumer of LFP filtered to the ripple band. That requires the LFP -> LFP Band chain:

- **`Session`** (and therefore `Nwbfile`, `IntervalList`, `LabMember`, `Lab`, etc.) — the standard NWB-ingest prerequisites must be populated first.
- **`LFPElectrodeGroup`** + **`LFPElectrodeGroup.LFPElectrode`** — selection of which electrodes contribute to the LFP.
- **`LFPSelection`** — selection key (session + electrode group + interval + filter).
- **`LFPV1`** (in the `lfp_merge.LFPOutput` merge) populated, and inserted into the `LFPOutput` merge table.
- **`FirFilterParameters`** — must contain a band-pass FIR filter named for the ripple band (typically `"Ripple 150-250 Hz"`) for the relevant sampling rate. If you haven't run `FirFilterParameters().add_filter(...)` for that band/sampling rate, `LFPBandSelection.set_lfp_band_electrodes()` will fail.
- **`LFPBandSelection`** + **`LFPBandSelection.LFPBandElectrode`** — set via `LFPBandSelection().set_lfp_band_electrodes(nwb_file_name, lfp_merge_id, electrode_list, filter_name, filter_sampling_rate, ripple_band_interval_list_name, reference_electrode_list)`.
- **`LFPBandV1`** — populated for that selection. This is what `RippleLFPSelection` actually points at.

## 2. Position must already exist

Ripple detection in V1 takes head speed as an input so it can mask out movement periods. That requires:

- **`PositionOutput`** (the position merge table) populated for the relevant interval. Concretely, one of `TrodesPosV1` / `DLCPosV1` / `CommonPos` must be populated and merged into `PositionOutput`. You will need the resulting `pos_merge_id` (a.k.a. `PositionOutput`'s primary key) when you build the `RippleTimesV1` key.

## 3. The ripple-specific selection tables

These are the tables you actually populate by hand right before `RippleTimesV1.populate()`:

- **`RippleParameters`** — holds the detector parameters (algorithm name, speed threshold, minimum duration, z-score threshold, etc.). A `"default"` row ships with the package via `insert_default()` but you should confirm it exists (`RippleParameters() & {"ripple_param_name": "default"}`). Add a custom row if you want non-default thresholds.
- **`RippleLFPSelection`** — one row keyed by `(nwb_file_name, lfp_band_filter_name, target_interval_list_name, filter_name, filter_sampling_rate, electrode_group_name, ...)` plus the `lfp_band_electrode_list_name` from `LFPBandV1`.
- **`RippleLFPSelection.RippleLFPElectrode`** — the part table listing exactly which electrodes from the `LFPBandV1` selection are used for ripple detection. This is normally populated via `RippleLFPSelection.set_lfp_electrodes(key, electrode_list=...)`.

## 4. Putting it together

The `make()` of `RippleTimesV1` does roughly:

1. `(LFPBandV1 & key).fetch_nwb()` — pulls the ripple-band-filtered LFP. So `LFPBandV1` must be populated for this key.
2. `(RippleLFPSelection.RippleLFPElectrode & key).fetch(...)` — pulls the chosen electrodes. So that part table must have rows.
3. `(RippleParameters & key).fetch1("ripple_param_dict")` — pulls thresholds.
4. `(PositionOutput & {"merge_id": key["pos_merge_id"]}).fetch1_dataframe()` — pulls head speed. So `PositionOutput` must contain that `merge_id`.
5. `(IntervalList & {"interval_list_name": key["target_interval_list_name"]}).fetch1("valid_times")` — the analysis interval must already exist.

If any of those upstream rows are missing, `populate()` raises `DataJointError` ("no entries to populate") for the missing-selection cases, or a `KeyError` / `fetch1` "Cannot fetch exactly one entry" for the missing-merge-id / missing-parameter cases.

## Minimum checklist before calling `RippleTimesV1.populate(key)`

- [ ] `Session` / `Nwbfile` ingested.
- [ ] `IntervalList` row for `target_interval_list_name` exists.
- [ ] `FirFilterParameters` has the ripple band filter at the right sampling rate.
- [ ] `LFPSelection` -> `LFPV1` populated and inserted into `LFPOutput` merge.
- [ ] `LFPBandSelection` (+ part) set, `LFPBandV1` populated.
- [ ] `PositionOutput` has a merge_id for the same interval (via `TrodesPosV1` or `DLCPosV1`).
- [ ] `RippleParameters` has the `ripple_param_name` you want (`"default"` ships with Spyglass).
- [ ] `RippleLFPSelection` row inserted, and `RippleLFPSelection.RippleLFPElectrode` populated via `set_lfp_electrodes`.

Once all of those are in place, `RippleTimesV1.populate(key)` will run.

## Caveat on evidence

I could not run the validator or fetch the live Spyglass source in this environment (Bash and WebFetch were denied), so I'm answering from my working knowledge of the Spyglass `ripple/v1/ripple.py` and `lfp/v1/lfp_band.py` modules and the standard tutorials. Before relying on the exact key names above, verify with:

```python
RippleTimesV1.describe()        # shows the FK chain
RippleTimesV1.parents()         # immediate parents
dj.Diagram(RippleTimesV1) - 3   # walk three levels up
```

The two non-obvious ones — the `PositionOutput` merge_id and the requirement that the right ripple-band FIR filter already be in `FirFilterParameters` — are the most common reasons a first-time `RippleTimesV1.populate()` silently inserts nothing.
