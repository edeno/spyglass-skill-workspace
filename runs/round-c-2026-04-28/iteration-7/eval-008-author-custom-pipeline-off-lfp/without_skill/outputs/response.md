# Custom Spyglass pipeline: per-interval theta/gamma power ratio

## Design summary

You want one row per `(IntervalList entry, LFP entry)` combination, computing a theta/gamma power ratio over that interval window, with the result table behaving like other Spyglass tables (DataJoint schema, `SpyglassMixin`, `populate()`-driven, `fetch1()`-friendly, NWB-aware for the analysis output).

The standard Spyglass pattern for this is a **four-table chain**:

1. **Parameters table** (`Manual`) — knobs: theta band, gamma band, FFT method, etc.
2. **Selection table** (`Manual`) — picks which `(LFP, IntervalList, Parameters)` combos to run.
3. **Computed table** (`Computed` with a `make()`) — does the work, writes one row per Selection entry.
4. (Optional) **Part table** — if you want per-electrode rows under one parent computation.

The selection-then-compute split is the convention in Spyglass (see `LFPSelection` -> `LFPV1`, `RippleParameters` -> `RippleTimesV1`, etc.) and matters because it lets users curate what gets populated without re-engineering the compute step.

## Schema sketch

```python
# src/your_lab/theta_gamma/theta_gamma_ratio.py
import datajoint as dj
import numpy as np
import pandas as pd
import pynwb
from scipy.signal import welch

from spyglass.common import IntervalList                 # parent for interval keys
from spyglass.lfp.v1.lfp import LFPV1                    # parent for LFP data
from spyglass.utils import SpyglassMixin                  # gives fetch_nwb, etc.
from spyglass.utils.dj_helper_fn import fetch_nwb
from spyglass.common.common_nwbfile import AnalysisNwbfile

schema = dj.schema("your_lab_theta_gamma_v1")             # pick your own schema name


# ---------------------------------------------------------------------------
# 1. Parameters
# ---------------------------------------------------------------------------
@schema
class ThetaGammaRatioParams(SpyglassMixin, dj.Manual):
    definition = """
    # Parameter set for theta/gamma power-ratio computation
    theta_gamma_params_name : varchar(64)
    ---
    params : blob   # dict: bands, psd method, nperseg, etc.
    """

    @classmethod
    def insert_default(cls):
        cls.insert1(
            {
                "theta_gamma_params_name": "default",
                "params": {
                    "theta_band_hz": (6.0, 10.0),
                    "gamma_band_hz": (30.0, 80.0),
                    "psd_method": "welch",
                    "nperseg": 1024,
                    "noverlap": 512,
                    "detrend": "constant",
                    "min_interval_duration_s": 1.0,
                },
            },
            skip_duplicates=True,
        )


# ---------------------------------------------------------------------------
# 2. Selection: which (LFP, interval, params) triples to compute
# ---------------------------------------------------------------------------
@schema
class ThetaGammaRatioSelection(SpyglassMixin, dj.Manual):
    definition = """
    # Choose which LFP x interval x params combos to populate
    -> LFPV1
    -> IntervalList
    -> ThetaGammaRatioParams
    """


# ---------------------------------------------------------------------------
# 3. Computed: one row per selection entry
# ---------------------------------------------------------------------------
@schema
class ThetaGammaRatio(SpyglassMixin, dj.Computed):
    definition = """
    # Per-interval theta/gamma power ratio
    -> ThetaGammaRatioSelection
    ---
    analysis_file_name : varchar(255)   # AnalysisNwbfile holding per-electrode arrays
    object_id          : varchar(80)    # NWB object id for the per-electrode table
    mean_theta_power   : float          # mean across electrodes, mean over interval
    mean_gamma_power   : float
    mean_ratio         : float          # mean_theta_power / mean_gamma_power
    n_electrodes       : int
    interval_duration_s: float
    """

    def make(self, key):
        # --- 1. fetch params ---
        params = (ThetaGammaRatioParams & key).fetch1("params")
        theta_lo, theta_hi = params["theta_band_hz"]
        gamma_lo, gamma_hi = params["gamma_band_hz"]

        # --- 2. fetch LFP NWB and interval ---
        lfp_eseries = (LFPV1 & key).fetch_nwb()[0]["lfp"]   # ElectricalSeries
        lfp_data = np.asarray(lfp_eseries.data)              # (n_time, n_elec)
        lfp_ts = np.asarray(lfp_eseries.timestamps)          # (n_time,)
        fs = 1.0 / np.median(np.diff(lfp_ts))

        valid_times = (IntervalList & key).fetch1("valid_times")  # (n_intvl, 2)

        # --- 3. mask LFP to interval ---
        mask = np.zeros_like(lfp_ts, dtype=bool)
        for start, stop in valid_times:
            mask |= (lfp_ts >= start) & (lfp_ts <= stop)
        if mask.sum() < int(params["min_interval_duration_s"] * fs):
            raise ValueError(f"Interval too short for key {key}")

        x = lfp_data[mask, :]                                 # (n_t_in, n_elec)

        # --- 4. PSD per electrode ---
        freqs, psd = welch(
            x, fs=fs, axis=0,
            nperseg=params["nperseg"],
            noverlap=params["noverlap"],
            detrend=params["detrend"],
        )
        # psd shape: (n_freqs, n_elec)

        theta_idx = (freqs >= theta_lo) & (freqs <= theta_hi)
        gamma_idx = (freqs >= gamma_lo) & (freqs <= gamma_hi)

        theta_power = np.trapz(psd[theta_idx], freqs[theta_idx], axis=0)  # (n_elec,)
        gamma_power = np.trapz(psd[gamma_idx], freqs[gamma_idx], axis=0)
        ratio = theta_power / gamma_power                                 # (n_elec,)

        # --- 5. write per-electrode results into AnalysisNwbfile ---
        nwb_file_name = (LFPV1 & key).fetch1("nwb_file_name")
        analysis_file_name = AnalysisNwbfile().create(nwb_file_name)
        per_elec_df = pd.DataFrame(
            {
                "electrode_id": np.asarray(lfp_eseries.electrodes.data[:]),
                "theta_power": theta_power,
                "gamma_power": gamma_power,
                "theta_gamma_ratio": ratio,
            }
        )
        object_id = AnalysisNwbfile().add_pandas_dataframe(
            analysis_file_name, per_elec_df
        )
        AnalysisNwbfile().add(nwb_file_name, analysis_file_name)

        # --- 6. insert summary row ---
        self.insert1(
            {
                **key,
                "analysis_file_name": analysis_file_name,
                "object_id": object_id,
                "mean_theta_power": float(np.mean(theta_power)),
                "mean_gamma_power": float(np.mean(gamma_power)),
                "mean_ratio": float(np.mean(ratio)),
                "n_electrodes": int(x.shape[1]),
                "interval_duration_s": float(mask.sum() / fs),
            }
        )

    def fetch_dataframe(self, key=None):
        """Return the per-electrode results for one row as a DataFrame."""
        key = key or {}
        nwbs = (self & key).fetch_nwb()
        return nwbs[0]["per_electrode"]   # name keyed off how add_pandas_dataframe registers it
```

