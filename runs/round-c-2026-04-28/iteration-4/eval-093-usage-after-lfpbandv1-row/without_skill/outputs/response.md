# What to do next with a populated `LFPBandV1` row

Once you have an `LFPBandV1` row populated for the theta band, you typically pull the filtered LFP back out as an analysis object and then do something biologically meaningful with it (theta phase, theta power, phase locking, etc.). Here's the natural progression.

## 1. Fetch the filtered NWB / data

`LFPBandV1` is a DataJoint computed table whose payload is an NWB analysis file written by the populate step. The conventional access pattern is:

```python
from spyglass.lfp.analysis.v1 import lfp_band as sgb

key = {
    "nwb_file_name": "...nwb",
    "lfp_merge_id": "...",
    "filter_name": "Theta 5-11 Hz",
    "filter_sampling_rate": 1000,
    "target_interval_list_name": "...",
}

# pynwb ElectricalSeries-like object
lfp_band_obj = (sgb.LFPBandV1 & key).fetch1_dataframe()
# or, lower-level access to the NWB ElectricalSeries:
nwb_obj = (sgb.LFPBandV1 & key).fetch_nwb()[0]
es = nwb_obj["lfp_band"]   # ElectricalSeries
```

`fetch1_dataframe()` returns a pandas DataFrame indexed by time (seconds), with one column per band-filtered electrode — that's usually what you want for downstream analysis. (If your version of Spyglass exposes it via the merge table `LFPBandOutput` instead, fetch through that — same idea.)

## 2. Sanity-check before analyzing

Before computing anything fancy, confirm the obvious:

- **Sampling rate**: `filter_sampling_rate` matches what you asked for (commonly 1000 Hz for theta).
- **Time range**: the DataFrame's index covers the `target_interval_list_name` you intended (e.g., a run epoch), not the whole session.
- **Channels**: the columns are the electrodes you specified in `LFPBandSelection` — typically a CA1 pyramidal-layer reference plus whatever else you selected.
- **Plot a few seconds** of trace and overlay it with the raw LFP from the same channel. The band-filtered trace should look like a clean ~8 Hz oscillation, with amplitude that waxes and wanes during running.

## 3. Compute the things theta is actually used for

This is where you choose based on the science question. The common next moves:

**(a) Theta phase via Hilbert transform.** Take the analytic signal of the band-filtered trace, get instantaneous phase and amplitude:

```python
from scipy.signal import hilbert
import numpy as np

x = lfp_band_obj["<chan>"].to_numpy()
analytic = hilbert(x)
theta_phase = np.angle(analytic)        # radians, -pi..pi
theta_amp   = np.abs(analytic)          # envelope / theta power proxy
```

Use `theta_phase` to:
- Compute spike–theta phase locking (per unit, per cell type) — mean resultant length, Rayleigh test.
- Tag every spike with its theta phase for phase precession analyses against position.
- Define theta cycles (zero-crossings of phase) as the unit of analysis for sequence / replay-during-theta work.

**(b) Theta power / theta-to-delta ratio.** Use `theta_amp` (or `theta_amp**2`) to:
- Detect theta epochs (high theta, low delta) vs LIA / SWR epochs.
- Gate other analyses to "good theta" times — Spyglass typically does this by intersecting interval lists.

**(c) Position-coupled analyses.** Align the theta phase/amplitude time series to `IntervalPositionInfo` (or `TrodesPosInfoV1` etc.) to get phase-by-position, phase precession, theta sequences.

## 4. Persist results back into the pipeline (recommended)

Don't just keep the analysis in a notebook. The Spyglass-native move is to feed `LFPBandV1` into the next computed table that consumes it. Depending on what you're after:

- For ripple work the analogous chain is `LFPBandV1` (ripple band) -> `RippleTimesV1`. For theta there isn't always a single canonical "TimesV1" table, but if your project has one (e.g., a theta-state table, or a phase-locking table), populate that with this `LFPBandV1` key as its upstream parent. That keeps provenance intact.
- If you're doing a one-off analysis, at minimum record the exact `key` dict you fetched with — that's the provenance pointer back to this row.

## 5. Things to verify, not assume

- **Reference scheme**: `LFPBandSelection` lets you set a reference electrode per channel. For theta phase analyses people usually want a common reference (often a CA1 pyramidal-layer channel) so phases are comparable across electrodes. Confirm what's actually in the selection row before interpreting cross-channel phase differences.
- **Filter edges**: the first/last ~1 second of the filtered trace can ring; drop or mask edges if you're analyzing short epochs.
- **Interval intersection**: when you correlate with spikes or position, intersect the LFP band's valid times with the spike/position valid times — don't assume they're identical.

## TL;DR

Fetch the band-filtered trace with `fetch1_dataframe()` (or `fetch_nwb()`), Hilbert-transform it to get instantaneous theta phase and amplitude, sanity-check sampling rate / interval / channels, and then use phase+amplitude for whatever theta-based analysis you're after (spike phase locking, phase precession, theta-state detection). If a downstream computed table consumes `LFPBandV1` in your project, populate that next so the provenance chain stays in DataJoint.
