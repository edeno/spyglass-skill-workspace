# Custom cross-correlation table downstream of `SortedSpikesGroup`

## Decision tree (one row per group → single-source pipeline)

Walking the five-step decision tree in `custom_pipeline_authoring.md`:

1. The grouping is already done — `SortedSpikesGroup` *is* the
   "set of units to analyze together" table. Don't re-roll a grouping
   table.
2. You need a **`Parameters`** table (`dj.Lookup`) for the tunable
   knobs of cross-correlation: bin width, max lag, smoothing, and
   the time interval to restrict to.
3. You need a **`Selection`** table (`dj.Manual`) pairing one
   `SortedSpikesGroup` row with one parameter set (and an
   `IntervalList` row, since `SortedSpikesGroup` itself isn't
   interval-scoped).
4. You need a **`Computed`** table whose `make()` produces the
   cross-correlogram array per group and writes it to an
   `AnalysisNwbfile`.
5. You do **not** need a merge table — only one implementation
   exists; downstream tables can FK-ref the Computed table directly.
   (Non-Negotiable #5; merge tables are only warranted for multiple
   interchangeable implementations.)

"One row per group" = the Computed table's PK is the
`SortedSpikesGroup` PK plus the params PK plus (optionally) the
interval PK. The actual matrix of pair-wise CCGs is too large for a
DataJoint cell, so it goes into the AnalysisNwbfile and the row
just stores `analysis_file_name` + an object id.

## Schema shape

```python
import datajoint as dj

from spyglass.common import IntervalList
from spyglass.common.common_nwbfile import AnalysisNwbfile
from spyglass.spikesorting.analysis.v1.group import SortedSpikesGroup
from spyglass.utils import SpyglassMixin, SpyglassMixinPart

schema = dj.schema("<database_user>_xcorr")  # personal prefix; must
                                              # match dj.config["database.user"]

@schema
class CrossCorrParams(SpyglassMixin, dj.Lookup):
    """Parameters for pairwise cross-correlogram computation."""

    definition = """
    xcorr_params_name: varchar(32)
    ---
    xcorr_params: blob
    """
    contents = [
        ["default", {"bin_ms": 1.0, "max_lag_ms": 100.0,
                     "smoothing_sigma_ms": 0.0}],
    ]

@schema
class CrossCorrSelection(SpyglassMixin, dj.Manual):
    """One row = one (SortedSpikesGroup, IntervalList, params) to run."""

    definition = """
    -> SortedSpikesGroup
    -> IntervalList
    -> CrossCorrParams
    """

@schema
class CrossCorr(SpyglassMixin, dj.Computed):
    """Pairwise cross-correlograms for all units in one group."""

    definition = """
    -> CrossCorrSelection
    ---
    -> AnalysisNwbfile
    ccg_object_id:  varchar(40)   # full (n_units, n_units, n_lags) array
    unit_ids_object_id: varchar(40)  # ordered unit-id vector
    lags_object_id: varchar(40)      # lag-time vector (s)
    """

    class Pair(SpyglassMixinPart):
        """Per-pair scalar summaries (peak, peak-lag, area). Optional."""

        definition = """
        -> master
        unit_id_a: int
        unit_id_b: int
        ---
        peak_rate:   float
        peak_lag_s:  float
        """

    def make(self, key):
        params = (CrossCorrParams & key).fetch1("xcorr_params")
        nwb_file_name = (CrossCorrSelection & key).fetch1("nwb_file_name")
        interval = (IntervalList & key).fetch1("valid_times")

        # SortedSpikesGroup.fetch_spike_data takes the SortedSpikesGroup
        # PK fields out of `key`; time_slice can be a (t0, t1) tuple per
        # spikesorting/analysis/v1/group.py:231-232.
        spike_times, unit_ids = SortedSpikesGroup().fetch_spike_data(
            key, return_unit_ids=True
        )

        # ccg: (n_units, n_units, n_lags); lags: (n_lags,)
        ccg, lags, pair_rows = compute_ccg(
            spike_times, unit_ids, interval, params, key=key,
        )

        # Builder context handles CREATE -> POPULATE -> REGISTER.
        # Always pass distinct table_name values; default "pandas_table"
        # collides if you call add_nwb_object more than once.
        with AnalysisNwbfile().build(nwb_file_name) as builder:
            ccg_id  = builder.add_nwb_object(ccg,            table_name="ccg")
            uid_id  = builder.add_nwb_object(np.asarray(unit_ids),
                                             table_name="unit_ids")
            lag_id  = builder.add_nwb_object(lags,           table_name="lags")
            analysis_file_name = builder.analysis_file_name

        self.insert1({
            **key,
            "analysis_file_name":     analysis_file_name,
            "ccg_object_id":          ccg_id,
            "unit_ids_object_id":     uid_id,
            "lags_object_id":         lag_id,
        })
        self.Pair().insert(pair_rows, skip_duplicates=True)
```

## Why this shape

- **`SortedSpikesGroup` is the upstream key.** Its PK is
  `(nwb_file_name, sorted_spikes_group_name,
  unit_filter_params_name)` (`spikesorting_v1_analysis.md` →
  source `spikesorting/analysis/v1/group.py`). FK-ref'ing it with
  `-> SortedSpikesGroup` propagates exactly those three fields, so
  `CrossCorr` ends up with one row per (group, interval, params).
- **Parameters / Selection / Computed are kept separate**
  (Non-Negotiable #3). Re-running with new bin/lag values is just
  another `CrossCorrParams` entry + new Selection row, no row
  deletions needed.
- **Output goes to `AnalysisNwbfile`** (Non-Negotiable #4). For N
  units the full CCG tensor is `N*N*n_lags` floats — too big for a
  DataJoint blob column. The DJ row stores only file name + object
  ids; `(CrossCorr & key).fetch_nwb()[0]` retrieves the NWB and you
  pull each object by its id.
- **`CrossCorr.Pair` is optional** but useful — it gives you a
  queryable per-pair summary (peak rate, peak lag) without loading
  the full tensor. Master insert before part insert (FK ordering;
  see canonical skeleton).
- **No merge table.** One implementation, no multi-source need
  (Non-Negotiable #5).
- **`SpyglassMixin` first in MRO**, with `SpyglassMixinPart` for the
  part table (Non-Negotiable #1).
- **Schema name must be `<database_user>_<suffix>`** —
  `dj.schema("spyglass_<user>_xcorr")` would fail with a MySQL
  permission error because the prefix must equal
  `dj.config["database.user"]`. There is no `spyglass_*` framework
  namespace.

## Things to confirm at write time

- `dj.config["database.user"]` value, used as the schema prefix.
- The exact `SortedSpikesGroup` PK fields — verify with
  `SortedSpikesGroup.heading` or `code_graph.py` before relying on
  the field names above for documentation; the FK arrow propagates
  them correctly regardless.
- Whether you actually want an `IntervalList` FK or want to pull
  the interval out of params. FK is cleaner because it makes
  per-epoch computations queryable without parsing a blob.

## Relevant skill paths

- `/Users/edeno/Documents/GitHub/spyglass-skill/skills/spyglass/references/custom_pipeline_authoring.md`
  — five-step decision tree, non-negotiables, canonical skeleton,
  AnalysisNwbfile builder pattern, schema naming rule.
- `/Users/edeno/Documents/GitHub/spyglass-skill/skills/spyglass/references/spikesorting_v1_analysis.md`
  — `SortedSpikesGroup` PK + `fetch_spike_data` signature.
