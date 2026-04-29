# `spyglass.spikesorting.v0` vs `spyglass.spikesorting.v1`

Short answer: **use `v1` for any fresh session today.** `v0` is the legacy
pipeline kept around so you can still read sortings that were curated before
`v1` landed; you should not be populating new `v0` tables. Both pipelines
feed into a single merge table, `SpikeSortingOutput`, so downstream code
(decoding, ripple/MUA, replay, etc.) doesn't care which side a sorting came
from.

## Why `v1` is the one to use

A few things changed between the two:

- **`v1` is the actively maintained pipeline.** Bug fixes, new sorter
  bindings, artifact-detection improvements, metric curation, FigURL
  curation views, recompute helpers, and the burst-pair workflow all land
  in `spyglass.spikesorting.v1` (`recording.py`, `artifact.py`, `sorting.py`,
  `curation.py`, `metric_curation.py`, `figurl_curation.py`,
  `burst_curation.py`, `recompute.py`). The `v0` modules
  (`spikesorting_recording.py`, `spikesorting_artifact.py`,
  `spikesorting_sorting.py`, `spikesorting_curation.py`, …) are still
  importable but are kept for back-compat — new features are not being
  added there.
- **`v1` separates curation from the sort itself.** In `v0`,
  `CuratedSpikeSorting` is the terminal curated table and curation rounds
  are baked in as new rows. In `v1`, `CurationV1` is its own table and
  each round of curation (manual, metric-based, FigURL-based) is a new
  `curation_id` rather than a re-sort, which is a much cleaner audit
  trail.
- **`v1` plays nicely with the merge table by design.** The merge wrapper
  knows how to walk back through `SpikeSortingRecordingSelection →
  SpikeSortingSelection → CurationV1 → SpikeSortingOutput.CurationV1`
  given a partial key (`_get_restricted_merge_ids_v1` in
  `spyglass/spikesorting/spikesorting_merge.py`). The `v0` side has a
  more ad‑hoc `sort_interval` shim and the merge helper warns that "V0
  requires artifact restrict — ignoring `restrict_by_artifact`," which
  is the kind of thing that signals "this is the legacy path."

## The merge table is the bridge

For everything downstream, the relevant object is

```python
from spyglass.spikesorting.spikesorting_merge import SpikeSortingOutput
```

`SpikeSortingOutput` is a DataJoint merge table with three part tables, one
per source pipeline:

| Part table                                 | Source                  | Use it for                            |
| ------------------------------------------ | ----------------------- | ------------------------------------- |
| `SpikeSortingOutput.CurationV1`            | `v1.CurationV1`         | All new sorting work                  |
| `SpikeSortingOutput.CuratedSpikeSorting`   | `v0.CuratedSpikeSorting`| Reading already-curated v0 sortings   |
| `SpikeSortingOutput.ImportedSpikeSorting`  | `imported`              | Sortings ingested from outside        |

Once a sorting is registered in `SpikeSortingOutput`, every consumer
(decoders, ripple/MUA pipelines, your own analyses) restricts to a
`merge_id` and uses `SpikeSortingOutput.get_sorting(key)`,
`get_spike_times(key)`, `get_spike_indicator(key, time)`,
`get_firing_rate(key, time, ...)` without caring which pipeline produced
it. That's the whole point of having a merge table.

## Concrete recommendation

For a fresh session today:

1. **Run `v1`.** Populate, in order:
   `SpikeSortingRecordingSelection → SpikeSortingRecording → ArtifactDetectionSelection → ArtifactDetection → SpikeSortingSelection → SpikeSorting → CurationV1`
   (plus `MetricCurationSelection`/`MetricCuration` and/or
   `FigURLCurationSelection`/`FigURLCuration` if you want curation
   rounds on top), then insert the chosen `CurationV1` row into
   `SpikeSortingOutput` via `SpikeSortingOutput.insert([key], part_name="CurationV1")`.
2. **Don't populate any `v0` tables for new sessions.** Treat the
   `spyglass.spikesorting.v0` import as read-only.
3. **If you need to *query* an existing v0 sorting** (e.g., older
   subjects whose sortings haven't been redone), don't call into
   `v0.spikesorting_curation.CuratedSpikeSorting` directly from analysis
   code. Go through `SpikeSortingOutput.CuratedSpikeSorting` (the v0
   part of the merge table) so that downstream code stays uniform.
   Use `SpikeSortingOutput.get_restricted_merge_ids(key, sources=["v0"])`
   when you need to fetch v0 `merge_id`s by interpretable keys.
4. **In code review:** if you see new code importing
   `from spyglass.spikesorting.v0 import ...`, that's a smell unless the
   purpose is explicitly "read pre-existing v0 sortings." New ingestion
   / sorting / curation logic should live on `v1`.

## Mixed-pipeline lab — how to read old code

If the lab repo has a mix of `v0` and `v1` imports, a reasonable cleanup
heuristic is:

- Anything that *populates* tables (`.populate()`, `make`, `insert`) on
  `v0` classes — leave it alone if it's how legacy sessions were built,
  but don't copy that pattern into new code.
- Anything that *reads* `v0.CuratedSpikeSorting` (e.g., to feed a
  decoder) — migrate to going through `SpikeSortingOutput`. Existing
  `v0.CuratedSpikeSorting` rows already have corresponding entries in
  `SpikeSortingOutput.CuratedSpikeSorting`, so the data is reachable
  without re-running anything.
- For brand-new sessions, do the entire pipeline on `v1` and ignore
  `v0` entirely.

## Caveats / unknowns

- I haven't verified the deprecation status of every `v0` submodule
  against the current Spyglass main; "do not populate v0 for new
  sessions" is the policy implied by the merge table's design and the
  v0/v1 split, but if you want a hard answer, check the project's
  changelog or release notes before committing to a long-running
  v1-only workflow.
- If your downstream code (custom analyses outside Spyglass) was
  written against `v0.CuratedSpikeSorting` row keys directly, switching
  to merge-table keys will require a small refactor — `merge_id` is a
  `uuid`, not the `(nwb_file_name, sort_group_id, …)` key v0 used.
