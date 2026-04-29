# Which reference do I consult first?

For deleting a single entry from `PositionOutput` via a `merge_key`, you have two references in play, and the order matters:

1. **First: `references/destructive_operations.md`**
   Any `.delete()` against a Spyglass table is a destructive cascade. The destructive-operations reference is the resource-first stop because it covers the safety workflow that has to wrap *any* delete:
   - restrict before deleting (never call `.delete()` on an unrestricted table),
   - preview the cascade with `.delete(safemode=True)` / inspect downstream descendants,
   - confirm row count is what you expect (exactly 1 here),
   - understand transaction semantics and what gets cascaded into part tables and downstream merges.
   This applies whether the target is a merge table or a regular table, so it sets the guardrails before you touch the merge-specific API.

2. **Second: `references/merge_methods.md`**
   Merge tables have their own delete idioms because the row you want to remove lives in a *part table* (e.g. `PositionOutput.TrodesPosV1`), not in the `PositionOutput` master directly. The merge-methods reference is where you find:
   - how `merge_key` (the `merge_id` UUID) maps to the correct part table,
   - `PositionOutput.merge_get_part(restriction)` to resolve the part-table row from a merge_key,
   - the recommended pattern of restricting the part table by the `merge_id` and calling `.delete()` there (deleting from the master alone can leave orphaned part rows or fail the FK cascade in the wrong order),
   - any helper like `delete_downstream_parts` / `delete_downstream_merge` that Spyglass exposes for merge cleanup.

## Concrete order of operations

```text
destructive_operations.md   -> safety workflow, safemode preview, cascade awareness
merge_methods.md            -> merge_get_part + part-table restrict-then-delete pattern
```

So: open `destructive_operations.md` first to lock in the safety workflow, then `merge_methods.md` for the merge-key-specific delete mechanics. If `PositionOutput` itself is feeding a downstream pipeline (e.g. linearization, decoding) you may also need a quick look at `dependencies.md` to confirm what the cascade will sweep, but those are the two primary references.
