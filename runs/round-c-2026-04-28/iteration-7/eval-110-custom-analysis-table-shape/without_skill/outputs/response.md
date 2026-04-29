# Custom cross-correlation table for `SortedSpikesGroup`

Here's the schema shape I'd use, with the reasoning laid out.

## Schema decision: `Computed` keyed by `SortedSpikesGroup` PK

```python
import datajoint as dj
import numpy as np
import pynwb
from spyglass.spikesorting.analysis.v1.group import SortedSpikesGroup
from spyglass.common.common_nwbfile import AnalysisNwbfile
from spyglass.utils import SpyglassMixin

schema = dj.schema("my_xcorr_v1")  # pick your own prefix


@schema
class CrossCorrelogramParams(SpyglassMixin, dj.Lookup):
    definition = """
    # Parameters for pairwise spike cross-correlograms
    xcorr_param_name : varchar(64)
    ---
    bin_ms          : float          # bin width in ms
    window_ms       : float          # +/- window in ms
    normalization   : enum('count','rate','coeff')
    """
    contents = [
        ("default_1ms_50ms", 1.0, 50.0, "coeff"),
    ]


@schema
class CrossCorrelogramSelection(SpyglassMixin, dj.Manual):
    definition = """
    # One selection row = one SortedSpikesGroup x one param set
    -> SortedSpikesGroup
    -> CrossCorrelogramParams
    """


@schema
class CrossCorrelogram(SpyglassMixin, dj.Computed):
    definition = """
    # Pairwise cross-correlogram for every unit pair in the group
    -> CrossCorrelogramSelection
    ---
    -> AnalysisNwbfile          # where the heavy arrays live
    xcorr_object_id : varchar(40)   # NWB object id for the xcorr DynamicTable / array
    unit_ids        : blob          # list[int] aligned to the matrix axes
    n_units         : int
    n_bins          : int
    """

    def make(self, key):
        # 1. Pull spike times for every unit in the group.
        #    SortedSpikesGroup exposes a helper for this:
        spike_times = SortedSpikesGroup.fetch_spike_data(key)  # list[np.ndarray]
        unit_ids = list(range(len(spike_times)))               # or pull real ids

        params = (CrossCorrelogramParams & key).fetch1()
        bin_s    = params["bin_ms"] / 1000.0
        window_s = params["window_ms"] / 1000.0
        n_bins   = int(2 * window_s / bin_s) + 1

        # 2. Compute the (n_units, n_units, n_bins) tensor.
        xcorr = compute_pairwise_xcorr(
            spike_times, bin_s=bin_s, window_s=window_s,
            normalization=params["normalization"],
        )

        # 3. Persist heavy arrays in an AnalysisNwbfile, keep only ids in DJ.
        nwb_file_name = (SortedSpikesGroup & key).fetch1("nwb_file_name")
        analysis_file = AnalysisNwbfile().create(nwb_file_name)
        with pynwb.NWBHDF5IO(
            AnalysisNwbfile.get_abs_path(analysis_file), "a", load_namespaces=True
        ) as io:
            nwbf = io.read()
            container = pynwb.core.DynamicTable(
                name="cross_correlogram",
                description=f"pairwise xcorr, bin={params['bin_ms']}ms",
            )
            # store xcorr as a single ndarray column or a 3D dataset; pick one and stick with it
            container.add_column(name="xcorr", description="(n_units,n_units,n_bins)", data=[xcorr])
            nwbf.add_scratch(container)
            io.write(nwbf)
            object_id = container.object_id

        AnalysisNwbfile().add(nwb_file_name, analysis_file)

        self.insert1({
            **key,
            "analysis_file_name": analysis_file,
            "xcorr_object_id": object_id,
            "unit_ids": np.asarray(unit_ids),
            "n_units": len(unit_ids),
            "n_bins": n_bins,
        })

    def fetch_xcorr(self, key=None):
        """Return (xcorr, unit_ids, lags_s) for one row."""
        row = (self & key).fetch1()
        path = AnalysisNwbfile.get_abs_path(row["analysis_file_name"])
        with pynwb.NWBHDF5IO(path, "r", load_namespaces=True) as io:
            nwbf = io.read()
            obj = nwbf.objects[row["xcorr_object_id"]]
            xcorr = np.asarray(obj["xcorr"][0])
        params = (CrossCorrelogramParams & row).fetch1()
        lags = np.arange(-params["window_ms"], params["window_ms"] + params["bin_ms"],
                         params["bin_ms"]) / 1000.0
        return xcorr, row["unit_ids"], lags
```

