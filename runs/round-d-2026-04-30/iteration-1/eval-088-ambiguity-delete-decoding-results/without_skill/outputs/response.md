There isn't one single command — "delete my decoding results" is ambiguous in Spyglass and the right answer depends on three things you haven't specified. Let me lay out the choices, then give you the command for the most common case.

## Three things I need to know

### 1. Which decoding pipeline?

Spyglass has two parallel v1 decoders, plus a merge table that ties them together:

- `spyglass.decoding.v1.clusterless.ClusterlessDecodingV1` — clusterless (waveform-feature) decoding
- `spyglass.decoding.v1.sorted_spikes.SortedSpikesDecodingV1` — sorted-spike decoding
- `spyglass.decoding.decoding_merge.DecodingOutput` — the merge table that registers entries from either of the above

If you have entries in both pipelines for this NWB file and you want both gone, you need to delete from both, or delete from the merge table (which cascades into the appropriate part).

(There is also a deprecated `spyglass.decoding.v0` namespace. If your results came from v0, the table names differ and the same restriction keys won't match.)

### 2. Just the rows, or also the upstream `…Selection` rows?

`ClusterlessDecodingV1` and `SortedSpikesDecodingV1` are `dj.Computed` tables. Their `make()` populates them from a `…Selection` (`dj.Manual`) row that you inserted earlier:

- `ClusterlessDecodingSelection`
- `SortedSpikesDecodingSelection`

Deleting the computed row leaves the selection in place — meaning a future `populate()` will re-create the same result. If you actually want this configuration gone (so you can re-insert with different params), delete the selection row; DataJoint will cascade-delete the computed row, the merge entry, and the on-disk files (`results_path`, `classifier_path`) automatically.

If, on the other hand, you just want to free disk space and re-run later with the same selection, delete only the computed row.

### 3. Just this NWB file, or every decoding entry?

The primary key inherits `nwb_file_name` from `Session` via `UnitWaveformFeaturesGroup` / its sorted-spike equivalent, so a restriction like `{"nwb_file_name": "j1620210710_.nwb"}` is what you want. **Double-check the filename** — your message has `j1620210710_.nwb` with a trailing underscore before `.nwb`, which is unusual. Spyglass NWB filenames typically end in `_.nwb` (the trailing underscore is added by `make_copy_nwb` / the ingestion step), so this is probably correct, but verify with `Nwbfile() & 'nwb_file_name LIKE "j1620210710%"'` before deleting anything.

## The command (most common case)

If you just want all decoding rows for that session gone — both pipelines, including the merge entries and the on-disk `.nc` / `.pkl` files — delete from the merge table:

```python
from spyglass.decoding.decoding_merge import DecodingOutput

key = {"nwb_file_name": "j1620210710_.nwb"}

# Preview first — confirm it matches what you expect
(DecodingOutput.merge_restrict(key)).fetch("KEY")

# Then delete
DecodingOutput().delete(restriction=key)
# or equivalently:
(DecodingOutput & DecodingOutput.merge_restrict(key)).delete()
```

`DecodingOutput.delete()` is overridden (`spyglass/utils/dj_merge_tables.py:860`) to walk into each part table (clusterless / sorted-spikes), delete those rows under the normal Spyglass `cautious_delete` flow, then sweep up the orphaned master row. Because the part rows point at `filepath@analysis` external stores, DataJoint's external-file cleanup will also remove the `.nc` results file and `.pkl` classifier file, but **only after you run** `DecodingOutput.external_table_cleanup()` or `dj.errors.UnknownAttributeError`-free equivalent — DataJoint doesn't unlink external files at delete time, it marks them for cleanup.

If you want to wipe stranded result/model files left from prior failed runs (files on disk that aren't registered in the table), there's also:

```python
DecodingOutput().cleanup(dry_run=True)   # preview
DecodingOutput().cleanup()                # actually delete the orphaned files
```

That is *not* a substitute for deleting the table rows — `cleanup()` only removes files that are *already* unregistered.

## If you only want one of the two pipelines

```python
from spyglass.decoding.v1.clusterless import ClusterlessDecodingV1
# or:
from spyglass.decoding.v1.sorted_spikes import SortedSpikesDecodingV1

(ClusterlessDecodingV1 & {"nwb_file_name": "j1620210710_.nwb"}).delete()
```

This will prompt you for confirmation (Spyglass `cautious_delete` shows you cascaded downstream rows including the merge entry before committing). It also removes the corresponding `DecodingOutput` master row via the cascade.

## If you want to also wipe the Selection rows

```python
from spyglass.decoding.v1.clusterless import ClusterlessDecodingSelection
from spyglass.decoding.v1.sorted_spikes import SortedSpikesDecodingSelection

(ClusterlessDecodingSelection & {"nwb_file_name": "j1620210710_.nwb"}).delete()
(SortedSpikesDecodingSelection & {"nwb_file_name": "j1620210710_.nwb"}).delete()
```

Cascading from `…Selection` is the cleanest way to fully remove "this decoding run ever happened" — it takes out the selection, the computed row, the merge entry, and (after external cleanup) the files.

## Recommendation

1. First run the preview line (`DecodingOutput.merge_restrict(key).fetch("KEY")`) and look at the count and `source` field — confirm you're targeting the right rows and the right pipeline(s).
2. If you only want results gone but want to keep the selection so you can re-`populate()` later: delete from `DecodingOutput`.
3. If you want the configuration gone too: delete from the `…Selection` table(s).
4. After the delete, run `DecodingOutput().cleanup()` (or rely on DataJoint external-store cleanup) to actually unlink the `.nc` and `.pkl` files on disk.

If you tell me which pipeline you used and whether you want to keep the selection, I can give you the single exact line.