## Why this shape

- **Three foreign keys via Selection.** Putting `LFPV1`, `IntervalList`, and `ThetaGammaRatioParams` upstream of `ThetaGammaRatioSelection` is what guarantees one row per `(interval, LFP, params)` triple. DataJoint enforces the compound primary key.
- **`SpyglassMixin`.** Gives you `fetch_nwb()`, restricted-permission deletes, and consistent error reporting. All Spyglass-style tables inherit from it.
- **`Computed` + `make(key)`.** `populate()` will iterate over every Selection row that is missing in `ThetaGammaRatio` and call `make` exactly once per. Idempotent and resumable for free.
- **AnalysisNwbfile for per-electrode arrays.** Don't stuff numpy arrays into `blob` columns when they're per-electrode and could be larger; the convention is to write them into an analysis NWB file and store `(analysis_file_name, object_id)` in the table. Summary scalars (`mean_*`) stay in the row so they're queryable in SQL.
- **Schema name with `_v1`.** Spyglass convention; lets you make breaking changes by minting `_v2` rather than mutating definitions in place.

## Things you'll need to decide / wire up

1. **Schema namespacing.** I used `your_lab_theta_gamma_v1`. Pick a name your DataJoint user has CREATE rights on (typically `<labprefix>_<feature>_v<n>`).
2. **Per-electrode vs per-interval granularity.** If you'd rather have one row per `(interval, LFP, electrode)`, promote the per-electrode results into a **part table** under `ThetaGammaRatio`:
   ```python
   class Electrode(SpyglassMixin, dj.Part):
       definition = """
       -> master
       electrode_id : int
       ---
       theta_power : float
       gamma_power : float
       theta_gamma_ratio : float
       """
   ```
   Insert with `self.Electrode.insert([...])` inside `make()`. This is queryable in SQL but bloats the relational store; the AnalysisNwbfile approach scales better.
3. **Interval source.** `IntervalList` is keyed by `(nwb_file_name, interval_list_name)`. Make sure the intervals you want are inserted there (they are, for everything Spyglass already knows about — task epochs, pos intervals, ripple intervals, etc.). If you have custom intervals, insert them into `IntervalList` first; don't make a parallel intervals table.
4. **LFP source.** `LFPV1` is the v1 LFP table; if your lab uses the LFP merge table (`LFPOutput`), point at the merge instead via `LFPOutput` so the user can pick any LFP source. That's a one-line change to the Selection FK.
5. **Numerical hygiene.** I used `np.trapz` over the band — that integrates power across the band rather than just summing PSD bins, which is what you want when `nperseg` changes. Worth keeping. Also worth checking: zero-gamma denominators (mask out, or add eps), NaNs from electrode dropouts, and that `lfp_ts` is monotonic before computing `fs`.
6. **Tests.** Easiest test path: simulate an LFP with a known theta:gamma amplitude ratio, push through `make()` on a tiny `IntervalList`, assert `mean_ratio` is within tolerance. Spyglass tests use `pytest` + ephemeral DataJoint schemas; mirror that.

## Typical usage once it's built

```python
ThetaGammaRatioParams.insert_default()

ThetaGammaRatioSelection.insert(
    (LFPV1 & {"nwb_file_name": "anim01_20240101_.nwb"})
    * (IntervalList & "interval_list_name LIKE 'pos %% valid times'")
    * (ThetaGammaRatioParams & {"theta_gamma_params_name": "default"}),
    skip_duplicates=True,
)

ThetaGammaRatio.populate(reserve_jobs=True, display_progress=True)

df = (ThetaGammaRatio & {"nwb_file_name": "anim01_20240101_.nwb"}).fetch(format="frame")
```

That's the whole loop.
