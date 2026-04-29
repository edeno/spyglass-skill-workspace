# Enumerating downstream consumers of `DecodingOutput`

Use **`DecodingOutput.descendants()`** — that's the right tool. It walks the full transitive closure of the dependency graph, so you get every direct child *plus* every child-of-a-child, etc., in a single call.

```python
from spyglass.decoding.decoding_merge import DecodingOutput

# Names (default): list[str] of fully qualified table names
for t in DecodingOutput.descendants():
    print(t)

# Or as FreeTable objects you can introspect:
for ft in DecodingOutput.descendants(as_objects=True):
    print(ft.full_table_name, ft.heading.names)
```

## Why `descendants()` and not `children()`

These are different things and the distinction matters here:

- `DecodingOutput.children()` — only the **one-hop** children. The tables whose schema definition contains a direct FK to `DecodingOutput`. For a merge master, that's essentially the part tables (and anything else FK'd directly to the master).
- `DecodingOutput.descendants()` — the **transitive** walk. Every child, plus every child of those children, recursively, until the graph terminates.

If a custom analysis table in your DB FKs to `DecodingOutput` directly, `children()` would catch it. But if it FKs to one of `DecodingOutput`'s children, or a child-of-a-child (e.g. you built a `MyReplayMetric` table that takes a `DecodingOutput` row plus extra params, then a downstream `MyReplaySummary` that joins multiple `MyReplayMetric` rows) — only `descendants()` will find both. For "every table that takes data from `DecodingOutput`," the transitive walk is what you want.

## The merge-master subtlety

`DecodingOutput` is a **merge master** (defined in `src/spyglass/decoding/decoding_merge.py:19` with `merge_id: uuid` as its only PK). It has two part tables shipped by Spyglass:

- `DecodingOutput.ClusterlessDecodingV1`
- `DecodingOutput.SortedSpikesDecodingV1`

By Spyglass convention, downstream consumers FK to **the merge master itself** (`DecodingOutput`), not to the part tables. That's the whole point of the merge layer — a single stable FK target regardless of which decoding source produced the row. So `DecodingOutput.descendants()` is the right call here.

If you instead called `DecodingOutput.ClusterlessDecodingV1.descendants()`, you'd only enumerate things FK'd to *that specific part* (rare, and not the standard pattern), and you'd miss everything FK'd to the merge master itself. Don't go through the parts for this question.

(`DecodingOutput.parents()` / `.ancestors()` walk *upstream* — toward `PositionGroup`, `UnitWaveformFeaturesGroup`, `DecodingParameters`, etc. — which is the opposite of what you want.)

## Filtering to your own custom tables

`descendants()` returns Spyglass-shipped tables too. To narrow to tables defined in your own schema(s), filter on the `full_table_name`, which has the form `` `schema_name`.`table_name` ``:

```python
my_schemas = ("my_lab_decoding", "my_replay_analysis")  # your schema prefixes

for ft in DecodingOutput.descendants(as_objects=True):
    schema = ft.full_table_name.split(".", 1)[0].strip("`")
    if schema in my_schemas:
        print(ft.full_table_name, "—", len(ft), "rows")
```

If you're not sure what schemas are yours, `dj.list_schemas()` shows everything on the connection; the Spyglass-shipped ones are prefixed with names like `common_*`, `decoding_*`, `lfp_*`, `position_*`, `spikesorting_*`, `ripple_*`, `mua_*`, `linearization_*`, plus the `_merge` schemas.

## A runtime caveat worth knowing

`descendants()` is computed from the live DB graph, so it sees every table that's actually been declared against the connected database — including custom tables Spyglass doesn't ship. But it only returns names / `FreeTable` objects, **not a restrictable relation**. Don't write `DecodingOutput.descendants() & key` — that won't do what it looks like. Loop over `as_objects=True` and restrict each `FreeTable` individually if you need to count rows or fetch keys.

If you want the source-graph view instead (what's declared in the Spyglass codebase, ignoring custom tables in your DB), use the bundled `code_graph.py path` script. For "what's actually in my DB right now," `DecodingOutput.descendants()` (or `db_graph.py`) is what you want — and that matches your question.

## References

- [spyglassmixin_methods.md § Table Inspection](../../../skills/spyglass/references/spyglassmixin_methods.md#table-inspection) — `parents()` / `children()` and pointer to DataJoint's `descendants()` / `ancestors()`.
- [datajoint_api.md § Table Inspection Commands](../../../skills/spyglass/references/datajoint_api.md#table-inspection-commands) — full topology block including the `as_objects=True` / not-restrictable caveat.
- [merge_methods.md](../../../skills/spyglass/references/merge_methods.md) — merge-master conventions; consumers FK to the master, not the parts.
- Source: `src/spyglass/decoding/decoding_merge.py:19` (`DecodingOutput` definition).
