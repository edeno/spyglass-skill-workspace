For what you're describing — a Computed table in your own schema that produces a waveform-feature array, writes it into an AnalysisNwbfile, and registers the file — the first reference I'd reach for in the spyglass skill is the **custom pipeline / "writing your own table"** reference.

In the skill's `references/` directory that's the file that covers building a new `dj.Computed` table inside Spyglass conventions: subclassing `SpyglassMixin` alongside `dj.Computed`, structuring the `make()` method, and the AnalysisNwbfile lifecycle — i.e. the pattern

1. `nwb_file_name = AnalysisNwbfile().create(key["nwb_file_name"])` to get a fresh analysis file,
2. open it with `pynwb.NWBHDF5IO(...)`, add your waveform-features container (typically as a `pynwb.core.DynamicTable` / `ScratchData` / a processing-module entry, or via `AnalysisNwbfile().add_nwb_object(...)` to get back an object_id),
3. `AnalysisNwbfile().add(key["nwb_file_name"], nwb_file_name)` to register the new analysis file in the `AnalysisNwbfile` table,
4. store `analysis_file_name` and the returned `object_id` on the key, and `self.insert1(key)`.

That's the canonical Spyglass write path and it's what the custom-pipeline reference exists to walk you through. Concretely, in this repo I'd open `skills/spyglass/references/` and look for the file whose name matches "custom pipeline" / "writing tables" / "analysis nwb" — that's the resource-first hit for this task before I touched any of the more topic-specific references (spike sorting, LFP, decoding, etc.), because none of those apply: the question is about *authoring* a Computed table, not consuming an existing pipeline.

Secondary references I'd pull in only if needed:

- the **merge-table** reference, *only if* you intend the new table to feed a `_Merge` table downstream (waveform features often do — e.g., as a sibling of an existing waveform pipeline). If it's a leaf table, skip this.
- the **AnalysisNwbfile / file management** reference (sometimes split out separately from the custom-pipeline doc) for the exact `create` / `add` / `add_nwb_object` signatures and the rules about not editing an analysis file after `add()`.
- the **common debugging / populate failures** reference if `populate()` misbehaves — but only after the table is written.

The two non-obvious things the custom-pipeline reference will save you from getting wrong:

- **Inherit `SpyglassMixin` first**, before `dj.Computed`, so the mixin's `fetch_nwb`, permission, and export-tracking hooks land correctly. `class WaveformFeatures(SpyglassMixin, dj.Computed):`.
- **Register the analysis file with `AnalysisNwbfile().add(...)` inside `make()` after you've written and closed it**, and store `analysis_file_name` on the key. If you forget the `add()` call, the file exists on disk but Spyglass (and DANDI/FigURL export) won't know about it, and downstream `fetch_nwb` will fail.

So: custom-pipeline reference first, AnalysisNwbfile reference second if it's a separate doc, merge-table reference only if you're plugging into one.
