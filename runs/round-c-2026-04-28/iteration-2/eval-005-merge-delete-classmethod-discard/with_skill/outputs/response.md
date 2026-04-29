# STOP — do not confirm that 200-row prompt

That confirmation will delete every row in `PositionOutput` (master + every part). Hit **no** / abort the prompt right now. Your one bad position entry is fine; the cascade you're being asked to confirm is **not** what you asked for.

## What just happened

You hit the **classmethod-restriction-discard** footgun on merge tables (Common Mistake #1 in this skill). The mechanism:

- `PositionOutput.merge_delete` is a `@classmethod` with `restriction=True` as the default — see `src/spyglass/utils/dj_merge_tables.py:443-444`:

  ```python
  @classmethod
  def merge_delete(cls, restriction: str = True, **kwargs):
  ```

- When you write `(PositionOutput & merge_key).merge_delete()`, Python routes the classmethod call to **the class**, not the restricted instance. The `& merge_key` is silently discarded.
- `merge_delete` then runs with its default `restriction=True`, which means "every row." That's why the prompt is offering you ~200 rows — that's roughly the size of the whole `PositionOutput` table on your DB.

The same dispatch trap applies to `merge_delete_parent`, `merge_restrict`, `merge_get_part`, `merge_get_parent`, `merge_view`, and `merge_html`. Always pass the restriction as an argument to these.

## The corrected form

Pass the restriction as a positional argument — do not pre-restrict the class:

```python
# WRONG — silently drops the & merge_key, deletes the whole table:
# (PositionOutput & merge_key).merge_delete()

# RIGHT — restriction is the first positional arg:
PositionOutput.merge_delete(merge_key)
```

## Inspect-before-destroy (paired pattern from destructive_operations.md)

The skill's hard rule is: never run a destructive helper without the matching inspect step first. For your case, that looks like:

```python
# 1. Resolve the bad row to its merge_id (you already did this).
merge_key = PositionOutput.merge_get_part(
    {"nwb_file_name": "j1620210710_.nwb", "interval_list_name": "02_r1"}
).fetch1("KEY")

# 2. INSPECT — confirm exactly what will be deleted. Should print
#    a single row with the merge_id you intend to remove.
target = PositionOutput & merge_key
print(len(target))                  # expect: 1
print(target.fetch(as_dict=True))   # eyeball the row

# 3. Also preview the part-row that will be cascaded.
#    (PositionOutput & merge_key).parts() is NOT restriction-aware,
#    so use merge_get_part for the actual restricted preview.
part = PositionOutput.merge_get_part(merge_key)
print(len(part), "part row(s) will be deleted")
print(part.fetch(as_dict=True))

# 4. Pause for explicit user confirmation.

# 5. Destroy — restriction passed as argument, NOT via `&`:
PositionOutput.merge_delete(merge_key)
```

If step 2 prints `1` and the row matches the bad session/interval you intended, you're safe to run step 5. If it prints anything else, stop and re-restrict — you have the wrong key.

## Why the bad shape is so easy to hit

It looks identical to every other DataJoint pattern (`(Table & key).delete()` is correct on normal `dj.Computed`/`dj.Manual` tables), and it doesn't error — it just silently changes what gets deleted. The only signal is the unexpectedly-large confirmation prompt, which you correctly noticed. Good catch on stopping to ask.

References in the skill:
- Common Mistake #1: `references/common_mistakes.md` § "Classmethod restriction discard on merge tables"
- Full classmethod-discard table (all 7 affected methods + safety checklist): `references/merge_methods.md` § "Classmethod Restriction Discard (Read First)"
- Paired inspect/destroy shapes: `references/destructive_operations.md` § "Merge-table delete helpers"
