## Short answer: no — push back on this design

The schema you proposed violates a Spyglass authoring non-negotiable, and a couple of details in the schema string itself are wrong. I'd recommend rerouting the matrix to an `AnalysisNwbfile` and keeping only metadata in the DataJoint row. Details below.

## What's wrong

### 1. ~5 MB blobs in DataJoint columns is the exact case the framework tells you to avoid

From `custom_pipeline_authoring.md` Non-Negotiable #4 (which mirrors `docs/src/ForDevelopers/Schema.md`):

> Write analysis outputs to `AnalysisNwbfile` when the result is sizeable (arrays, waveforms, posteriors). **Keep only small metadata in DataJoint columns.** Tables should reference exactly one AnalysisNwbfile table — Spyglass validates this on declaration.

And from the same reference's "AnalysisNwbfile Storage Pattern" section:

> Outputs too large for DataJoint columns (arrays, waveforms, posteriors, timeseries) go into an AnalysisNwbfile. The DataJoint row stores only the filename and object IDs.

A few hundred groups × ~5 MB ≈ 1–2 GB of blob payload pushed through MySQL. Concrete consequences:

- Every `fetch()` round-trips the blob through the DB even when you only wanted to enumerate `group_name`s. `(MyXcorr & key).fetch("KEY")` is fine, but anything that pulls the full row drags the matrix.
- MySQL `longblob` is technically up to 4 GB per cell, but lab DBs typically have `max_allowed_packet` tuned for small rows; a 5 MB blob is not the failure point, but a `*` join that materializes many of them can be.
- Backups, replication, and `mysqldump` all balloon. The lab-shared MySQL instance is shared infra; a single user's xcorr pipeline shouldn't dominate it when files-on-disk via NWB are the standard path.
- You lose self-describing metadata. NWB scratch / processing modules carry units, axis labels, unit IDs alongside the matrix; a `longblob` is just bytes.

The `~5 MB` threshold isn't itself in the skill text as a hard line — the rule is qualitative ("sizeable"). But cross-correlation matrices for all-pairs of units are exactly the "arrays / waveforms / posteriors" shape the rule is targeting. Treat it as a no.

### 2. Two schema-string problems independent of the size question

Your proposed definition:

```
-> SortedSpikesGroup
group_name
xcorr_matrix : longblob
```

- **`group_name` is redundant.** `SortedSpikesGroup`'s primary key is already `(nwb_file_name, unit_filter_params_name, sorted_spikes_group_name)` (see `spikesorting_v1_analysis.md` "SortedSpikesGroup" section, sourced from `src/spyglass/spikesorting/analysis/v1/group.py`). The FK arrow `-> SortedSpikesGroup` already pulls `sorted_spikes_group_name` into your PK. Adding a separate `group_name` either (a) is a typo for the existing field, in which case it's a duplicate, or (b) introduces a second per-group identifier with no source of truth, which makes restrictions ambiguous. Drop it.
- **No params / selection separation.** From Non-Negotiable #3: "Keep Parameters, Selection, and Computed tables separate." A cross-correlation pipeline has at minimum a bin width and lag window. If you ever want to re-run with different bins, a single Computed table with no Params table forces you to delete rows. The Five-Step Decision Tree (Params → Selection → Computed) applies even for "one analysis, run a few hundred times."
- **Tier not specified.** You'll want `dj.Computed` with `make()`, not `dj.Manual`, since the matrix is derived deterministically from `SortedSpikesGroup` + params.

## What to do instead

Skeleton (adapted from the canonical template in `custom_pipeline_authoring.md`, "Canonical Schema Skeleton"):

```python
import datajoint as dj
from spyglass.common.common_nwbfile import AnalysisNwbfile
from spyglass.spikesorting.analysis.v1.group import SortedSpikesGroup
from spyglass.utils import SpyglassMixin

schema = dj.schema("yourdjuser_xcorr")  # <database.user>_<suffix>; not spyglass_*

@schema
class XCorrParams(SpyglassMixin, dj.Lookup):
    definition = """
    xcorr_params_name: varchar(32)
    ---
    xcorr_params: blob   # small dict — ok in DJ
    """
    contents = [
        ["default", {"bin_ms": 1.0, "window_ms": 100.0}],
    ]

@schema
class XCorrSelection(SpyglassMixin, dj.Manual):
    definition = """
    -> SortedSpikesGroup
    -> XCorrParams
    """

@schema
class XCorr(SpyglassMixin, dj.Computed):
    definition = """
    -> XCorrSelection
    ---
    -> AnalysisNwbfile
    xcorr_object_id: varchar(40)
    """

    def make(self, key):
        params = (XCorrParams & key).fetch1("xcorr_params")
        nwb_file_name = (SortedSpikesGroup & key).fetch1("nwb_file_name")

        spike_times, unit_ids = SortedSpikesGroup().fetch_spike_data(
            key, return_unit_ids=True
        )
        # ... compute xcorr_array (n_units, n_units, n_lags) ...

        with AnalysisNwbfile().build(nwb_file_name) as builder:
            obj_id = builder.add_nwb_object(xcorr_array, table_name="xcorr")
            analysis_file_name = builder.analysis_file_name

        self.insert1({
            **key,
            "analysis_file_name": analysis_file_name,
            "xcorr_object_id": obj_id,
        })
```

Notes on the skeleton:

- **Schema name** must be `<database.user>_<suffix>` — not `spyglass_*` (that hits a MySQL permission error at `dj.schema(...)` call time). See "Schema Naming and Your Write Surface" in `custom_pipeline_authoring.md`.
- **`SpyglassMixin` first** in the MRO — required, per Non-Negotiable #1.
- **`build()` context manager** is the supported path for AnalysisNwbfile writes; mixing `create()` / `add()` / `add_nwb_object()` raises "Cannot call add_nwb_object() in state: REGISTERED."
- **Pass `table_name` explicitly** — default is `"pandas_table"`; multiple objects in scratch space without distinct names collide.
- **No merge table.** Single source, single implementation — Merge Table Guardrail says skip it.

## When the longblob shape *is* OK

Just so the rule isn't all-or-nothing: small fixed-shape blobs (param dicts, short summary stats, a vector of N≤100 floats) are fine in DataJoint columns. Spyglass's own `*Params` tables use `blob` for parameter dicts. The line is qualitative and the skill text uses "sizeable" — a 5 MB matrix per row at hundred-group cardinality clears that line.

## Summary

- Don't put the matrix in `longblob`. Route it through `AnalysisNwbfile` and store `analysis_file_name` + `xcorr_object_id` in the DJ row.
- Drop the redundant `group_name` (the FK to `SortedSpikesGroup` already supplies `sorted_spikes_group_name`).
- Split into Params + Selection + Computed so re-runs with different bin widths don't require deletes.
- Use `dj.Computed` with `make()`, `SpyglassMixin` first in MRO, schema name `<your_dj_user>_xcorr`.
