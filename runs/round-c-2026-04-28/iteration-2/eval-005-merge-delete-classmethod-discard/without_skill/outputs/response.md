# Stop — do NOT confirm that 200-row deletion

That prompt is asking you to delete ~200 rows because, despite how it
looks, your restriction is not actually being applied to the delete.
**Type `n` / abort the prompt right now** before doing anything else.
A 200-row cascade out of `PositionOutput` is almost certainly going to
take down a large chunk of downstream work that you didn't intend to
touch.

## What's actually happening

`PositionOutput.merge_delete` is a **classmethod** on the merge-table
mixin, and its first parameter is `restriction` with a default of
`True` (i.e. "everything"). When you wrote

```python
(PositionOutput & merge_key).merge_delete()
```

a few things conspire against you:

1. `PositionOutput & merge_key` produces a *restricted query
   expression* — but it's still bound to the same class.
2. `.merge_delete()` is a classmethod, so Python dispatches it on the
   **class**, not on the restricted expression. The `& merge_key` part
   is silently discarded.
3. Inside the method, `restriction` falls back to its default `True`,
   which means "match every row in the merge table." That's where the
   ~200 comes from — that's the size of the whole `PositionOutput`
   merge table, not your one bad entry.

So the call you made is equivalent to `PositionOutput.merge_delete()`
with no filter at all. The chained `&` is a no-op here. This is the
**classmethod-restriction-discard** footgun: any time you write
`(SomeMergeTable & key).merge_*()` for a classmethod on the merge
mixin, the restriction in front of the dot vanishes.

## The fix: pass the restriction as an argument

```python
# 1. Resolve the merge_id you actually want to drop.
merge_key = (
    PositionOutput.merge_get_part(
        {"nwb_file_name": "j1620210710_.nwb", "interval_list_name": "02_r1"}
    ).fetch1("KEY")
)

# 2. INSPECT before you destroy — confirm it's exactly one row,
#    and confirm it's the row you think it is.
print(PositionOutput.merge_restrict(merge_key))
print(len(PositionOutput.merge_restrict(merge_key)))   # expect 1

# 3. Delete by passing the restriction *into* the classmethod.
PositionOutput.merge_delete(merge_key)
```

Key change: `PositionOutput.merge_delete(merge_key)` — restriction
goes in as the **argument**, not via `&` on the left of the dot. Now
the classmethod sees your filter and only deletes that one merge_id
(plus its part-table row).

## Inspect-before-destroy, in general

Whenever you're about to call any `merge_delete*` / `delete` /
`delete_quick`, run the matching read-only restrict first and
eyeball the count and the rows. If the count surprises you, stop
and re-derive the restriction; don't confirm the prompt to "see what
happens." DataJoint deletes cascade through dependents, and on a
merge table that cascade can be wide.

A safe pattern:

```python
restr = PositionOutput.merge_restrict(merge_key)
print(restr)               # show me the rows
assert len(restr) == 1     # fail loudly if more than one matched
PositionOutput.merge_delete(merge_key)
```

If you've already accidentally hit `y` on the 200-row prompt, stop
populating, note exactly what was deleted (DataJoint logs the table
counts), and you'll likely need to repopulate the affected
downstream pipelines from upstream sources.

## TL;DR

- The prompt is asking to delete 200 rows because your restriction
  was dropped — `merge_delete` is a classmethod, so `(T & key).merge_delete()`
  becomes `T.merge_delete()` with the default `restriction=True`.
- Do NOT confirm the prompt.
- Use `PositionOutput.merge_delete(merge_key)` instead — restriction
  as argument.
- Always `merge_restrict` and check the row count before any
  `merge_delete`. Pattern name: **classmethod-restriction-discard**.
