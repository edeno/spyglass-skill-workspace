# Next steps after `SpikeSortingSelection.insert_selection`

You're at Step 3 of the v1 spike sorting pipeline (`spyglass.spikesorting.v1`). The Selection table is populated; the rest is `populate()` of the computed table, then a small chain of curation tables, then a publish into the merge wrapper.

## Immediate next: run the sorter

```python
from spyglass.spikesorting.v1 import SpikeSorting

SpikeSorting.populate(sort_key)
```

A note on the name: the v1 spike sorter class is literally named `SpikeSorting` (not `SpikeSortingV1`) — see `src/spyglass/spikesorting/v1/sorting.py:234`. It lives at `spyglass.spikesorting.v1.SpikeSorting`. There is also a v0 class with the same name in `spyglass.spikesorting.v0`, so always import from the `v1` subpackage to avoid the collision.

## Then: the v1 curation chain (in order)

After `SpikeSorting.populate` succeeds, the v1 flow is:

1. **`CurationV1`** — insert an initial curation row that anchors the `sorting_id`. This is the editable curation handle and must come **before** `MetricCuration`, because metric curation computes quality metrics on top of an existing `CurationV1` entry. Use the classmethod helper, not raw `insert1`:

   ```python
   from spyglass.spikesorting.v1 import CurationV1

   curation_key = CurationV1.insert_curation(
       sorting_id=sort_key["sorting_id"],
       description="initial",
   )  # may return a list on rerun — normalize to a single dict
   ```

   See `src/spyglass/spikesorting/v1/curation.py:30` (the class) and `:88-93`, `:117-128` (the rerun-vs-fresh return shape — on a parent rerun, `insert_curation` returns a list of dicts rather than one dict, so normalize before splatting).

2. **`MetricCurationSelection` + `MetricCuration.populate`** — quality metrics (snr, isi_violation, nn_isolation, nn_noise_overlap, etc.) over the just-inserted `CurationV1` row. This is the step that auto-suggests labels and merge groups based on metrics.

   ```python
   from spyglass.spikesorting.v1 import MetricCurationSelection, MetricCuration

   mc_key = MetricCurationSelection.insert_selection({
       **curation_key,
       "waveform_param_name": "default_not_whitened",
       "metric_param_name": "franklab_default",
       "metric_curation_param_name": "default",
   })
   MetricCuration.populate(mc_key)
   ```

   `MetricCurationSelection` is at `metric_curation.py:195`; `MetricCuration` at `metric_curation.py:230`. Heads-up: unlike the rerun-tolerant helpers above, `MetricCurationSelection.insert_selection` returns a single dict on duplicate (`metric_curation.py:221`), so no list normalization is needed here.

3. **`SpikeSortingOutput`** (merge insert) — once you have a curation you're happy with (typically a second `CurationV1` row that applies labels/merge groups derived from the metrics, optionally via FigURL or BurstPair), publish it into the `SpikeSortingOutput.CurationV1` part table:

   ```python
   from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput

   merge_insert_key = (CurationV1 & final_curation_key).fetch("KEY", as_dict=True)
   SpikeSortingOutput.insert(merge_insert_key, part_name="CurationV1")
   ```

   `insert` takes a **list** of dicts here, not a bare dict (passing a dict raises `TypeError`).

## The flow at a glance

```
SpikeSortingSelection (← you are here, just inserted)
        ↓
SpikeSorting.populate                       # runs the sorter
        ↓
CurationV1.insert_curation                  # initial curation entry — BEFORE metrics
        ↓
MetricCurationSelection → MetricCuration.populate   # quality metrics
        ↓
(optionally another CurationV1 entry applying labels/merges,
 plus FigURLCuration / BurstPair as desired)
        ↓
SpikeSortingOutput.insert(..., part_name="CurationV1")  # publish to merge
```

So to answer directly: the **next** table you populate is `SpikeSorting` (`SpikeSorting.populate(sort_key)`). After that, the **next** step is inserting an initial `CurationV1` row via `CurationV1.insert_curation` — and only then do you go on to `MetricCuration` and finally `SpikeSortingOutput`.
