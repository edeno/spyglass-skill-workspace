# Cross-correlation matrices in a longblob column: workable, but not ideal

Short answer: it will run, but you're picking the design that Spyglass / DataJoint conventions explicitly steer you away from. At ~5 MB × a few hundred groups (~1-2 GB total), longblob is on the borderline where the costs start to matter. I'd recommend storing the matrix as an external file (NWB/AnalysisNwbfile or DataJoint `filepath@`/`attach@` store) rather than as a row-inline blob, and keeping only metadata + a path in the table.

## Why longblob works mechanically

DataJoint's `longblob` is a MySQL `LONGBLOB` (max 4 GB per cell), serialized via DataJoint's blob protocol (numpy-aware, lossless for ndarrays). 5 MB per row is well under the per-cell ceiling, and a few hundred rows × 5 MB ≈ 1-2 GB total is not catastrophic for MySQL — InnoDB will handle it. So nothing will break on day one.

## Why it's not the convention in Spyglass

A few real costs accumulate:

1. **Every `fetch()` pulls the whole blob.** DataJoint has no column projection that excludes a single blob — `MyTable & key` followed by `.fetch1()` deserializes the full 5 MB even if you only wanted `group_name`. You can `.fetch1("KEY")` or `.proj()` to dodge it, but it's an easy footgun, especially in joins. Browsing the table in a notebook becomes painful.

2. **Backups, replication, and migrations get expensive.** The MySQL dump grows by gigabytes of data that compresses poorly (numpy bytes are already dense). Spyglass deployments that share a database (the common lab pattern) will feel this — the DB is the shared resource, scratch disk is not.

3. **The blob is opaque to anyone but the producing code.** No NWB metadata, no units, no axis labels, no provenance about bin width or lag range. Six months later you'll have a `(N, N, n_lags)` array and have to read the populate code to remember what axis is what.

4. **Spyglass's house style is "small metadata in DJ, arrays in NWB."** Look at how `SortedSpikes`, `LFPV1`, `DecodingV1`, `PositionV1` etc. are structured — the DJ row holds keys + an `analysis_file_name` (or equivalent), and the actual arrays live in an `AnalysisNwbfile` written through `AnalysisNwbfile().create()` / `.add()`. That convention exists precisely because per-row blobs scale badly. (See `src/spyglass/common/common_nwbfile.py` and any of the `*_v1` analysis tables for the pattern.)

## What I'd actually recommend

In rough order of preference:

**Option A — AnalysisNwbfile (most Spyglass-idiomatic).** Store the cross-correlation matrix as a `DynamicTable` or `NWBDataInterface` inside an analysis NWB file, and keep `analysis_file_name` + `object_id` in the DJ table. You inherit Spyglass's file-management, cleanup, and sharing machinery. Schema becomes:

```
-> SortedSpikesGroup
group_name : varchar(...)
---
-> AnalysisNwbfile
xcorr_object_id : varchar(40)
bin_width_ms : float           # keep small scalars inline
max_lag_ms : float
n_units : int
```

**Option B — DataJoint external store (`filepath@store` or `blob@store`).** If you don't want to touch NWB, configure an external blob store in your `dj.config["stores"]` and declare `xcorr_matrix : blob@xcorr_store`. The bytes live on disk/S3, the DB row holds only a hash. This keeps your current schema shape and removes the bloat-the-DB problem, but you lose the NWB self-description.

**Option C — Just use `longblob` and accept the costs.** Reasonable if (i) this is a personal/scratch schema not shared with the lab, (ii) you'll rarely fetch and never browse, and (iii) the analysis is short-lived. At a few hundred rows it won't bring the DB down. Add a comment in the table definition recording `bin_width`, `max_lag`, and matrix axis order, since the blob carries no metadata.

## Things to nail down regardless of option

- **What exactly is `xcorr_matrix`?** A `(n_units, n_units, n_lags)` array? Symmetric pairs only? Normalized or raw counts? Auto-correlations on the diagonal? Document this — and prefer storing as a structured object (NWB `DynamicTable` with unit-pair rows) over a raw ndarray when feasible.
- **Bin width and lag range** must be table attributes, not buried in the blob. Otherwise you can't query "give me the 1 ms-binned ones."
- **Parameter table.** Standard Spyglass pattern is `XCorrParams` (a `dj.Lookup` or `dj.Manual` with `xcorr_params_name` PK and a `params : blob`/`longblob` of the dict), then your computed table is `-> SortedSpikesGroup` + `-> XCorrParams`. This lets you recompute under different bin widths without schema churn.
- **Make it a `dj.Computed`** with a `make()` method that fetches spike trains from `SortedSpikesGroup.fetch_spike_data()`, computes pairwise cross-correlograms (e.g., via `elephant.spike_train_correlation.cross_correlation_histogram` or a vectorized numpy implementation), and inserts.

## Honest unknowns

- I haven't checked your specific Spyglass version for the exact `SortedSpikesGroup` API — recent versions expose `fetch_spike_data()` returning a list of spike-time arrays; confirm against your installed `src/spyglass/spikesorting/spikesorting_merge.py` / `analysis/v1/group.py`.
- "A few hundred groups × 5 MB" is fine; if this grows to thousands of groups or 50 MB matrices, Option A/B stops being optional.

## Bottom line

Reasonable as a quick prototype. Not what I'd ship as a shared lab table. Move the array to an AnalysisNwbfile (Option A) and your future self — and your DBA — will thank you.
