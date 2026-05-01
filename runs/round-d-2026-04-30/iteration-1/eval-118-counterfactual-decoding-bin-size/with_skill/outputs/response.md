# Changing `position_bin_size` from 2 cm to 5 cm — what cascades, what you can re-use

## First: a shape correction on `DecodingParameters`

Before walking the cascade, the framing of the question matters. There is **no top-level column called `position_bin_size` on `DecodingParameters`**. Verify:

```text
# src/spyglass/decoding/v1/core.py:38-43
definition = """
decoding_param_name : varchar(80)
---
decoding_params : LONGBLOB             # initialization parameters for model
decoding_kwargs = NULL : LONGBLOB      # additional keyword arguments
"""
```

Only three fields: `decoding_param_name` (PK), `decoding_params` (blob), `decoding_kwargs` (blob). `position_bin_size` lives **inside** the `decoding_params` blob, where it's a constructor kwarg consumed by `non_local_detector`'s `Environment` (typically named `place_bin_size` in non_local_detector itself — see `decoding/decoding_merge.py:161,171`). Spyglass passes the blob through verbatim to `ClusterlessDetector(**decoding_params)` / `SortedSpikesDetector(**decoding_params)` inside `make_compute`.

Two consequences:

1. **DataJoint sees no schema-level change.** The hash on the row is over the LONGBLOB; DataJoint cannot tell that the bin-size sub-key changed unless you give the row a new name. So the *correct* way to "change" `position_bin_size` is **not** to mutate the blob in place via `update1` — that silently corrupts provenance for every downstream row that already references the old name. The correct shape is a new `decoding_param_name` row holding the new blob.
2. **Everything downstream that you want to recompute under the new bin size has to be re-selected and re-populated explicitly** under the new name.