## Why this shape

1. **`Computed` not `Imported`.** Cross-correlation is derived from upstream tables; it's not pulling new data off disk. `Computed` is the canonical Spyglass choice (e.g. `DecodingOutput`, `SortedSpikesIndicator`).

2. **Selection table separates "what to compute" from "the result."** This is the universal Spyglass pattern (`*Selection` -> `*` Computed). It lets you queue work via `populate(...)` without polluting the result table with rows you haven't run yet, and lets you re-run with new params by adding a `CrossCorrelogramParams` row.

3. **One row per group, NOT one row per pair.** You asked for one row per group — good instinct. With N units you'd otherwise get N*(N-1)/2 rows per group; for N=200 that's ~20k rows per recording. Heavy arrays should stay in NWB, not blow up the DJ row count.

4. **Heavy arrays in `AnalysisNwbfile`, pointers in DJ.** This is the Spyglass convention everywhere there's a multi-MB result (decoding posteriors, LFP, ripple traces). The DJ row holds:
   - `analysis_file_name` (FK to `AnalysisNwbfile`)
   - `xcorr_object_id` (NWB object UUID inside the file)
   - small metadata: `unit_ids`, `n_units`, `n_bins`

   Then `fetch_xcorr()` opens the NWB file and pulls the (n_units, n_units, n_bins) tensor. Don't put a multi-MB blob directly in MariaDB — DJ allows it but Spyglass strongly avoids it.

5. **`SpyglassMixin`** gives you the `delete()`, `fetch_nwb()`, and merge-aware behavior the rest of Spyglass expects. Always inherit it on user tables.

6. **Unit identity.** I'd recommend storing real unit identifiers from the group (curation_id + unit_id pairs, or whatever `SortedSpikesGroup.fetch_spike_data` returns alongside the times in your Spyglass version) rather than positional indices, so a downstream consumer can match a row of the matrix back to its source unit. Confirm the exact return shape of `fetch_spike_data` in your installed version — older versions returned just a list of arrays, newer ones return a dict-like with unit metadata.

## Things I'd verify before relying on this

- Exact return signature of `SortedSpikesGroup.fetch_spike_data(key)` in your Spyglass version (`spyglass/spikesorting/analysis/v1/group.py`). Older API: `list[np.ndarray]`. Some versions also return unit ids.
- Whether your group spans multiple `nwb_file_name` values — `SortedSpikesGroup` is keyed by `nwb_file_name + sorted_spikes_group_name`, so a single row maps to one source NWB and the `AnalysisNwbfile().create(nwb_file_name)` call is well-defined.
- The Spyglass version pin — `SortedSpikesGroup` lives at `spyglass.spikesorting.analysis.v1.group` in current main; in older releases it was elsewhere.

## Alternative I considered and rejected

**One row per unit pair.** Cleaner DJ-native querying ("show me all pairs with peak > X"), but: (a) you said one row per group, (b) row counts explode quadratically with units, (c) re-fetching a full matrix means N^2 round-trips. If pair-level queryability matters later, add a thin `CrossCorrelogramPair` part-table under `CrossCorrelogram` with `(unit1, unit2, peak_ms, peak_value)` summary stats — keep the heavy tensor in NWB.
