# `spyglass.spikesorting.v0` vs `v1` — which to use for a fresh session

**Short answer: use v1 for all new work. v0 is legacy — read-only for querying existing sortings, do not populate v0 tables for new sessions.**

## Why v1

The v1 pipeline (`spyglass.spikesorting.v1.*`) is the current/recommended pipeline. v0 (`spyglass.spikesorting.v0.*`) predates it and is kept around so that pre-existing v0 sortings in the database remain queryable through the same downstream interface that v1 uses. There is no scientific reason to produce *new* sortings under v0 today — it has more tables threaded through the curation step, uses plain `.insert1(...)` instead of v1's `insert_selection(...)` UUID/validation convention, and has a known footgun where `Curation.get_curated_sorting` does not filter `'reject'`-labeled units.

For a fresh session, the v1 flow is:

```
SortGroup
  → SpikeSortingRecordingSelection → SpikeSortingRecording
  → ArtifactDetectionSelection → ArtifactDetection
  → SpikeSortingSelection → SpikeSorting
  → CurationV1
  → SpikeSortingOutput (merge)
```

Imports come from `spyglass.spikesorting.v1` and `spyglass.spikesorting.spikesorting_merge.SpikeSortingOutput`. Full canonical example: see `references/spikesorting_v1_pipeline.md`.

## How v0 and v1 coexist — `SpikeSortingOutput` is the merge table

Both pipelines feed a single merge table, `SpikeSortingOutput` (defined in `src/spyglass/spikesorting/spikesorting_merge.py`). `SpikeSortingOutput` has `merge_id` (UUID) as its only PK and three part tables:

| Part table | Source | Holds |
| --- | --- | --- |
| `SpikeSortingOutput.CurationV1` | `spyglass.spikesorting.v1.curation.CurationV1` | v1 sortings (current) |
| `SpikeSortingOutput.CuratedSpikeSorting` | `spyglass.spikesorting.v0.spikesorting_curation.CuratedSpikeSorting` | v0 legacy sortings |
| `SpikeSortingOutput.ImportedSpikeSorting` | `spyglass.spikesorting.imported.ImportedSpikeSorting` | Pre-sorted units imported from NWB |

Downstream consumers (decoding, MUA, ripple analysis, firing-rate helpers) talk to `SpikeSortingOutput` only and don't need to branch on pipeline version — `get_spike_times`, `get_sorting`, `get_recording`, etc. dispatch through the part table internally.

## What to do with old v0 code you're staring at

Two cases:

1. **Reading / querying existing v0 sortings already in the DB.** Don't re-run them under v1 just to re-run them. Query through the merge wrapper rather than touching v0 tables directly:

   ```python
   from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput

   merge_ids = SpikeSortingOutput().get_restricted_merge_ids(
       {"nwb_file_name": nwb_file, "interval_list_name": "02_r1"},
       sources=["v0"],          # or ["v0", "v1"] to mix
   )
   for mid in merge_ids:
       spikes = SpikeSortingOutput().get_spike_times({"merge_id": mid})
   ```

   The v0-specific footguns (e.g. `Curation.get_curated_sorting` returning rejected units, `CuratedSpikeSorting.fetch_nwb` silently returning a list on multi-row restrictions) are documented in `references/spikesorting_v0_legacy.md`. Open that reference *only* for reading legacy v0 code or pulling pre-existing v0 sortings.

2. **Producing a new sort for today's session.** Use v1 end-to-end. Do **not** populate v0 tables for new sessions — `references/spikesorting_v0_legacy.md` is explicit: "For new sorting/curation work, use v1 — do not populate v0 tables."

## Watch out: class-name collisions

Many class names exist in BOTH `v0` and `v1` modules with different schemas and different insert conventions: `SortGroup`, `SpikeSortingRecordingSelection`, `SpikeSortingRecording`, `ArtifactDetection*`, `SpikeSorterParameters`, `SpikeSortingSelection`, `SpikeSorting`, `WaveformParameters`, `MetricParameters`, `BurstPair*`, `RecordingRecomputeVersions`, etc. When you see `SpikeSorting` or `SortGroup` in old lab code, look at the `from spyglass.spikesorting.v?...` import at the top of that file before reasoning about it. Full collision table: `references/spikesorting_v0_legacy.md` § "Class-name Collisions to Watch For".

Note in particular: v1's `SortGroup` only ships `set_group_by_shank(...)`. v0 had `set_group_by_electrode_group(...)` — that method does not exist on v1's `SortGroup`, so don't port that v0 pattern into a fresh v1 workflow.

## TL;DR

- New session today → **v1** (`spyglass.spikesorting.v1.*` + `SpikeSortingOutput.CurationV1`).
- Old v0 sortings already in the DB → query through `SpikeSortingOutput` (specifically the `SpikeSortingOutput.CuratedSpikeSorting` part for v0 rows); don't re-run them under v0.
- `SpikeSortingOutput` is the merge table that surfaces v0 (`CuratedSpikeSorting` part) and v1 (`CurationV1` part) sortings under one uniform interface for downstream consumers.