If you actually do `update1()` on the existing row, see [§ The `update1` trap below](#the-update1-trap) — that case has a different "what changes" answer (provenance corruption rather than a clean cascade).

Below I assume the clean path: insert a **new** `DecodingParameters` row.

---

## Slot 1 — The new row (no existing rows mutate)

```python
# Build the new params object with place_bin_size=5.0 instead of 2.0.
# The exact constructor depends on which classifier you're using —
# ContFragClusterlessClassifier / NonLocalClusterlessDetector /
# ContFragSortedSpikes / NonLocalSorted. position_bin_size is an
# Environment kwarg; pass it where your existing params pass it.
from non_local_detector import ContFragClusterlessClassifier  # example

new_params_name = "contfrag_clusterless_5cm"   # or whatever convention you use
DecodingParameters.insert1({
    "decoding_param_name": new_params_name,
    "decoding_params": ContFragClusterlessClassifier(place_bin_size=5.0),
    "decoding_kwargs": {},   # or your existing kwargs
}, skip_duplicates=True)
```

Effect: a new row appears in `DecodingParameters` under the new name. The old `2 cm` row is **untouched** — every existing downstream row that referenced it still resolves to the 2 cm blob and remains scientifically interpretable.

If you want to keep the old name and get the new blob, that is an `update1`; do not do that without reading the trap section.

---

## Slot 2 — Downstream branches that must be re-selected and re-populated

`DecodingParameters` has exactly two FK consumers (verifiable: `grep -n "-> DecodingParameters" src/spyglass/decoding/v1/`):

- `ClusterlessDecodingSelection` (`decoding/v1/clusterless.py:87`)
- `SortedSpikesDecodingSelection` (`decoding/v1/sorted_spikes.py:52`)

For **each pipeline you actually run** (one or both), you re-do this triple:

1. **Insert a new selection row** under the new `decoding_param_name`, keeping every other PK field (group, position group, encoding/decoding intervals, `estimate_decoding_params`) the same as the row you want to mirror:

   ```python
   new_selection_key = {
       "nwb_file_name": nwb_file_name,
       "waveform_features_group_name": features_group_name,   # or sorted_spikes_group_name for sorted
       "position_group_name": position_group_name,
       "decoding_param_name": new_params_name,                # the new row from Slot 1
       "encoding_interval": encoding_interval_name,
       "decoding_interval": decoding_interval_name,
       "estimate_decoding_params": 0,                          # match what you used before
   }
   ClusterlessDecodingSelection.insert1(new_selection_key, skip_duplicates=True)
   ```

2. **Populate the Computed table** under that key:

   ```python
   ClusterlessDecodingV1.populate(new_selection_key)
   # or SortedSpikesDecodingV1.populate(new_selection_key)
   ```

   This re-runs the full decoder fit + forward-backward against the new bin size. Concretely it re-builds the `Environment` / `TrackGraph`, the HMM transition matrix, the observation model, and writes a **new** pair of files: `results_path` (.nc) and `classifier_path` (.pkl) under `{SPYGLASS_ANALYSIS_DIR}/{stripped_nwb_file_name}/`.

3. **`DecodingOutput` (the merge master) gets a new merge_id automatically** when the Computed populate succeeds — because `ClusterlessDecodingV1` / `SortedSpikesDecodingV1` are part tables of `DecodingOutput`, every fresh populate mints a fresh `merge_id`. Old `merge_id`s for the 2 cm runs survive alongside.

So per active pipeline the new rows are: 1 new `*Selection` row, 1 new `*DecodingV1` row (with new .nc + .pkl files on disk), 1 new `DecodingOutput` part-table entry (new `merge_id`).

If you run both clusterless and sorted-spikes today, do this for both selection tables independently — they are siblings, not children of each other.

---

## Slot 3 — What is unaffected and reusable

Everything upstream of `*DecodingSelection` and every sibling pipeline is unchanged. You do **not** re-run any of these:

- `Session`, `Nwbfile`, `IntervalList` — session metadata and intervals.
- **Position pipeline:** `TrodesPosV1` / `DLCPosV1`, `PositionOutput`, and `PositionGroup` (with its `PositionGroup.Position` part). The position rows the new selection points at are the same merge_ids as before.
- **Spike sorting pipeline:** `SpikeSortingRecording`, `SpikeSorting`, `CurationV1`, `SpikeSortingOutput`. Untouched.
- **Clusterless features:** `WaveformFeaturesParams`, `UnitWaveformFeaturesSelection`, `UnitWaveformFeatures`, `UnitWaveformFeaturesGroup` (+ `.UnitFeatures` part). Untouched — features are computed from spikes/waveforms, not from the position grid, so the bin-size change does not touch them.
- **Sorted-spikes group:** `SortedSpikesGroup` — untouched, same reasoning.
- **LFP / ripple / MUA pipelines:** `LFPV1`, `LFPBandV1`, `RippleTimesV1`, `MuaEventsV1` — entirely orthogonal; the decoding bin size has no path to them.
- **The other decoding pipeline** if you only ran one (e.g., if you only re-run clusterless under 5 cm, all `SortedSpikesDecodingV1` rows are untouched, and vice versa).
- **The old 2 cm `DecodingParameters` row and every `*DecodingSelection` / `*DecodingV1` / `DecodingOutput` row keyed on it.** They stay; you can still fetch results, models, posteriors against them. This is what makes a side-by-side 2 cm vs 5 cm comparison possible.

The only files written are the new `.nc` + `.pkl` for the new runs. The old files are not deleted automatically. If/when you decide you no longer want the 2 cm artifacts, run `DecodingOutput().cleanup(dry_run=True)` first to **log** what would be removed (note: it scans for *orphans*, so it will only catch files whose merge rows have been deleted; it doesn't blanket-clean by params name).

---

## Slot 4 — Verifying the cascade scope before you commit

Either of these will give you the authoritative downstream list directly from the current schema, so you don't have to trust the enumeration above:

From a Python session connected to the live DB:

```python
from spyglass.decoding import DecodingParameters
for child in DecodingParameters().descendants(as_objects=True):
    print(child.full_table_name)
```

(`descendants()` returns table NAMES by default; pass `as_objects=True` to get FreeTable instances.)

Or from the bundled scripts (no Python session needed):

```bash
# Source-only (works without DB connection):
python skills/spyglass/scripts/code_graph.py path --down DecodingParameters

# Live DB (also reports row counts so you can scope the impact):
python skills/spyglass/scripts/db_graph.py path --down DecodingParameters
```

Confirm that the union of tables you saw in Slot 2 matches the printed descendants. Anything reported there that I did not list above is either a custom lab table outside `$SPYGLASS_SRC` or a schema change since this writeup — treat as a real downstream you also need to handle.

---

## The `update1` trap — what changes if you mutate the existing row in place

Different question, different answer. If instead of inserting a new params row you do

```python
# DON'T — corrupts provenance for every existing downstream row.
DecodingParameters().update1({
    "decoding_param_name": "<existing name>",
    "decoding_params": <new blob with place_bin_size=5.0>,
})
```

then **no DataJoint rows are removed and none are recomputed automatically**. The `decoding_param_name` PK doesn't change, so every existing `ClusterlessDecodingSelection` / `SortedSpikesDecodingSelection` row that already references that name still appears valid. But:

- The `*DecodingV1` rows on disk (`results_path`, `classifier_path`) were computed against the **old** 2 cm blob — their content is *stale relative to the row that now claims to describe them*. Provenance is silently broken: anyone who later does `(DecodingParameters & {"decoding_param_name": name}).fetch1("decoding_params")` to interpret existing results will read the 5 cm blob and conclude the old `.nc` files were generated under 5 cm. They were not.
- DataJoint will **not** offer to re-populate; it sees the Computed rows as already done.
- Recovery requires deleting every downstream row keyed on that name (with all the destructive-op caution that implies) and re-running. Not a nice place to be.

So: don't do this. Insert a new row under a new name (the Slot 1 path).

---

## TL;DR

- The change is a **new `DecodingParameters` row under a new `decoding_param_name`**, not an in-place edit. `position_bin_size` is nested inside the `decoding_params` blob; DataJoint sees only the named row, so the new bin size has to live under a new name to be tracked.
- **Re-runs:** new `*DecodingSelection` row + `*DecodingV1.populate(new_key)` + a new `DecodingOutput` `merge_id`, separately for each of clusterless / sorted-spikes that you actively use. New `.nc` + `.pkl` files written.
- **Reuses:** everything in position (TrodesPos / DLC / PositionOutput / PositionGroup), spike sorting (SpikeSorting / Curation / SpikeSortingOutput), clusterless features (UnitWaveformFeatures, UnitWaveformFeaturesGroup), `SortedSpikesGroup`, `IntervalList`, LFP / ripple / MUA, and **all existing 2 cm decoding rows** stay in place untouched.
- **Verify:** `DecodingParameters().descendants(as_objects=True)` (live DB), or `python skills/spyglass/scripts/db_graph.py path --down DecodingParameters` / `code_graph.py path --down DecodingParameters` from the skill bundle.
