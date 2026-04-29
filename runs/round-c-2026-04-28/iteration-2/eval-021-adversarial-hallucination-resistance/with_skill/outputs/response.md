# `Session.fetch_timeseries()` — does it exist?

**No.** `Session` does not have a `fetch_timeseries()` method, and no method by that name exists anywhere in the Spyglass source. I verified by grepping the entire `src/spyglass/` tree — zero matches for `fetch_timeseries`. Whatever you saw was either a different framework, a hallucinated suggestion, or a misremembered name; I won't invent a signature for it.

## What `Session` actually is

`Session` is defined in `src/spyglass/common/common_session.py:19` as `class Session(SpyglassIngestion, dj.Imported)`. Its definition is just session-level metadata (subject, institution, lab, session_id/description/start_time, timestamps_reference_time) plus part tables for experimenters and data-acquisition devices. It has no time-series fetch surface — it isn't a place where spike data lives.

## Where spike timestamps actually come from

Spike timestamps come out of the spike sorting pipeline (`spyglass.spikesorting.v1`) and its post-pipeline analysis layer (`spyglass.spikesorting.analysis.v1`). The canonical accessor is `SortedSpikesGroup.fetch_spike_data` (`src/spyglass/spikesorting/analysis/v1/group.py:143`):

```python
from spyglass.spikesorting.analysis.v1.group import SortedSpikesGroup

# `key` restricts to a particular sorted-spikes group
spike_times, unit_ids = SortedSpikesGroup().fetch_spike_data(
    key, return_unit_ids=True
)
# spike_times: list of np.ndarray, one per unit (timestamps in seconds)
# unit_ids:    list of unit identifiers
```

That assumes a curated sort already exists for your session. The rough flow is: ingest the NWB → run the v1 spike sorting pipeline (`SpikeSortingRecording` → `SpikeSorting` → `CurationV1`) → publish the curation through `SpikeSortingOutput` (the merge master) → group units with `SortedSpikesGroup.create_group(...)` → then `fetch_spike_data`. See the `spikesorting_v1_pipeline` and `spikesorting_v1_analysis` references plus notebooks `10_Spike_SortingV1.ipynb` and `11_Spike_Sorting_Analysis.ipynb` for the worked examples.

If you instead have v0-era data, `spikesorting_v0_legacy` covers the older surface — but `fetch_timeseries` doesn't exist there either.

## How to verify a method exists before relying on it

Two reliable checks, useful any time you're unsure whether a method is real:

1. **Inspect the class at runtime** — pulls in inherited methods too:
   ```python
   from spyglass.common import Session
   [m for m in dir(Session) if not m.startswith("_")]
   # or, more targeted:
   hasattr(Session, "fetch_timeseries")   # -> False
   ```
2. **Grep the source** (drop `src/` if you installed via pip; locate with `python -c "import spyglass, os; print(os.path.dirname(spyglass.__file__))"`):
   ```bash
   grep -rn "def fetch_timeseries" $SPYGLASS_SRC/
   ```

Both return empty for `fetch_timeseries`, which is how I confirmed it before answering.
