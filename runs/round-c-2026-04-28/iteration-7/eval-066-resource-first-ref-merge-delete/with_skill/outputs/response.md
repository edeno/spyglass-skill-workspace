# Which reference to consult first

**Consult [`destructive_operations.md`](../../../../spyglass/references/destructive_operations.md) first.**

## Why that reference, in that order

This task is a *destructive* operation on a *merge master*. Two routing rows in SKILL.md apply, but they are not equal — `destructive_operations.md` owns the **workflow** ("inspect before destroy"), and `merge_methods.md` owns the **call form**. The workflow has to wrap the call, so it comes first.

Concretely, before you ever type `merge_delete`, the skill requires:

1. **Phase 1 — Inspect.** Build the restriction, run `print(len(rel))`, and preview rows. For a merge master specifically, `(PositionOutput & merge_key).parts()` is **not** restriction-aware (it returns every declared part regardless of restriction). Use `PositionOutput().merge_restrict(merge_key)` or `PositionOutput().merge_get_part(merge_key)` to preview the actual affected rows.
2. **Phase 2 — Report** target table, restriction, count, sample rows, and what cascades.
3. **Phase 3 — Wait for explicit confirmation.** Don't proceed on silence or "ok".
4. **Phase 4 — Execute.**
5. **Phase 5 — Verify** the partial delete left the rest intact.

That phased shape is the whole reason `destructive_operations.md` exists, and it applies to `merge_delete` per its "Merge-table delete helpers" subsection.

## Why `merge_methods.md` is the second read, not the first

The classmethod-discard footgun is the load-bearing call-form detail for this task: **`(PositionOutput & merge_key).merge_delete()` silently drops the restriction** because `merge_delete` is a classmethod with `restriction=True` as the default — Python routes the call to the class, not the restricted instance, so it deletes **every** merge entry. The correct form is:

```python
# Inspect (do this first, then confirm with the user)
merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
print((PositionOutput & merge_key).fetch(as_dict=True))

# After explicit confirmation:
PositionOutput.merge_delete(merge_key)   # classmethod form, restriction passed as arg
```

This is also Common Mistake #1 in SKILL.md, so the skill flags it before you reach either reference. `destructive_operations.md` has a short version of the corrected shape inline (its "Merge-table delete helpers" subsection); `merge_methods.md` is where you go if you also need the full list of other classmethods that share the same dispatch hazard (`merge_delete_parent`, `merge_restrict`, `merge_get_part`, `merge_get_parent`, `merge_view`, `merge_html`).

## One additional caveat for `PositionOutput` specifically

`merge_delete` dispatches through each part table's `.delete()` → `cautious_delete`, so the **team-permission check applies**. If the session(s) backing this `merge_id` were ingested by another lab member, you'll get a `PermissionError` naming the experimenter. The default response is to coordinate with that person, not reach for `super_delete()` or `merge_delete_parent()` (the latter bypasses the team check and is treated as a `super_delete`-class operation).

## Summary

- **First:** `destructive_operations.md` — for the inspect → report → confirm → execute → verify workflow that wraps the call.
- **Second (only if needed):** `merge_methods.md` — for the classmethod call-form rules across all merge helpers.
- **Already covered in SKILL.md itself:** Common Mistake #1 (the classmethod-discard shape) and Core Directive #1 (never destroy without inspect + confirmation).
