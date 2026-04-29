# Custom theta/gamma power-ratio pipeline — schema sketch

You're authoring a new analysis that consumes existing LFP and produces one row per `(LFP entry, interval, params)`. That's a textbook "extending an existing pipeline" case in Spyglass — you FK-ref the upstream merge table (`LFPOutput`) plus `IntervalList` plus a `Parameters` table, and write the per-interval ratios out via `AnalysisNwbfile`.

A few decisions before any code:

## Decisions

1. **No new merge table.** You have one implementation, not multiple interchangeable backends. Skip the `*Output` merge layer; downstream tables can FK-ref your `Computed` directly. (Custom-pipeline non-negotiable #5.)
2. **Schema name must be `<database_user>_<suffix>`.** MySQL grants only let you write to schemas prefixed with your DataJoint username. If your `dj.config["database.user"]` is `edeno`, use e.g. `edeno_theta_gamma`. Do **not** use `spyglass_*`, `lfp_*`, or any of the lab-shared names (`behavior`, `common`, `decoding`, `figurl`, `lfp`, `linearization`, `mua`, `position`, `ripple`, `sharing`, `spikesorting`) — `dj.schema(...)` will refuse with a permission error.
3. **FK upstream = `LFPOutput` (the merge master), not `LFPV1`.** That way the same code works whether the LFP came from `LFPV1`, `ImportedLFP`, or `CommonLFP`. You retrieve the LFP DataFrame inside `make()` via `(LFPOutput & key).fetch1_dataframe()`.
4. **One row per (LFP entry × interval × params).** The PK is the union of upstream FKs. DataJoint enforces uniqueness automatically — no extra unique index needed.
5. **`AnalysisNwbfile` for the per-time-bin ratio trace; scalar summaries can live in DataJoint columns.** If you only ever store one mean ratio per interval, you can skip `AnalysisNwbfile` entirely; if you store the time-resolved ratio across the interval, write it to scratch and store the object_id.
6. **`SpyglassMixin` first in MRO.** Always — method overrides break otherwise.

## Schema sketch

```python
import datajoint as dj

from spyglass.common import IntervalList
from spyglass.common.common_nwbfile import AnalysisNwbfile
from spyglass.lfp import LFPOutput
from spyglass.utils import SpyglassMixin

schema = dj.schema("edeno_theta_gamma")  # <database_user>_<suffix>


@schema
class ThetaGammaRatioParams(SpyglassMixin, dj.Lookup):
    """Frequency bands + smoothing for the theta/gamma ratio.

    Stored as a Lookup so parameter sets are baked into the class
    and the same name maps to the same numbers across re-runs.
    """

    definition = """
    theta_gamma_params_name: varchar(32)
    ---
    theta_gamma_params: blob
    """
    contents = [
        [
            "default",
            {
                "theta_band_hz": (6.0, 10.0),
                "gamma_band_hz": (30.0, 80.0),
                "smoothing_s": 0.25,    # boxcar / Gaussian sigma
                "min_interval_s": 0.5,  # skip intervals shorter than this
            },
        ],
        [
            "slow_gamma",
            {
                "theta_band_hz": (6.0, 10.0),
                "gamma_band_hz": (20.0, 50.0),
                "smoothing_s": 0.25,
                "min_interval_s": 0.5,
            },
        ],
    ]


@schema
class ThetaGammaRatioSelection(SpyglassMixin, dj.Manual):
    """One row per (LFP merge entry, interval, params) you want to compute.

    FK to LFPOutput (the merge master) lets the same selection accept
    LFPV1, ImportedLFP, or CommonLFP-sourced LFPs uniformly.
    """

    definition = """
    -> LFPOutput
    -> IntervalList
    -> ThetaGammaRatioParams
    """


@schema
class ThetaGammaRatio(SpyglassMixin, dj.Computed):
    """Per-(LFP, interval) theta/gamma power ratio.

    Stores a small scalar summary in DataJoint columns and the
    full time-resolved ratio trace in an AnalysisNwbfile.
    """

    definition = """
    -> ThetaGammaRatioSelection
    ---
    -> AnalysisNwbfile
    ratio_object_id: varchar(40)   # object_id of the per-time ratio table
    mean_ratio: float              # interval-averaged theta/gamma
    median_ratio: float
    n_samples: int                 # samples that fell inside the interval
    """

    def make(self, key):
        params = (ThetaGammaRatioParams & key).fetch1("theta_gamma_params")

        # Resolve nwb_file_name through the interval (always present there).
        nwb_file_name = (IntervalList & key).fetch1("nwb_file_name")

        # 1. Pull the filtered LFP via the merge layer.
        lfp_df = (LFPOutput & key).fetch1_dataframe()

        # 2. Pull the interval bounds.
        valid_times = (IntervalList & key).fetch1("valid_times")  # (n, 2)

        # 3. Compute theta/gamma ratio across the interval.
        #    (Hilbert envelope or wavelet — your call; keep it in
        #    a helper module rather than inline.)
        ratio_df, summary = compute_theta_gamma_ratio(
            lfp_df, valid_times, params,
        )  # returns (DataFrame indexed by time, dict of scalars)

        # 4. Write the trace to an AnalysisNwbfile via the builder
        #    context manager (handles CREATE -> POPULATE -> REGISTER).
        with AnalysisNwbfile().build(nwb_file_name) as builder:
            ratio_object_id = builder.add_nwb_object(
                ratio_df, table_name="theta_gamma_ratio",
            )
            analysis_file_name = builder.analysis_file_name

        # 5. Insert the master row. No part tables in this design —
        #    one (LFP, interval, params) -> one ratio.
        self.insert1({
            **key,
            "analysis_file_name": analysis_file_name,
            "ratio_object_id": ratio_object_id,
            "mean_ratio": float(summary["mean"]),
            "median_ratio": float(summary["median"]),
            "n_samples": int(summary["n_samples"]),
        })
```

## Why this shape

- **Three-table layering (Params + Selection + Computed).** Mandatory under custom-pipeline non-negotiable #3 — combining them (e.g. dropping a `params: blob` onto the Computed table) breaks reproducibility and makes parameter sweeps require deletes.
- **`-> LFPOutput` as the upstream FK.** The merge master gives you `fetch1_dataframe()` uniformly across `LFPV1`, `ImportedLFP`, and `CommonLFP`. If you only ever want LFPV1, you can FK `LFPV1` directly — but then `ImportedLFP` users can't run your pipeline.
- **`-> IntervalList`.** Spyglass's per-session interval list. Cardinality is exactly "one row per (nwb_file_name, interval_list_name)" so it slots in cleanly. Each `(LFPOutput, IntervalList, params)` triple is a unique PK and naturally produces one row.
- **No part table.** A part table would be appropriate if you wanted, e.g., one row per electrode within the LFP group. As stated, the analysis collapses across electrodes into a single ratio per interval, so the master alone is enough.
- **`AnalysisNwbfile` for the trace, scalars in columns.** Don't store the time-resolved ratio array as a blob in DataJoint — that's what the analysis-NWB indirection is for. Scalars (`mean_ratio`, `median_ratio`, `n_samples`) are cheap to keep in columns and let you restrict / sort without opening any files.

## Things to watch when you flesh this out

- **`compute_theta_gamma_ratio` is yours to write.** Hilbert envelope on band-pass-filtered LFP is the usual route. Verify on simulated LFP (theta-only, gamma-only, mixed) before running on real data.
- **`valid_times` shape.** `(IntervalList & key).fetch1("valid_times")` returns an `(n_segments, 2)` array — many intervals are multi-segment. Make sure `compute_theta_gamma_ratio` aggregates correctly across segments and doesn't index across gaps.
- **`fetch1_dataframe()` cardinality.** If `key` doesn't restrict `LFPOutput` to exactly one row, `fetch1_dataframe()` will raise. Inside `make()` you're given a fully-PK-restricted key, so this is fine — but if you ever call it from a query helper, do `print(len(LFPOutput & key))` first.
- **`skip_duplicates=True` and `IntervalList`.** Your `make()` does **not** insert into `IntervalList` (it consumes one), so you don't trip non-negotiable #6. If you later add a derived-interval table that does insert, do not pass `skip_duplicates=True` — it bypasses orphan-cleanup and produces silent wrong-data on re-runs.
- **Permissions.** When other lab members run `populate()`, they need SELECT on `lfp` and `common` and INSERT on `edeno_theta_gamma`. If only you can write, others can still query the rows you populated.
- **Don't add a merge table yet.** If a `ThetaGammaRatioV2` arrives later (different algorithm, same output shape) and downstream tables want to consume both interchangeably, *that's* when you introduce `ThetaGammaRatioOutput`. Until then, downstream tables can FK-ref `ThetaGammaRatio` directly.

## Usage flow

```python
ThetaGammaRatioSelection.insert1({
    "merge_id": <lfp_merge_id>,                   # from LFPOutput.merge_get_part(...)
    "nwb_file_name": nwb_file,
    "interval_list_name": "02_r1",
    "theta_gamma_params_name": "default",
})
ThetaGammaRatio.populate(
    {"nwb_file_name": nwb_file, "theta_gamma_params_name": "default"},
    display_progress=True,
)

# Per-row scalar summary
(ThetaGammaRatio & {"nwb_file_name": nwb_file}).fetch(
    "interval_list_name", "mean_ratio", "median_ratio", as_dict=True,
)

# Time-resolved trace for one (LFP, interval, params)
ratio_df = (ThetaGammaRatio & key).fetch_nwb()[0]["theta_gamma_ratio"]
```

That's the full skeleton. Once you're happy with the shape, drop it in a module under your team's directory (e.g. `<my_repo>/edeno_theta_gamma/theta_gamma.py`), import it, and the schema gets created on first import.
