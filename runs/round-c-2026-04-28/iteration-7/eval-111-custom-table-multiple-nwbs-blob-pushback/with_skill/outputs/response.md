# Inline blob vs AnalysisNwbfile for a ~5 MB cross-correlation matrix

Short answer: I'd push back. "Only ~5 MB" is exactly the size where this decision compounds badly, and the AnalysisNwbfile path is less plumbing than it looks once you use the `build()` context manager. Below is the reasoning, then what to do if you still want the blob.

## Why "just blob it" is the wrong default in Spyglass

This is one of the explicit non-negotiables for custom pipeline authoring (`docs/src/ForDevelopers/Schema.md`, summarized in the skill):

> Write analysis outputs to `AnalysisNwbfile` when the result is sizeable (arrays, waveforms, posteriors). Keep only small metadata in DataJoint columns.

A 5 MB correlation matrix per row is "sizeable" by Spyglass's convention. Concretely:

1. **Per-row size is not the right unit; total table size is.** 5 MB sounds harmless, but DataJoint blobs live in MySQL (specifically in the `external` store or directly in the row, depending on how you declare the column). A `blob@...` external store is fine; a bare `blob` or `longblob` column embeds the bytes in the InnoDB table and starts hurting `SELECT *`, `describe()`, backups, and replication once you have hundreds of rows. Even at 5 MB × 200 sessions × a few parameter sets you're at multiple GB of MySQL-resident bytes that nobody asked for.

2. **`fetch()` semantics differ.** With an AnalysisNwbfile, the DataJoint row is tiny (filename + object_id), so restrictions, joins, and `describe()` stay fast. Anyone doing `(MyTable & key).fetch()` to inspect rows will accidentally pull every 5 MB matrix in the restriction over the network if it's a column blob. With NWB, they have to opt in via `fetch_nwb()` / `fetch1_dataframe()`.

3. **Reproducibility / sharing.** AnalysisNwbfile rows are what `Export`, DANDI uploads, and Kachery sharing operate on. If your correlations live in a MySQL blob column, they don't ride along with a paper export — you'd have to reimplement the export path yourself.

4. **The "plumbing" you're avoiding is ~5 lines.** This is the entire write path inside `make()`:

   ```python
   from spyglass.common.common_nwbfile import AnalysisNwbfile

   nwb_file_name = (Session & key).fetch1("nwb_file_name")
   with AnalysisNwbfile().build(nwb_file_name) as builder:
       obj_id = builder.add_nwb_object(corr_matrix, table_name="cross_corr")
       analysis_file_name = builder.analysis_file_name

   self.insert1({**key,
                 "analysis_file_name": analysis_file_name,
                 "result_object_id": obj_id})
   ```

   The `build()` context manager handles the CREATE → POPULATE → REGISTER lifecycle for you — that's the part that used to be painful (the "Cannot call add_nwb_object() in state: REGISTERED" trap). Read on the way back out is `(MyTable & key).fetch_nwb()[0]["cross_corr"]` via the SpyglassMixin. There is no manual pynwb import in the user-facing path.

   The table definition is one extra line:

   ```
   -> AnalysisNwbfile
   result_object_id: varchar(40)
   ```

   versus

   ```
   corr_matrix: longblob
   ```

   Net cost of doing it the Spyglass way: ~5 lines of `make()` body, one FK ref, no separate file management on your part.

## Where the inline-blob shape *is* fine

Not everything needs to go to NWB. Inline blobs are appropriate for:

- **Small parameter dicts** on a `Parameters` table (the canonical pattern uses `myanalysis_params: blob`). Bytes are O(KB), reads are uniform, and Lookup-tier semantics make this the right place.
- **Small per-row scalars / vectors** that are intrinsic identifiers, not analysis outputs (e.g. a small lookup vector, a hash, a bounding-box tuple).
- **Truly one-off / throwaway exploration**, where the table exists in your personal schema (`<your_user>_scratch`) and you'll drop it. But "I have multiple NWBs, one row each" is not throwaway — you've already implied a real pipeline.

A 5 MB correlation matrix per session does not fit any of those categories.

## If you still want to do it anyway

Two cases where I'd grudgingly accept the blob:

1. **You want to externalize the blob** (recommended over bare `longblob`). Configure a `blob@store` external store in `dj.config["stores"]`, then declare:

   ```
   corr_matrix: blob@analysis
   ```

   This keeps MySQL light (just a hash) and parks the bytes on disk under your store path. It's still not as good as NWB (no DANDI / export integration, no `fetch_nwb()` semantics, no scratch-space typing), but it avoids the worst MySQL pathology.

2. **The matrix really is metadata, not output** — e.g., a small fixed-size summary statistic and the per-pair time courses live elsewhere. Then it's the same shape as a `Parameters`-style blob and the calculus is different.

If neither of those fits, the honest tradeoff is: "I'd save ~5 lines of `make()` code now, in exchange for a table that's slow to query, doesn't export cleanly, and won't share with collaborators via the standard Spyglass paths." That's a bad trade.

## My recommendation

Use `AnalysisNwbfile` with the `build()` context manager pattern. The "plumbing" is genuinely 5 lines once you've seen it once, and you get the standard Spyglass `fetch_nwb()` / export / sharing surface for free. If after writing it once you still find it heavy, that's a real signal worth revisiting — but the version of "AnalysisNwbfile is painful" that lives in lore is mostly from the pre-`build()` era when you had to interleave `create()` / `add()` / `add_nwb_object()` calls and could land in the REGISTERED-state error.

## Sources

- `/Users/edeno/Documents/GitHub/spyglass-skill/skills/spyglass/references/custom_pipeline_authoring.md` — Non-Negotiable #4 ("Write analysis outputs to AnalysisNwbfile when the result is sizeable") and the "AnalysisNwbfile Storage Pattern" section with the canonical `build()` context manager snippet.
- `docs/src/ForDevelopers/Schema.md` (Spyglass repo) — canonical schema skeleton with `-> AnalysisNwbfile` + `result_object_id: varchar(40)` shape.
- `docs/src/ForDevelopers/AnalysisTables.md` (Spyglass repo) — `build()` lifecycle and the REGISTERED-state error that motivated it.
