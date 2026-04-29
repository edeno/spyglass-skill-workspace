## Short answer

Neither. **`SpikeSortingV1` does not exist** in the v1 pipeline. The v1 spike-sorting Computed class is just `SpikeSorting` (no `V1` suffix), defined in `src/spyglass/spikesorting/v1/sorting.py:234` and re-exported from `spyglass.spikesorting.v1`.

So the correct call is:

```python
from spyglass.spikesorting.v1 import SpikeSorting

SpikeSorting.populate(key)        # class-form (most common in the docs)
# or equivalently
SpikeSorting().populate(key)      # instance-form
```

DataJoint accepts both class- and instance-form `populate` — they dispatch to the same logic, so the dict-vs-method choice is not what's tripping you up here. The actual issue is the class name.

## Why this is easy to get wrong — v0 → v1 naming is asymmetric

This is a real footgun and worth flagging explicitly. **There is no consistent rule** for whether a v1 table keeps the `V1` suffix or drops it. From the source under `src/spyglass/`:

**v1 classes that keep the `V1` suffix:**
- `LFPV1` (`lfp/v1/lfp.py:45`)
- `LFPBandV1` (`lfp/analysis/v1/lfp_band.py:290`)
- `TrodesPosV1` (`position/v1/position_trodes_position.py:178`)
- `DLCPosV1` (`position/v1/position_dlc_selection.py:39`)
- `RippleTimesV1` (`ripple/v1/ripple.py:182`)
- `LinearizedPositionV1` (`linearization/v1/main.py:111`)
- `CurationV1` (`spikesorting/v1/curation.py:30`)
- `ClusterlessDecodingV1` (`decoding/v1/clusterless.py:95`)
- `SortedSpikesDecodingV1` (`decoding/v1/sorted_spikes.py:61`)
- `MuaEventsV1` (`mua/v1/mua.py:63`)

**v1 classes in the spike-sorting subpackage that DROP the `V1` suffix:**
- `SpikeSorting` (`spikesorting/v1/sorting.py:234`) — the Computed class you want
- `SpikeSortingSelection` (`spikesorting/v1/sorting.py:199`)
- `SpikeSortingRecording` (`spikesorting/v1/recording.py`)
- `SpikeSortingRecordingSelection` (`spikesorting/v1/recording.py`)
- `MetricCuration` / `MetricCurationSelection` (`spikesorting/v1/metric_curation.py`)
- `FigURLCuration` / `FigURLCurationSelection` (`spikesorting/v1/figurl_curation.py`)
- `ArtifactDetection` / `ArtifactDetectionSelection` (`spikesorting/v1/artifact.py`)

So you've already used one of the unsuffixed v1 classes — `SpikeSortingSelection` — without realizing it. `SpikeSorting` follows the same pattern: the package path (`spyglass.spikesorting.v1`) carries the version, the class name doesn't.

The reason this exists historically is that the v0 spike-sorting subpackage was renamed/replaced rather than kept side-by-side under a different class name (`spyglass.spikesorting.v0` does still exist, with its own `SpikeSorting` class — they don't collide because they live in different modules). Other subpackages took the opposite route and kept v0 classes under their original names while suffixing the new ones with `V1`.

## The general rule: verify, don't extrapolate

When you see a v1 class name in one subpackage, **don't infer the spelling of a v1 class in another subpackage** — verify by import or by listing the module:

```bash
# Confirm what's actually exported from spyglass.spikesorting.v1
python -c "import spyglass.spikesorting.v1 as m; print([n for n in dir(m) if 'Sort' in n])"
```

or just:

```python
from spyglass.spikesorting.v1 import SpikeSorting   # works
from spyglass.spikesorting.v1 import SpikeSortingV1 # ImportError
```

The skill's `code_graph.py` (under `skills/spyglass/scripts/`) is the script-friendly version of that check if you want to discover all `dj.Computed` classes in a module without running an import.

## Concrete next step for your workflow

Replace your call with:

```python
from spyglass.spikesorting.v1 import SpikeSortingSelection, SpikeSorting

# (you already inserted into SpikeSortingSelection)
SpikeSorting.populate(key)
```

For the broader v1 spike-sorting flow (recording → artifact → sort → curation → merge-table publish), the canonical end-to-end example with the rerun-tolerant `insert_selection()` quirks lives in `skills/spyglass/references/spikesorting_v1_pipeline.md` (the "Canonical Example (v1)" section) — that's the file to load if you want the full pipeline rather than just this one call.
