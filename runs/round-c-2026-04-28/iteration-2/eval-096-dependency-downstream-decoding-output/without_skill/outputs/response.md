# Enumerating downstream tables of `DecodingOutput`

Spyglass tables are DataJoint relations, so "every table that takes data
from `DecodingOutput`" is the same question as "every table that has a
foreign-key path back to `DecodingOutput`". DataJoint exposes that graph
walk directly.

## Use `descendants()`, not `children()`

```python
from spyglass.decoding.decoding_merge import DecodingOutput

for t in DecodingOutput.descendants():
    print(t)
```

The distinction matters:

- `DecodingOutput.children()` returns only the **one-hop** children —
  tables whose primary key directly references `DecodingOutput`. If your
  custom analysis table FKs to one of those children (or to a
  child-of-a-child), `children()` will miss it.
- `DecodingOutput.descendants()` walks the **full transitive closure**
  of the dependency graph downstream of `DecodingOutput`. Every direct
  child, plus every grandchild, plus every great-grandchild, in one call.
  That is what you want when you say "every table that takes data from
  `DecodingOutput`".

(Symmetrically, `parents()` and `ancestors()` walk *upstream*. You want
the *downstream* side here, so `descendants()`.)

The return value is a list of fully-qualified table names (strings like
`` `decoding_merge`.`__decoding_output__some_child` ``). If you want
them as DataJoint table objects you can resolve them via
`dj.FreeTable(connection, name)` or by looking them up in the schema's
`schema.list_tables()`.

## Subtlety: `DecodingOutput` is a merge master

`DecodingOutput` is a Spyglass **merge table**. Concretely, that means:

- `DecodingOutput` itself is the *master* — it holds the unifying
  primary key (a `merge_id` UUID) that downstream tables reference.
- The per-source implementations (`ClusterlessDecodingV1`,
  `SortedSpikesDecodingV1`, …) live as *part tables* under the master.

Downstream consumers — including any custom analysis table you write
that takes "the output of decoding" — should and do FK to the **merge
master** (`DecodingOutput`), not to the part tables. That is the whole
point of the merge pattern: the consumer is agnostic about which decoder
produced the row.

So:

- `DecodingOutput.descendants()` is the right call. It enumerates
  everything that FKs to the merge master, which is where downstream
  analyses actually attach.
- Calling `.descendants()` on a part table — e.g.
  `DecodingOutput.ClusterlessDecodingV1.descendants()` — would only find
  things FK'd to *that specific part*, which in well-formed Spyglass
  code is essentially nothing user-facing. You'd miss the actual
  downstream pipeline.

## Filtering to your own tables

`descendants()` will return Spyglass-internal tables too (the part
tables themselves, plus any housekeeping). To narrow to your custom
schema, filter on the table name prefix:

```python
MY_SCHEMA = "my_lab_analysis"  # your schema name
for t in DecodingOutput.descendants():
    if t.startswith(f"`{MY_SCHEMA}`."):
        print(t)
```

Or, if you want both the name and a live table object:

```python
import datajoint as dj
from spyglass.decoding.decoding_merge import DecodingOutput

conn = DecodingOutput.connection
for name in DecodingOutput.descendants():
    ft = dj.FreeTable(conn, name)
    print(name, "rows:", len(ft))
```

## Quick visual sanity check

If you want to *see* the dependency tree before iterating, DataJoint
also has:

```python
dj.Diagram(DecodingOutput) + 2   # show 2 levels downstream
```

That's useful to confirm where your custom table actually attaches
before you trust the `descendants()` enumeration.

## Summary

- `DecodingOutput.descendants()` — full transitive downstream closure;
  use this.
- `DecodingOutput.children()` — one hop only; will under-report.
- `DecodingOutput` is a merge master, so FKs from downstream
  (including custom) tables land on the master, which is exactly what
  `descendants()` traverses. Don't call `descendants()` on the part
  tables — you'll miss the real consumers.
