Good questions — both `merge_*` and `SpyglassMixin` are things Spyglass adds *on top of* plain DataJoint, which is why you won't find them in the DataJoint docs. Let me unpack each.

## 1. Merge tables — a Spyglass convention, not a DataJoint primitive

DataJoint itself only ships a handful of table tiers: `dj.Manual`, `dj.Lookup`, `dj.Imported`, `dj.Computed`, and `dj.Part`. There is no `dj.Merge`. What you're seeing with `PositionOutput` / `LFPOutput` is a **design pattern the Spyglass team built using vanilla DataJoint pieces** (a master table plus several part tables) and then dressed up with helper methods.

### What problem it solves

Spyglass has multiple ways to produce "the same kind of result." For position, for example, you can get an animal's position from:

- `TrodesPosV1` — the Trodes/SpikeGadgets-derived position pipeline,
- `DLCPosV1` — DeepLabCut-based pose estimation,
- `CommonPos` — the older `IntervalPositionInfo` path,
- `ImportedPose` — pose data that was already in the source NWB file.

Downstream analyses (decoding, ripple detection, linearization, etc.) don't want to care *which* of those produced the position — they just want "the position for this session." A merge table is the indirection layer that lets that work.

### How it's structured

Look at `spyglass/position/position_merge.py` and you'll see the shape:

```python
@schema
class PositionOutput(_Merge, SpyglassMixin):
    definition = """
    merge_id: uuid
    ---
    source: varchar(32)
    """

    class TrodesPosV1(SpyglassMixin, dj.Part):
        definition = """
        -> PositionOutput
        ---
        -> TrodesPosV1
        """

    class DLCPosV1(SpyglassMixin, dj.Part):
        definition = """
        -> PositionOutput
        ---
        -> DLCPosV1
        """
    # ... CommonPos, ImportedPose, etc.
```

So the convention is:

- The **master** table (`PositionOutput`) has just two columns: a UUID `merge_id` (the only primary key) and a `source` string saying which upstream pipeline this row came from.
- Each **part** table inside it (`PositionOutput.TrodesPosV1`, `PositionOutput.DLCPosV1`, …) holds a foreign key back to the actual upstream result row. One part per upstream source.
- A given `merge_id` lives in exactly one of those part tables, and the master row's `source` field tells you which one.

The master is `dj.Manual`-tier under the hood (entries are inserted, not computed via `make()`); it's the *part* tables that actually point at the per-pipeline results. Downstream tables foreign-key against `PositionOutput`, not against `TrodesPosV1` / `DLCPosV1` directly, which is the whole point — the downstream code doesn't have to branch on which pipeline produced position.

### What the `merge_*` helpers do

Because this is a Spyglass-invented pattern, DataJoint doesn't know anything about it, so Spyglass adds methods on the merge master to traverse the master/part structure:

- `merge_restrict(restriction)` — apply a normal DataJoint restriction (e.g. `{"nwb_file_name": "minirec.nwb"}`) and get back the matching `merge_id`s, regardless of which part they live in. This is the "give me the rows for this session, I don't care which pipeline" call.
- `merge_get_part(restriction)` — given a restriction, return the actual part table(s) holding those rows, so you can join through to the upstream pipeline-specific attributes.
- `merge_fetch` / `fetch_nwb` on the merge — gathers NWB files across whichever parts the rows live in, again hiding the source-pipeline details.

These are mostly classmethods on the merge master (defined in `spyglass.utils.dj_merge_tables.Merge`, which `_Merge` aliases). They exist purely because plain DataJoint has no notion of "this master + its parts collectively represent one logical output," so Spyglass had to build that abstraction itself.

**Where to read about this in the project:** the canonical introduction to Spyglass's data model — including merge tables and how they fit into the pipeline graph — is the **`01_Concepts.ipynb`** notebook in `notebooks/`. Start there before anything deeper. There is a more specialized `04_Merge_Tables.ipynb` later in the notebook series that drills into the mechanics, but `01_Concepts.ipynb` is the right entry point for "what is this thing and why does it exist."

## 2. `SpyglassMixin` — what it adds on top of `dj.Computed`

