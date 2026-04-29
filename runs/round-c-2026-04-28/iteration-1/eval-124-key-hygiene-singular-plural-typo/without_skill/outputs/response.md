# Why your `&` restriction "didn't work"

Short version: it almost certainly did nothing — and that's why `fetch1()` then complained. DataJoint's `&` operator silently ignores keys in a restriction dict that don't match any attribute in the table's heading. So if the attribute name in your dict doesn't match a real column, the restriction reduces to an empty dict, which restricts nothing, and the query returns *every* row. `fetch1()` insists on exactly one row, so with N > 1 rows in the table you get:

```
DataJointError: fetch1 expected one tuple, found N
```

## What's likely wrong with your key

You wrote:

```python
(TrodesPosParams & {'trodes_pos_param_name': 'default'}).fetch1()
```

Note the singular `param`. In Spyglass, the primary-key attribute on `TrodesPosParams` is **plural**: `trodes_pos_params_name` — i.e. `params`, not `param`. So `'trodes_pos_param_name'` is not a column in the heading, the dict-style restriction matches nothing, and you fall through to the silent-drop behavior described above.

Don't take my word for it — verify it in your own session before patching code:

```python
from spyglass.position.v1 import TrodesPosParams  # adjust import to wherever you import it from
TrodesPosParams.heading.primary_key
# -> ['trodes_pos_params_name']
TrodesPosParams.heading.attributes.keys()
```

`heading.primary_key` is the authoritative list of PK attribute names; `heading.attributes` shows every column. If you see `trodes_pos_params_name` there, that confirms the typo.

## The fix

Use the actual attribute name:

```python
(TrodesPosParams & {'trodes_pos_params_name': 'default'}).fetch1()
```

Or, equivalently, use a SQL-string restriction (which *will* error loudly on a bad attribute name, unlike dict restrictions):

```python
(TrodesPosParams & "trodes_pos_params_name = 'default'").fetch1()
```

That second form is a useful habit: a typo in a SQL-string restriction raises an "unknown column" error from MySQL immediately, instead of silently matching everything.

## Why this footgun exists

DataJoint's dict-restriction semantics are "AND together the constraints I recognize, ignore the rest." That's convenient when you pass a `key` from a parent table's `make()` that has *extra* attributes not in this table — the extras get dropped, and only the relevant ones constrain the query. The downside is that a misspelled attribute name is indistinguishable from "an extra attribute the caller didn't filter out," so it's silently ignored. The diagnostic signal is exactly what you saw: a `fetch1` that expected 1 and got N where N is the full row count.

Two defensive habits that make this class of bug obvious:

1. Before restricting, glance at `Table.heading.primary_key` (or `Table.describe()`) so you're using the real attribute names, not what you remember them being.
2. When `fetch1()` returns `found N` with N suspiciously equal to `len(Table())`, suspect a silently-dropped restriction key first — typo, wrong table, or wrong dict — before suspecting duplicate rows.

## TL;DR

- The PK attribute is `trodes_pos_params_name` (plural `params`), not `trodes_pos_param_name`.
- DataJoint silently drops unknown keys from dict restrictions, so your `&` was a no-op and `fetch1()` saw all N rows.
- Fix the spelling, and check `TrodesPosParams.heading.primary_key` to confirm the canonical name in your installed Spyglass version.
