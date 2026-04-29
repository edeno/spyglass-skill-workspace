# Merge tables and `SpyglassMixin` — what they are and why DataJoint docs don't mention them

Short answer: both are **Spyglass conventions layered on top of DataJoint**, not DataJoint primitives. That's why nothing in the DataJoint docs covers them — they only exist once you import `spyglass.*`. Since you're new, the canonical place to read this end-to-end is `notebooks/01_Concepts.ipynb` in the Spyglass repo. Skip `04_Merge_Tables.ipynb` for now — it goes deeper into specialized merge mechanics and is easier to read once the framing below clicks.

---

## 1. What a merge table actually is

A "merge table" in Spyglass is a small, deliberate **DataJoint pattern**, codified in the private base class `_Merge` (`src/spyglass/utils/dj_merge_tables.py`). Its job is to give you **one stable handle** for "the output of pipeline X" even when there are multiple internal versions or upstream sources of that output.

Concrete shape, using `PositionOutput` (`src/spyglass/position/position_merge.py:24`):

- The **master table** has exactly one primary-key column: `merge_id` (a UUID), plus a non-PK `source` column naming which part the row came from.
- For every upstream pipeline that can produce position data, there is **one part table** living under the master:
  - `PositionOutput.TrodesPosV1` — Trodes / LED-tracker pipeline
  - `PositionOutput.DLCPosV1` — DeepLabCut pipeline
  - `PositionOutput.CommonPos` — the older `common_position` outputs
  - `PositionOutput.ImportedPose` — externally-tracked pose imported into Spyglass
- `LFPOutput` does the same job for LFP (parts: `LFPV1`, `ImportedLFP`, ...). The five Spyglass merge masters are `PositionOutput`, `LFPOutput`, `SpikeSortingOutput`, `LinearizedPositionOutput`, `DecodingOutput`.

So `merge_id` is **a Spyglass-issued UUID that points at exactly one row in exactly one part table**. Downstream tables (`RippleTimesV1`, `MuaEventsV1`, decoding selection tables, ...) declare their FK against `PositionOutput` rather than against `TrodesPosV1` or `DLCPosV1` directly. That's the whole point: a downstream pipeline can consume "position" without caring whether it came from Trodes, DLC, or imported pose, and a new pipeline version can be added later by simply writing another part table — no downstream rewrite.

This is purely a **Spyglass convention**. DataJoint just sees a master table with a `merge_id` PK and a bunch of part tables that FK back to it. The merge semantics are imposed by `_Merge`'s methods, not by DataJoint.

### The `merge_*` helper methods

`merge_id` is opaque (a UUID), so you almost never restrict by it directly — you find one. That's what the helpers are for. They're defined on `_Merge` and inherited by all five masters:

| Method | What it does | Typical use |
| --- | --- | --- |
| `merge_view(restriction)` | Read-only preview of the unified rows across all parts; missing columns show as `NULL`. | Exploration. |
| `merge_restrict(restriction)` | Returns a `dj.U` view across all parts, restricted by your dict / SQL / query. | Use when you don't know which part the entry lives in, or for `.fetch1('KEY')` to resolve a `merge_id`. |
| `merge_get_part(restriction, multi_source=False, ...)` | Returns the specific part-table query (e.g. `PositionOutput.TrodesPosV1`) that matches. Raises `ValueError` if 0 or >1 parts match. | Use when you need part-specific columns or `fetch1_dataframe()`. |
| `merge_get_parent(restriction)` | Same as above but returns the **parent** source table, not the part. | Walking back to e.g. `TrodesPosV1` itself. |
| `merge_fetch(*attrs, restriction=...)` | Fetch attributes across the union of all parts. | Quick aggregate fetches. |
| `merge_populate(source)` | Populate the merge from a named source table. | Pipeline lifecycle. |
| `merge_delete(restriction)` / `merge_delete_parent(restriction, dry_run=True)` | Cascade delete from master + parts (and optionally parents). | Lifecycle. |
| `parts()` / `source_class_dict` | Introspect what parts exist and which parent class each maps to. | Discovery. |

Canonical fetch idiom you'll see throughout Spyglass code:

```python
merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
df       = (PositionOutput & merge_key).fetch1_dataframe()
```

`merge_key` is opaque — pass it to `&`, don't read fields out of it.

