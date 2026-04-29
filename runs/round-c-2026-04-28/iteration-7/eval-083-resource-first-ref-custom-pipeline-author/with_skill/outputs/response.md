Open **`references/custom_pipeline_authoring.md`** first.

That's the right entry point because your task is *authoring* a new pipeline (a new `dj.Computed` table in your own schema, with `make()` writing to an `AnalysisNwbfile`), not *using* an existing pipeline. The Spyglass SKILL.md routing table sends "Authoring custom tables or pipelines / extending existing ones" to this single reference, and it's stage 5 ("Pipeline authoring") in the stage classifier — explicitly distinguished from stage 4 ("Pipeline usage").

What that file gives you, in the order you'll need it:

1. **Schema Naming and Your Write Surface** — your schema must be `<database_user>_<suffix>` (matching `dj.config["database.user"]`); MySQL enforces this at `dj.schema()` call time. Common hallucination: do NOT prefix with `spyglass_` — there is no implicit framework namespace, and lab-shared names are an explicit allowlist (`SHARED_MODULES`).
2. **Five-Step Decision Tree** — pick the smallest scaffold that fits: optional grouping (`dj.Manual`) → `Parameters` (`dj.Lookup`) → `Selection` (`dj.Manual`) → `Computed` (with `make()`). Keep these tables separate (Non-Negotiable #3); don't combine params into the Computed table.
3. **Non-Negotiables** — the rules that cause silent or mysterious failures:
   - `SpyglassMixin` must be **first** in the MRO, before `dj.Computed` (and `SpyglassMixinPart` for any part tables).
   - Choose the right tier (`dj.Computed` for an analysis output produced by `make()`).
   - Outputs sized like waveform-feature arrays go to **`AnalysisNwbfile`**, not into a DataJoint blob column. A table may reference exactly one AnalysisNwbfile table — Spyglass validates this on declaration.
   - Don't introduce a merge table unless you actually have multiple interchangeable implementations.
   - Never call `IntervalList.insert1(..., skip_duplicates=True)` from inside your `make()` — it bypasses the orphan-cleanup protection and can silently re-attach new computations to stale interval rows.
4. **Canonical Schema Skeleton** — a runnable Params/Selection/Computed/Part template you can copy and fill in. Two specific things to mirror:
   - Use the **`AnalysisNwbfile().build(nwb_file_name)` context manager** to wrap the CREATE → POPULATE → REGISTER lifecycle. Do NOT mix it with separate `create()` / `add()` / `add_nwb_object()` calls — that path raises `Cannot call add_nwb_object() in state: REGISTERED`.
   - Always pass `table_name=...` explicitly to `builder.add_nwb_object(...)` (default is `"pandas_table"`, so multiple writes collide in scratch space and retrieval fails).
   - Insert the master row **before** the part rows; the master row carries `analysis_file_name` + `result_object_id` (the fields below the `---` divider), not just the bare `key`.
5. **AnalysisNwbfile Storage Pattern** — the canonical write block for your case (a numpy/array result), plus the anti-pattern that produces the REGISTERED-state error. There's also a useful audit hook: `AnalysisRegistry().all_classes` (from `spyglass.common.common_nwbfile`) lists every registered `AnalysisNwbfile` subclass across the lab, in case another team has already authored one for related output.

Things to *skip* in that file for this task:
- The "Single Custom Table (Not a Pipeline)" section — you're authoring a Computed pipeline, not a one-off Manual table.
- The "Merge Table Guardrail" section — only relevant if you have multiple interchangeable implementations of the same waveform-feature analysis. For a single Computed table, let any future downstream tables FK-ref it directly.

If, after reading `custom_pipeline_authoring.md`, you find you're consuming output from one of the merge masters (`SpikeSortingOutput`, `LFPOutput`, `PositionOutput`, `LinearizedPositionOutput`, `DecodingOutput`) as the upstream input to your waveform-feature computation, then `references/merge_methods.md` is the natural follow-up — for the `merge_get_part` / `merge_get_parent` / `fetch1_dataframe` accessor surface and per-source method-availability gotchas. But start with `custom_pipeline_authoring.md`; it's the one reference that covers the whole shape of what you're building.

Authoritative paths the reference points back to (read these in the Spyglass repo if you want the source of truth):
- `docs/src/ForDevelopers/CustomPipelines.md`
- `docs/src/ForDevelopers/TableTypes.md`
- `docs/src/ForDevelopers/Schema.md`
- `docs/src/ForDevelopers/Classes.md`
