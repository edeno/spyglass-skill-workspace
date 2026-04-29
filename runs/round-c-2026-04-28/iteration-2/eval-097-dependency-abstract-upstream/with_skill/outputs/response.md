# Where does a Spyglass table get its data from?

Yes — there's a **fully general way**, and it works on any Spyglass (or plain DataJoint) table because both inherit the graph methods from `dj.Table`. You don't need pipeline-specific knowledge: the foreign-key graph is exposed directly on every table class.

The two methods you want are `parents()` and `ancestors()`, with `describe()` as the schema-level companion.

## `Table.parents()` vs `Table.ancestors()`

These look similar but answer **different questions** — pick based on whether you want one hop or the whole chain:

| Method | Returns | Use it when… |
|---|---|---|
| `Table.parents()` | The tables `Table` directly foreign-keys to (one hop up). | You want to know "what does this immediately depend on?" — usually to figure out the next selection/parameter table to insert into, or to debug a missing upstream key. |
| `Table.ancestors()` | Every table reachable by walking foreign keys upward, transitively (parents of parents of …). | You want to know "where does this table **ultimately** get its data from?" — i.e., the full provenance back to `Session`, `Nwbfile`, `IntervalList`, raw electrode/parameter tables, etc. |

Both return table **names** by default; pass `as_objects=True` if you want `FreeTable` objects you can introspect. Note: those objects are not a restrictable relation — `Table.ancestors() & {…}` silently does the wrong thing. If you want to iterate, loop and restrict each table individually.

There's a symmetric pair for the downstream direction: `children()` (one hop down) and `descendants()` (full transitive walk).

### Example: `LFPBandV1`

```python
from spyglass.lfp.analysis.v1.lfp_band import LFPBandV1

LFPBandV1.parents()
# One hop up — the tables LFPBandV1 directly FKs to:
#   LFPBandSelection, AnalysisNwbfile, IntervalList

LFPBandV1.ancestors()
# Transitive walk — keeps following FKs upward until it hits root tables.
# You'll see LFPBandSelection's parents (LFPV1, FirFilterParameters, Electrode, ...)
# and their parents, all the way back to Session, Nwbfile, IntervalList,
# LabMember, etc.
```

The `LFPBandV1` definition itself is

```
-> LFPBandSelection
---
-> AnalysisNwbfile
-> IntervalList
lfp_band_object_id: varchar(40)
```

so `parents()` mirrors exactly those three `->` arrows, and `ancestors()` chases each of them recursively.

## `Table.describe()` — the schema-level companion

`describe()` prints the table's `definition` string, which shows the **FK declarations inline** with the column list (the `-> ParentTable` arrows you see above). It's a static, schema-level view — it doesn't walk the graph or hit the database; it just renders the source-of-truth definition.

```python
LFPBandV1.describe()
# Prints the definition: PK declaration, ----, then FK arrows + secondary attrs.
```

When to use which:

- **`describe()`** — you want to *read* the FK arrows in source order, alongside the column declarations and comments. Best for "what is this table, exactly?"
- **`parents()` / `ancestors()`** — you want a *programmatic* enumeration of upstream tables to iterate over, restrict against, or feed into another tool. Best for "give me a list of dependencies I can loop over."

`describe()` is the static schema view; `parents()` / `ancestors()` are the runtime graph walk. They agree (modulo `ancestors()` going transitive), but they're shaped for different jobs.

## Generality

These are inherited from `dj.Table` itself, so they apply to **any** DataJoint table — Spyglass merge masters, merge parts, selection tables, computed tables, manual tables, parameter tables, your own custom tables, even tables in other labs' schemas on the same server. There is no pipeline-specific machinery here; it's the underlying DataJoint dependency graph.

A few practical notes:

- `parents()` / `ancestors()` need the relevant table classes to be **imported** in your session (they walk the digraph DataJoint builds from currently-known schemas). If you get a `NetworkXError: ... not in the digraph`, import the missing schema module and retry.
- For long chains, the transitive walk can be large — pipe through `len(...)` or filter by schema if you just want a sense of scale.
- If you want a richer / pretty-printed view (with FK kinds, schema boundaries, etc.), the skill ships `code_graph.py describe <Table>` for source facts and `db_graph.py describe <Table>` for runtime DB facts. Either runs `python skills/spyglass/scripts/<name>.py …` and is the LLM-friendly equivalent of the Python calls above.

## TL;DR

```python
Table.parents()    # one hop up:  immediate upstream FKs
Table.ancestors()  # all hops up: every upstream prerequisite, transitively
Table.describe()   # the definition string with FK arrows inline
```

Use `parents()` to debug the next missing key, `ancestors()` to chase full provenance, and `describe()` to read the schema as written in source.