Same general story: vanilla DataJoint gives you `dj.Computed` (and `Manual` / `Imported` / `Lookup`), and `SpyglassMixin` is an extra layer the project mixes in via Python multiple inheritance. So when you see something like

```python
class LFPV1(SpyglassMixin, dj.Computed):
    ...
```

you're getting a normal computed table that has been augmented with project-specific methods. Look at `spyglass/utils/dj_mixin.py` and you'll see `SpyglassMixin` is itself a stack of smaller mixins:

```python
class SpyglassMixin(
    CautiousDeleteMixin,
    ExportMixin,       # -> FetchMixin -> BaseMixin
    HelperMixin,
    PopulateMixin,
    RestrictByMixin,
):
    ...
```

Concretely, here's what each of those layers buys you that `dj.Computed` alone does not:

- **`fetch_nwb(...)`** (from the Fetch/Helper layers). This is the big one. Spyglass tables typically don't store their analysis blobs in DataJoint directly — they store a pointer to an `AnalysisNwbfile` (an NWB file on disk), and the actual arrays live in there. `fetch_nwb()` follows that pointer for you: it fetches the row, opens the right NWB file, and hands back the NWB object(s) you actually want to analyze. Plain DataJoint would just give you the file path; you'd have to open it yourself.
- **Upstream / downstream graph traversal (`<<` and `>>`)** (from `RestrictByMixin`). These operators let you walk the dependency graph by tier — "give me the upstream parents of this restricted set" / "give me the downstream children." Vanilla DataJoint can do this, but only via more verbose `.parents()` / `.children()` / repeated joins; the operators are a Spyglass ergonomics layer.
- **Cautious deletes** (`CautiousDeleteMixin`). Before deleting rows, Spyglass checks that the user is on the lab team for the affected `Session` (or is a `LabMember` admin). DataJoint's `delete()` will happily cascade-delete anything you have permissions on at the SQL level; this layer adds an application-level permission check so one user can't accidentally nuke another lab member's analyses.
- **Export hooks** (`ExportMixin`). Logs every fetch/restrict that touches the table during an "export" session, so that you can later reproduce a paper's analysis: Spyglass can replay exactly which rows fed into which figure, package the relevant NWB files, and ship them to DANDI / Kachery / FigURL. This is built on DataJoint's normal fetch path but layered with provenance tracking.
- **`PopulateMixin` behavior**. Wraps `populate()` with extra checks — transaction handling, hashing of the `make()` output to detect non-determinism, and validation of which `AnalysisNwbfile` foreign keys the table points at. Plain `dj.Computed.populate()` doesn't do any of that.
- **Misc helpers** (`HelperMixin`) — things like `get_params_blob_from_key()` for tables that store one parameter blob per primary key, schema-prefix sanity checks at instantiation, a guard that any table whose definition *looks* like a merge table actually inherits from `Merge`, etc.

So you can think of it as: `dj.Computed` gives you "a SQL-backed computed table"; `SpyglassMixin` adds the NWB-aware fetch path, the lab-permissions layer, the reproducibility/export plumbing, and ergonomic graph traversal that this particular project needs across hundreds of tables.

## TL;DR + where to start reading

- **Merge tables** are a **Spyglass convention** layered on plain DataJoint master+part tables. `PositionOutput`'s parts (`TrodesPosV1`, `DLCPosV1`, `CommonPos`, `ImportedPose`) each represent a different upstream pipeline; `merge_id` is the unified handle, and the `merge_*` helpers traverse master ↔ part for you. They're not a DataJoint primitive; you won't find them in DataJoint's docs.
- **`SpyglassMixin`** layers project-specific behavior on top of any DataJoint tier: `fetch_nwb` for NWB-aware fetches, `<<` / `>>` for graph traversal, cautious deletes, export/reproducibility hooks, and a wrapped `populate()`.

For the full conceptual tour with diagrams, read **`notebooks/01_Concepts.ipynb`** in the Spyglass repo first — that's the canonical "what is the data model" notebook and the right place to start before diving into pipeline-specific notebooks. For source: `spyglass/utils/dj_merge_tables.py` is the merge-table machinery and `spyglass/utils/dj_mixin.py` plus `spyglass/utils/mixins/` is `SpyglassMixin`.
