# Finding the primary key of `MyLabRipplePostprocess`

Since `MyLabRipplePostprocess` lives in your lab's internal package (not in the
Spyglass repo), you need to introspect it where it is *actually defined* or
where it is *actually instantiated as a DataJoint table* — you can't infer its
PK from the fact that it "wraps `RippleTimesV1`".

Below are three reliable ways to get the answer, in roughly the order I'd try
them.

## 1. Runtime introspection (most reliable)

DataJoint tables expose their schema as `.heading`, and the heading exposes the
primary key directly. In a Python session that can import your lab package and
connect to the DB:

```python
from my_lab_package.ripple import MyLabRipplePostprocess  # adjust import path

# As an attribute on the class (works once the class has been declared
# against a schema, which happens at import time for a DataJoint table):
print(MyLabRipplePostprocess.heading.primary_key)
# -> ['nwb_file_name', 'interval_list_name', ...]   # whatever it actually is

# Full heading (PK + secondary attributes, with types and comments):
print(MyLabRipplePostprocess.heading)

# Or, if you prefer the DataJoint definition string:
print(MyLabRipplePostprocess.describe())
```

Useful relatives of `heading.primary_key`:

- `MyLabRipplePostprocess.primary_key` — same list, shorthand on the table.
- `MyLabRipplePostprocess.heading.attributes` — dict of every attribute (PK and
  non-PK) with `.in_key` flags and dtypes.
- `MyLabRipplePostprocess.heading.secondary_attributes` — non-PK columns.
- `dj.Diagram(MyLabRipplePostprocess)` — visualize it and its parents (handy
  for confirming what it inherits from `RippleTimesV1`).

This is the method I'd recommend by default, because it tells you what the
table *actually* looks like in the database right now, including any custom
attributes the lab added on top of `RippleTimesV1`'s key.

## 2. Read the source definition in your lab package

If you can't (or don't want to) connect to the DB, find the class in the
internal package and read its `definition` string. A DataJoint table's PK is
everything above the `---` separator. For example:

```python
@schema
class MyLabRipplePostprocess(SpyglassMixin, dj.Computed):
    definition = """
    -> RippleTimesV1                       # <- foreign key into RippleTimesV1
    postprocess_param_name : varchar(64)   # <- extra PK attribute (example)
    ---
    postprocessed_intervals : blob
    """
```

In this hypothetical example, the PK would be the PK of `RippleTimesV1`
**plus** `postprocess_param_name`. The exact set depends on what your lab
wrote — that's why you need to look at the actual file. To find it:

```bash
# from the root of your lab's internal package
grep -rn "class MyLabRipplePostprocess" .
# or, if it's installed:
python -c "import my_lab_package.ripple as m; print(m.__file__)"
```

Once you have the file, the lines between `definition = """` and `---` are the
primary key.

Important: do **not** assume the PK is identical to `RippleTimesV1`'s PK. A
wrapper table commonly:

- adds its own parameter attribute (e.g. `postprocess_param_name`) to the key,
- projects only some of the parent's PK forward, or
- has a `dj.Part` table whose key is different again.

You have to read the actual `definition`.

## 3. Query the database directly (last resort)

If the class isn't importable but the table exists in the DB and you know the
schema/table name, you can ask MySQL/DataJoint:

```python
import datajoint as dj
schema = dj.Schema('my_lab_ripple')   # whatever the schema name is
# List tables in that schema:
print(schema.list_tables())

# Reflect the table without the Python class:
tbl = dj.FreeTable(dj.conn(), '`my_lab_ripple`.`_my_lab_ripple_postprocess`')
print(tbl.heading.primary_key)
```

(The backticked name follows DataJoint's naming rules: `dj.Computed` → leading
underscore, `dj.Imported` → leading underscore, etc.) `SHOW CREATE TABLE` from
a MySQL client will also show the PK columns.

## What I would *not* do

- Don't guess the PK from the class name `MyLabRipplePostprocess`.
- Don't assume it's identical to `RippleTimesV1.primary_key` just because it
  "wraps" it — that's the most common source of bugs when restricting or
  joining custom wrapper tables.
- Don't search the upstream Spyglass repo for it; by your own description the
  table isn't there, so any source-graph / repo-grep tool scoped to Spyglass
  will come up empty. The fact is in your lab package and in the live DB, not
  in `spyglass/`.

## TL;DR

In a Python session with your lab package importable and a DB connection:

```python
from my_lab_package.ripple import MyLabRipplePostprocess
MyLabRipplePostprocess.heading.primary_key
```

If you can't import or connect, open the class in your lab's internal package
and read everything above the `---` in its `definition` string.
