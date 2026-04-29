# Deleting decoding results in Spyglass

There's no single "delete my decoding results" command — you need to restrict the right table to your nwb_file_name and call DataJoint's `.delete()` on that restriction. Before I give the snippet, two things to pin down, because they change which table you actually want to hit.

## Disambiguate first

1. **Which decoding pipeline?** Spyglass has two v1 decoding pipelines, in different schemas:
   - `spyglass.decoding.v1.clusterless.ClusterlessDecodingV1` (clusterless / waveform-feature decoding)
   - `spyglass.decoding.v1.sorted_spikes.SortedSpikesDecodingV1` (sorted-unit decoding)
   They each have their own selection table (`...DecodingSelection`), parameters table, and output table. "Decoding results" usually means rows of the `...V1` populate-output table. If you ran both, you'll need to delete from both.

2. **What scope of "results"?** Typically one of:
   - **Just the populated outputs** for that NWB (keep selection rows so you can re-populate): restrict the `*V1` table and delete.
   - **Selection + outputs** (start over from scratch for that file): restrict the `*Selection` table and delete; cascading deletes will take the populated rows with it.
   - **Everything downstream of the NWB** (extreme — wipes position, spike sorting, LFP, etc., not just decoding): `Nwbfile & {'nwb_file_name': ...}` then `.delete()`. Almost certainly not what you want.

I'll assume you mean "delete the populated decoding outputs for `j1620210710_.nwb`, both pipelines, keep upstream intact."

## The command

```python
from spyglass.decoding.v1.clusterless import ClusterlessDecodingV1
from spyglass.decoding.v1.sorted_spikes import SortedSpikesDecodingV1

nwb_file_name = "j1620210710_.nwb"   # note the trailing underscore — Spyglass's copy name
restr = {"nwb_file_name": nwb_file_name}

# Inspect first — never delete blind
(ClusterlessDecodingV1 & restr)
(SortedSpikesDecodingV1 & restr)

# Then delete
(ClusterlessDecodingV1 & restr).delete()
(SortedSpikesDecodingV1 & restr).delete()
```

DataJoint will print the rows to be deleted and prompt for confirmation. Read the prompt — it will also list any downstream rows that cascade out (e.g., anything that consumed the decoding output).

## Things to check before you run it

- **Filename suffix**: `j1620210710_.nwb` (with the trailing underscore before `.nwb`) is the Spyglass-copied name in `Nwbfile`, not the original raw filename. That's the right one to use here. If you only have the original (e.g., `j1620210710.nwb`), look it up in `Nwbfile()` first — `nwb_file_name` is the primary key Spyglass uses everywhere.
- **Merge table**: if your decoding output ever flowed into a merge table (`DecodingOutput` or similar), check `merge_get_part`/`merge_restrict` to see what's downstream before deleting; otherwise you may get unexpected cascade prompts.
- **Don't use `delete_quick()`** unless you've already verified there's no downstream cascade — it skips the safety prompt and the cascade check.
- **Files on disk**: `.delete()` removes the DB rows. Stored analysis files (e.g., decoding result `.nc`/`.pkl` under `SPYGLASS_BASE_DIR/analysis/...`) are normally cleaned by Spyglass's `cleanup()` workflow, not by `.delete()`. If you want the disk space back, run the project's cleanup utility after the DB delete.
- **Permissions**: you can only delete rows you inserted (or that your DataJoint user owns). If someone else populated those rows, ask them or an admin.

If you actually wanted scope #2 (wipe selection too) or #3 (wipe everything for that NWB), tell me and I'll give you the matching restriction.
