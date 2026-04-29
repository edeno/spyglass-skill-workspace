# Tracing where a Spyglass table gets its data from

Yes — there's a general way, and it works for **any** Spyglass table, because every Spyglass table is ultimately a DataJoint table (subclass of `dj.Manual`, `dj.Imported`, `dj.Computed`, or `dj.Lookup`, usually via `SpyglassMixin`). The dependency information lives in the schema graph that DataJoint maintains, and you query it with methods that every table inherits.

## The two methods you want: `parents()` and `ancestors()`

DataJoint exposes the upstream graph through two complementary methods on every table class/instance:

### `Table.parents()` — one hop upstream

Returns the tables that `Table` directly foreign-keys to (its *immediate* dependencies, declared with `-> SomeOtherTable` lines in the table's `definition`).

Use this when you want to answer: *"What does this table immediately depend on?"* — i.e., which tables would I need to populate one step earlier to get a row in here.

```python
from spyglass.lfp.v1.lfp import LFPV1
LFPV1.parents()
# => list of immediately-upstream tables (e.g. LFPSelection, AnalysisNwbfile, ...)
```

By default it returns table names; you can also ask for the actual class objects with `parents(as_objects=True)`, and you can filter primary vs secondary FK parents with the `primary=` argument.

### `Table.ancestors()` — full transitive walk

Returns *every* table reachable by repeatedly following FKs upward — parents, grandparents, great-grandparents, all the way back to root tables like `Session`, `Nwbfile`, `IntervalList`, `Electrode`, etc.

Use this when you want to answer: *"Where does this table **ultimately** get its data from?"* — i.e., the full set of upstream tables whose contents (transitively) determine what can land here.

```python
LFPV1.ancestors()
# => transitive closure: every upstream table, including Session, Nwbfile,
#    IntervalList, Electrode, FirFilterParameters, ...
```

Practical rule of thumb:

| Question | Method |
|---|---|
| "What's the next step back in the pipeline?" | `parents()` |
| "What raw / config tables does this depend on, end to end?" | `ancestors()` |
| "What feeds *into* my Selection table?" | `parents()` on the Selection |
| "If I want to reproduce this row from scratch, what do I need populated?" | `ancestors()` |

(There are mirror-image methods `children()` and `descendants()` for the *downstream* direction — what depends on this table — which is the same idea pointed the other way.)

## The schema-level companion: `.describe()`

`parents()` / `ancestors()` give you a *runtime graph walk* — programmatic, iterable, useful in scripts. The complementary view is `Table.describe()`, which prints the table's `definition` string: the schema source as DataJoint sees it, with the **FK declarations (`-> ParentTable`) shown inline** with the column list.

```python
LFPV1.describe()
# -> LFPSelection
# -> AnalysisNwbfile
# ---
# lfp_object_id : varchar(40)
# ...
```

So:

- `describe()` = **static schema view**, in source order, good for *reading* the table's contract (what columns, what FKs, in what order).
- `parents()` / `ancestors()` = **runtime graph walk**, good for *iterating* (e.g. "loop over all upstreams and check whether each is populated").

Use `describe()` when you're orienting yourself to a new table; use `parents()` / `ancestors()` when you're writing code that needs the dependency list as data.

## Putting it together — a generic recipe

For any Spyglass table you encounter:

```python
from spyglass.some.module import SomeTable

SomeTable.describe()       # read the FK arrows + column definitions
SomeTable.parents()        # immediate upstream(s) — one hop
SomeTable.ancestors()      # full upstream lineage — transitive
```

That trio works the same way on `LFPV1`, `LFPBandV1`, `SpikeSortingV1`, `TrodesPosV1`, `RippleTimesV1`, etc., because they all inherit it from DataJoint. Combined with `dj.Diagram(SomeTable)` (which renders the local neighborhood graphically in a notebook), these are the standard tools for tracing where a table's data comes from.
