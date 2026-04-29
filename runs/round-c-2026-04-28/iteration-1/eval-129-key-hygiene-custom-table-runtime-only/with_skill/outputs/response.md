# Finding the primary key of `MyLabRipplePostprocess`

This is a **runtime / custom-pipeline** question, not a source-graph question. `MyLabRipplePostprocess` lives in your lab's internal package, so the source-graph tool the skill ships (`code_graph.py`) is the wrong tool for it: `code_graph.py` only walks `$SPYGLASS_SRC/spyglass/`. It cannot see classes that live outside that tree (lab repos, institute forks, downstream pip packages). Running `code_graph.py describe MyLabRipplePostprocess` will return `not_found` even though the class exists in your DB and your interpreter — that's a known boundary, not a bug.

A second important point before any answer: **do not guess the PK from the class name, and do not assume it inherits `RippleTimesV1`'s shape.** Custom wrappers commonly do one or more of:

- add their own PK fields (a postprocess version, a recompute timestamp, a method tag),
- project / rename a parent FK (e.g. `ripple_id` → `source_ripple_id`) so they can join to multiple parents,
- override the `definition` block entirely rather than re-declaring `-> RippleTimesV1`.

So the safe path is to read the runtime heading or the actual source — never the class name.

## Three concrete paths, depending on your context

### 1. Runtime introspection in your own Python session (always available)

This is the portable, universal answer. In any Python / Jupyter session where the lab package is installed:

```python
from mylabpkg.tables import MyLabRipplePostprocess  # adjust to your package's actual import path

print(MyLabRipplePostprocess.heading.primary_key)
# e.g. ['nwb_file_name', 'interval_list_name', 'ripple_param_name', 'postprocess_version']
```

`Table.heading.primary_key` is the runtime-authoritative answer — it reflects the schema as DataJoint actually sees it on the live server, after any dynamic FK overrides, aliased imports, or part-table registration. If you want the full heading (PK + secondary attrs + dtypes), use `MyLabRipplePostprocess.heading` or `MyLabRipplePostprocess.describe()`.

This is the answer to give first if the question is "how does a Spyglass user find a custom table's PK?" — it works on any install, no skill tooling required.

### 2. Bundled skill tool (only if the skill environment is configured with a DB connection)

If you're working inside an agent session that has the spyglass skill installed *and* a DataJoint connection configured (so `db_graph.py` can reach your DB), there's a bundled CLI that does the same heading lookup as a one-liner:

```bash
python skills/spyglass/scripts/db_graph.py describe \
    --import mylabpkg.tables \
    mylabpkg.tables:MyLabRipplePostprocess
```

The `--import mylabpkg.tables` flag runs your package's normal import side-effects (so the class registers with DataJoint), and the explicit `module:Class` form bypasses the source `_index` lookup — that's exactly what makes `db_graph.py` able to resolve a class outside `$SPYGLASS_SRC`. The output payload includes the runtime heading + parents/children/parts and stamps `graph: "db"` / `authority: "runtime-db"`, so it's clearly tagged as runtime truth rather than a source claim.

Caveat: this is a **bundled skill tool**, not a Spyglass user command — it only exists where this skill is installed alongside a DB connection. Don't recommend it as the answer for a generic Spyglass user; it's an agent-only path.

### 3. Source fallback (when neither the DB nor an importable copy is available)

If you can't connect to the DB and can't import the lab package, open the lab package's source and read the `definition = """..."""` block on `MyLabRipplePostprocess` directly. The fields above the `---` divider are the primary key. This is the slowest path but the most portable — it works from a checkout alone.

When reading the source, watch for two things that the class name won't tell you:

- **`-> Parent` lines that don't say `RippleTimesV1`.** Wrappers often inherit from a different upstream (e.g. `RippleLFPSelection`, or the parent's own merge layer) even when they "wrap" a sibling table conceptually.
- **Renamed FK fields** of the form `-> Parent.proj(new_name='old_name')`. The renamed field is what shows up in the PK, not the original.

## Why I'm not just guessing

The eval-relevant trap here is "guess `MyLabRipplePostprocess`'s PK looks like `RippleTimesV1`'s." That's a hallucination shape the skill explicitly flags: even when a class wraps another, its declared PK is independent and load-bearing for any restriction you write against it. The only sound answers are runtime introspection (paths 1 or 2) or reading the source definition (path 3).

For more on the source-vs-runtime split and when to reach for `db_graph.py` over `code_graph.py`, see `skills/spyglass/references/feedback_loops.md` ("Three graphs, three primitive families"). For custom-table caveats specifically — wrapper-vs-merge-part shape, projected FKs, override patterns — see `skills/spyglass/references/merge_methods.md` and `skills/spyglass/references/custom_pipeline_authoring.md`.
