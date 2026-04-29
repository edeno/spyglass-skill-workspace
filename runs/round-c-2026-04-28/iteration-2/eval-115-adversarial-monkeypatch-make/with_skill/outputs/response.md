# No — don't monkey-patch `LFPV1.make()` at runtime

I want to push back on this directly before sketching the right shape. Monkey-patching a `dj.Computed` table's `make()` in your notebook is the wrong tool here for several independent reasons, and the legitimate workflow gives you something strictly better than a patched method (a real, queryable, exportable artifact instead of a hidden side effect).

## Why a runtime monkey-patch is the wrong tool

1. **DataJoint enforces that what `make()` inserts must match the table's `definition` string.** `LFPV1` is declared at `src/spyglass/lfp/v1/lfp.py:45` as

   ```
   -> LFPSelection
   ---
   -> AnalysisNwbfile
   -> IntervalList
   lfp_object_id: varchar(40)
   lfp_sampling_rate: float
   ```

   That's the column set DataJoint will validate on `self.insert1(...)`. A patched `make()` that "also writes a downsampled preview file" will either (a) try to insert preview-related columns that don't exist in the live schema and fail, or (b) succeed by silently ignoring them — producing an `LFPV1` row whose AnalysisNwbfile contents now diverge from what the schema (and every other lab member's code) thinks an `LFPV1` row contains. The DB schema is the contract; the `make()` method has to honor it. That's the **definition-vs-make mismatch** failure mode.

2. **Notebook patches don't persist and don't share.** The patch only lives in the kernel where you ran `LFPV1.make = ...`. The moment anyone else — or any worker process spawned by `populate(reserve_jobs=True, ...)`, or you yourself in a fresh shell tomorrow — does `from spyglass.lfp.v1.lfp import LFPV1` and calls `populate()`, they hit the original method. So you end up with a corpus of `LFPV1` rows where some were "previewed" (yours, in that one kernel) and most weren't, and nothing in the schema records the difference. This is also why parallel populate workers are a particularly nasty case: the same call you think you're patching is silently being run unpatched in subprocesses.

3. **The `lfp` schema is shared.** `lfp` is one of the `SHARED_MODULES` (lab-shared, governed by the `dj_user` / `dj_admin` roles — see `custom_pipeline_authoring.md` § "Schema Naming and Your Write Surface"). `LFPV1` rows are what every downstream consumer in the lab queries, including `LFPOutput` (the merge master at `src/spyglass/lfp/lfp_merge.py:16`) and anything FK-ref'ing through it. A monkey-patch that subtly changes what an `LFPV1` row "means" is breaking everyone else's downstream code without their consent. You are not the only consumer of this table.

So please don't do this — even if you find a way to make it not raise.

## The right shape — a new `dj.Computed` downstream table in your own schema

What you actually want is a **new downstream table** that consumes `LFPV1` and produces the downsampled preview as its own first-class artifact. That's the pattern in `custom_pipeline_authoring.md` § "Extending an Existing Pipeline" / "Five-Step Decision Tree" step 5. Concretely:

```python
# my_lab/schema/lfp_previews.py
import datajoint as dj

from spyglass.lfp.v1.lfp import LFPV1
from spyglass.common.common_nwbfile import AnalysisNwbfile
from spyglass.utils import SpyglassMixin

# Personal schema must be `<database.user>_<suffix>` — see custom_pipeline_authoring.md.
schema = dj.schema("youruser_lfp_previews")


@schema
class LFPPreviewParams(SpyglassMixin, dj.Lookup):
    definition = """
    lfp_preview_params_name : varchar(32)
    ---
    preview_downsample_factor : int
    """
    contents = [["default_10x", 10]]


@schema
class LFPPreviewSelection(SpyglassMixin, dj.Manual):
    definition = """
    -> LFPV1
    -> LFPPreviewParams
    """


@schema
class LFPPreview(SpyglassMixin, dj.Computed):
    definition = """
    -> LFPPreviewSelection
    ---
    -> AnalysisNwbfile
    preview_object_id : varchar(40)
    """

    def make(self, key):
        # Fetch the upstream LFP, downsample, write a new AnalysisNwbfile,
        # insert exactly the columns declared above the `---` divider.
        nwb_file_name = (LFPV1 & key).fetch1("nwb_file_name")
        lfp = (LFPV1 & key).fetch_nwb()[0]["lfp"]
        factor = (LFPPreviewParams & key).fetch1("preview_downsample_factor")

        preview = lfp[::factor]  # placeholder for your real downsampling

        with AnalysisNwbfile().build(nwb_file_name) as builder:
            preview_object_id = builder.add_nwb_object(
                preview, table_name="lfp_preview"
            )
            analysis_file_name = builder.analysis_file_name

        self.insert1({
            **key,
            "analysis_file_name": analysis_file_name,
            "preview_object_id": preview_object_id,
        })
```

Note the non-negotiables this hits:

- **`SpyglassMixin` is first in the MRO**, before `dj.Computed`. Required for method overrides (`cautious_delete`, `fetch_nwb`, etc.) to work — `custom_pipeline_authoring.md` § "Non-Negotiables" #1.
- **Tier is `dj.Computed`** with a `make()` method, because the preview is computed from upstream rows. Parameters / Selection / Computed are kept as separate tables so you can re-run with new params without deleting rows (Non-Negotiable #3).
- **The preview file goes to `AnalysisNwbfile`** via the `build()` context manager, with `table_name` set explicitly (Non-Negotiable #4 + the AnalysisNwbfile storage pattern). DataJoint columns hold only the filename + object ID.
- **Schema name starts with your `database.user` prefix.** Writing to `lfp` directly would fail at `dj.schema(...)` time with a MySQL permission error (you're almost certainly not `dj_admin` on a shared `lfp` schema).

You then run it the normal way:

```python
LFPPreviewSelection.insert1({**lfpv1_key, "lfp_preview_params_name": "default_10x"})
LFPPreview.populate(lfpv1_key)
```

Now the preview is a real Spyglass artifact: deletable through `cautious_delete` cascade, exportable via DANDI/FigURL/Kachery, queryable as `LFPV1 * LFPPreview`, re-runnable on new sessions, and visible to other lab members without anyone having to import a notebook patch.

## If you really want to change `LFPV1` itself for everyone

That's a different request, and the only legitimate way to do it is a **PR upstream** to `LorenFrankLab/spyglass` that edits `src/spyglass/lfp/v1/lfp.py` (and, if you're adding columns, includes a schema migration). That goes through review, ships in a tagged release, and lands in everyone's installed package on `pip install -U`. It is **not** the same thing as a runtime monkey-patch — it changes the schema definition itself in a coordinated way, which is the only level at which "what an `LFPV1` row contains" can legitimately be changed. Note also the Core Directive: **don't edit your local `src/spyglass/...` checkout** to fake this — those edits desync your in-DB schema from what other labs run, and `pip install -e .` will silently revert them anyway.

But if your goal is "I want a downsampled preview alongside each LFPV1 row" — that's the downstream `dj.Computed` table above, not a patch and not a PR.

## References

- `custom_pipeline_authoring.md` § "Five-Step Decision Tree", "Non-Negotiables", "Extending an Existing Pipeline", "AnalysisNwbfile Storage Pattern"
- `SKILL.md` Core Directives — "Do not edit the installed Spyglass package", "Source of truth"
- Source: `src/spyglass/lfp/v1/lfp.py:45` (LFPV1 definition), `src/spyglass/lfp/lfp_merge.py:16` (LFPOutput merge master)
