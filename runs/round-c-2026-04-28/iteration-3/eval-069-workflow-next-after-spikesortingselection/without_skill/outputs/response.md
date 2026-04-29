# Next steps after `SpikeSortingSelection` (Spyglass v1 spike-sorting pipeline)

Once a row exists in `SpikeSortingSelection`, the v1 pipeline is fully parameterized for that recording/sort_group/sorter/params combination. From here the canonical sequence is:

## 1. Run the sorter — `SpikeSorting.populate(key)`

```python
from spyglass.spikesorting.v1 import SpikeSorting

SpikeSorting.populate(key)   # key restricts to your SpikeSortingSelection row
```

This is the immediate next step. Note: in the v1 module the populated table is just called `SpikeSorting` (not `SpikeSortingV1`) — `from spyglass.spikesorting.v1 import SpikeSorting`. It reads the recording + parameters dictated by `SpikeSortingSelection`, runs the sorter (e.g. MountainSort4, Kilosort) via SpikeInterface, and writes the sorting result (an NWB analysis file with the units table) into the database.

After this completes, you have spike times but no curation labels yet.

## 2. Create the initial curation — insert into `CurationV1`

```python
from spyglass.spikesorting.v1 import CurationV1

curation_key = CurationV1.insert_curation(
    sorting_id=key["sorting_id"],   # from the SpikeSorting row
    description="initial",
)
```

`CurationV1` is the editable curation handle. The first call with no parent creates curation 0 — a pass-through view of the raw sorter output, with empty `labels` and `merge_groups`. Every subsequent curation step (manual labeling, metric-based labeling, applying merges) creates a *new* `CurationV1` row that references its parent. **`CurationV1` must exist before metric curation, because metric curation operates on top of an existing curation.**

## 3. Compute quality metrics — `MetricCurationSelection` + `MetricCuration.populate`

```python
from spyglass.spikesorting.v1 import (
    MetricCurationSelection,
    MetricCuration,
    MetricCurationParameters,        # waveform/metric/label params
)

MetricCurationSelection.insert1({
    "curation_id": curation_key["curation_id"],
    "waveform_param_name": "default_whitened",
    "metric_param_name": "franklab_default",
    "metric_curation_param_name": "default",
})

MetricCuration.populate(key)
```

`MetricCuration` extracts waveforms, computes quality metrics (snr, isi_violation, nn_noise_overlap, etc.), and applies threshold-based labels (e.g. auto-label units as `noise` / `mua` / `accept`). The output is a *new* `CurationV1` row produced via `CurationV1.insert_curation(..., parent_curation_id=<prev>)` containing the metric-derived labels.

(Optional intermediate step: `FigURLCuration` / sortingview for manual relabeling, again landing back in `CurationV1`.)

## 4. Surface the final curation — `SpikeSortingOutput` merge table

```python
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput

SpikeSortingOutput.insert([final_curation_key], part_name="CurationV1")
```

`SpikeSortingOutput` is the merge table that unifies v0 and v1 curations behind one downstream interface. Inserting your final `CurationV1` row into the `CurationV1` part-table is what makes the units visible to downstream pipelines (decoding, ripple analysis, etc.) — those all restrict on `SpikeSortingOutput.merge_id`, not on the raw curation tables.

---

## Summary — ordered next-N

| # | Action | Table |
|---|--------|-------|
| 1 | `populate` (run sorter) | `SpikeSorting` |
| 2 | `insert_curation` (initial labels/merges) | `CurationV1` |
| 3 | `insert` + `populate` (quality metrics → labeled curation) | `MetricCurationSelection`, `MetricCuration` |
| 4 | `insert` (merge wrapper) | `SpikeSortingOutput` (CurationV1 part) |

Key ordering note: **`CurationV1` comes before `MetricCuration`.** `CurationV1` is the curation object itself; `MetricCuration` is a process that reads a `CurationV1` and emits a new `CurationV1` with metric-based labels. You cannot run metric curation without already having a curation row to attach to.