One framing note that will save you confusion later: most of these methods are **classmethods** with `restriction=True` as a default argument. So you call them as `PositionOutput.merge_restrict(key)`, *not* `(PositionOutput & key).merge_restrict()`. There's a real footgun in the latter shape, but you don't need to internalize it yet — `01_Concepts.ipynb` and `references/merge_methods.md` both spell it out when you're ready to write delete/restrict code.

---

## 2. What `SpyglassMixin` adds on top of `dj.Computed`

`SpyglassMixin` is what every Spyglass table (computed, manual, merge master, merge part) inherits in addition to its DataJoint tier. Conceptually it's "DataJoint plus Spyglass house rules." The big things it provides that plain DataJoint does not:

- **`fetch_nwb(*attrs, **kwargs)`** — NWB-aware fetch. Tables that store their data in an NWB or AnalysisNWB file get a one-call fetch that returns the actual NWB objects (e.g. an `ElectricalSeries` for LFP), and will transparently download missing files from DANDI / Kachery if needed. Only resolves on tables with an `Nwbfile` / `AnalysisNwbfile` FK; selection / parameter / interval tables raise `NotImplementedError`. There's a sibling `fetch_pynapple` for time-series workflows. (Defined at `src/spyglass/utils/mixins/fetch.py:284`.)

- **Graph-aware up/down restriction (`<<`, `>>`, `restrict_by`)** — `Table << restriction` walks **upstream** through the dependency graph until it finds rows matching the restriction; `Table >> restriction` walks **downstream**. Useful for interactive exploration when you don't want to hand-write the join chain. Slower than explicit joins (≈10x on long chains), so use them at the REPL, not in production loops.

- **`cautious_delete` / `delete` / team-permission gating** — `.delete()` on any SpyglassMixin table is aliased to `cautious_delete`, which checks lab-team membership against the session's experimenter and walks the dep graph to cascade the delete cleanly across merge masters. This is why a `.delete()` on a Spyglass table behaves differently from a plain `dj.Table.delete()`. There's a `super_delete()` escape hatch, but it bypasses both permissions *and* analysis-file cleanup — generally not what you want.

- **Augmented `populate()` with transaction + upstream-hash checks** — `SpyglassMixin.populate` (at `src/spyglass/utils/mixins/populate.py:48`) wraps each `make()` call in a DB transaction by default and verifies upstream hashes haven't changed during the run. It also adds a `processes` kwarg with a non-daemon pool path for tables whose `make()` itself uses multiprocessing (`_parallel_make = True`). Plain `dj.Computed.populate` doesn't do either of these.

- **Export hooks for reproducibility** — Spyglass tracks every fetch / restriction during a paper-export session via a mixin layer (`ExportMixin`). That's how `Export` snapshots can later reproduce exactly which rows fed a paper figure. This is invisible most of the time and only activates when you wrap your work in an export context.

- **Quality-of-life helpers** — `dict_to_pk(key)` (drop non-PK fields), `file_like('j16%')` (wildcard search on file fields), `restrict_by_list(field, [...])`, `find_insert_fail(key)` (locate the parent table causing an `IntegrityError`), `delete_orphans(dry_run=True)`, and `get_table_storage_usage()`. These are the small ergonomic things you'd otherwise hand-roll on a plain `dj.Computed` table.

So when you see `class TrodesPosV1(SpyglassMixin, dj.Computed):`, the mental model is: "this is a regular DataJoint computed table, **plus** NWB-aware fetch, graph-aware traversal, team-gated delete, transaction-wrapped populate, and export tracking." Nothing in `dj.Computed` itself does those — the mixin is where Spyglass standardizes them across every pipeline.

---

## Where to go next

- `notebooks/01_Concepts.ipynb` — the right starting point. It walks merge tables and the SpyglassMixin shape together with running examples.
- For deeper merge-table mechanics (the classmethod-discard footgun, the per-master helpers like `SpikeSortingOutput.get_restricted_merge_ids` and `DecodingOutput.fetch_results`, the projected-FK rename pattern downstream consumers use), come back to `references/merge_methods.md` once you're actually writing code against the masters.
- For the full mixin method surface (everything `fetch_nwb` covers, the `<<` / `>>` semantics, populate kwargs, `cautious_delete` permission rules), `references/spyglassmixin_methods.md`.
- `04_Merge_Tables.ipynb` exists but is a specialist-level notebook — fine later, premature now.
