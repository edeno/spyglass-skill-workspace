# Should you store a 5 MB cross-correlation matrix inline as a blob?

**Short answer: technically yes, but you really shouldn't, and Spyglass is built around the assumption that you won't.** The "AnalysisNwbfile plumbing" is annoying the first time, but it's a one-time cost that pays back continuously. Inline blobs look like a shortcut and turn into a debt.

Let me separate what's true from what's recommended.

## What's technically true

DataJoint supports `blob` and `longblob` attribute types backed by MySQL `MEDIUMBLOB` / `LONGBLOB`. A 5 MB NumPy array will serialize and store fine. So at the "will it work?" level, yes:

```python
@schema
class CrossCorr(SpyglassMixin, dj.Computed):
    definition = """
    -> SomeUpstream
    ---
    corr_matrix : longblob   # ~5 MB ndarray
    n_units     : int
    """
```

That will run. `(CrossCorr & key).fetch1("corr_matrix")` will hand you back the array. No NWB, no AnalysisNwbfile, no external file.

## Why Spyglass pushes you toward AnalysisNwbfile anyway

The convention in Spyglass is: **large numerical artifacts live in an NWB file on disk; the database stores the pointer + scalar metadata.** Look at `DecodingOutput`, `SpikeSortingOutput`, `LFPV1`, `PositionOutput`, etc. — they all follow the same shape: an `analysis_file_name` foreign key to `AnalysisNwbfile`, plus a small object-id string telling you where inside the file the data sits. The actual array is read lazily via pynwb.

Reasons that pattern exists, and reasons inline blobs hurt at scale:

1. **MySQL is not a bulk-array store.** Every fetch deserializes the entire blob into the client. There's no slicing, no lazy read, no chunked access. With NWB + HDF5 you can read one row of the matrix without pulling 5 MB across the wire.

2. **5 MB sounds small until you multiply.** One matrix per session × ~hundreds of sessions × a few parameter sweeps = gigabytes living inside the SQL server's tablespace. MySQL backups, replication, and `mysqldump` get ugly fast. AnalysisNwbfile keeps the SQL table tiny (kilobytes) and pushes bytes onto the lab filesystem / Kachery, which is sized for it.

3. **Sharing and provenance break.** Spyglass's export and sharing workflows (Kachery, `export.Export`) are built around AnalysisNwbfiles. An inline-blob table won't ride along when someone exports the analysis for a collaborator or for a paper. The data is stranded inside your database.

4. **You lose the NWB self-description.** Units, dimensions, electrode references, timestamps — all the metadata that makes the matrix interpretable a year from now — has nowhere to live next to the array. You'll end up adding `corr_axis_unit_ids : longblob`, `time_window : blob`, etc., reinventing a worse NWB.

5. **`SpyglassMixin.fetch_nwb()` and the rest of the ecosystem won't recognize your table.** Downstream tooling that walks `-> AnalysisNwbfile` won't find your artifact; figure-generation utilities, common populate helpers, and merge-table conventions assume the AnalysisNwbfile pattern.

6. **Schema migration pain.** Once a `longblob` column exists with terabytes of data, changing the storage layout means rewriting every row. With AnalysisNwbfile the SQL row is trivially mutable; the heavy data is decoupled.

## When inline blobs are actually fine

The convention isn't "no blobs ever." Small derived scalars and short vectors are routinely stored as `blob` in Spyglass tables — peak firing rates, fit parameters, short PSTH summaries, k-fold scores, a 100-element cluster-quality vector. Rule of thumb I'd use:

- **< ~100 KB and not user-facing data**: blob is fine.
- **100 KB – 1 MB**: judgment call; prefer AnalysisNwbfile if the artifact is something a user would ever want to plot, share, or version.
- **> 1 MB or array-shaped scientific data**: AnalysisNwbfile, basically always. 5 MB sits squarely in this bucket.

## The "I don't want to deal with the plumbing" part

That's the real objection, and it's fair — the AnalysisNwbfile dance is the steepest part of writing a custom Spyglass table the first time. But it's ~20 lines of boilerplate that you copy from any existing Spyglass `make()`, and it looks roughly like:

1. In `make()`, build your matrix.
2. `nwb_file_name = AnalysisNwbfile().create(key["nwb_file_name"])` to get a fresh analysis file.
3. Open it with `pynwb.NWBHDF5IO`, attach the matrix as a `DynamicTable` / `TimeSeries` / `Container` (a `DynamicTable` with one row holding the matrix is a common shortcut), grab the `object_id`.
4. `AnalysisNwbfile().add(key["nwb_file_name"], nwb_file_name)` to register it.
5. Insert a row containing `analysis_file_name` and the `object_id`.
6. Define `_nwb_table = AnalysisNwbfile` so `fetch_nwb()` works for free.

Search the Spyglass repo for `AnalysisNwbfile().create` and copy whichever existing `make()` is closest in shape (e.g. `src/spyglass/decoding/v1/...` or `src/spyglass/spikesorting/v1/...`). It's much less plumbing than it looks once you have a template.

## My recommendation

Use AnalysisNwbfile. The 5 MB number is a trap — it feels small in isolation but you'll have many of them, you'll want to share them, and you'll want lazy access eventually. Pay the one-time boilerplate cost now; future-you (and the rest of the lab) will not regret it.

If you genuinely want to prototype fast and you're going to throw the table away in a week, an inline `longblob` is fine for that prototype — just don't promote it to a real pipeline table without converting to AnalysisNwbfile first.
