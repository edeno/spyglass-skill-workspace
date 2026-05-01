# Deleting decoding results — clarify what you mean first

There isn't a single "right command" because **"decoding results"** for a session can mean two different things in Spyglass, and they need different commands. Before I give you code to run, please confirm which of these you actually want — they have very different consequences. After that, the skill mandates an **inspect-before-destroy** workflow: I will *not* hand you a one-liner that destroys data without a preview step you confirm first.

## Which kind of delete?

### Option A — Delete the DataJoint *rows* for this session's decoding runs

This removes the `DecodingOutput` merge entries (and the `ClusterlessDecodingV1` / `SortedSpikesDecodingV1` part-table rows feeding them) that were populated for `j1620210710_.nwb`. After this, the session has no decoding records in the DB; the `.nc` / `.pkl` files on disk become orphans (still on disk until you separately run `cleanup`).

This is what you want if you plan to re-run decoding with different parameters, or if the existing runs are wrong and you want them gone from the DB.

### Option B — Just sweep orphaned decoding files on disk

If your DB rows are already gone (or you just want to reclaim disk from runs whose DB rows have been deleted), you want `DecodingOutput().cleanup(...)`, which removes orphaned `.nc` (xarray posteriors) and `.pkl` (pickled classifiers) under `{SPYGLASS_ANALYSIS_DIR}/j1620210710/`. This is **session-agnostic** — it sweeps every orphan, not just this session's. There is no per-session variant.

### Option C — Delete one specific decoding entry

If you only want to delete one specific decoding entry (one `merge_id`) rather than every decoding entry for the session, the inspect step builds the merge key from your full `selection_key`, then we delete that single entry. Tell me which entry.

---

Most users asking this question want **Option A**. I'll lay out the safe workflow for it; if you actually wanted B or C, say so and I'll adjust.

## Option A — safe workflow (inspect → confirm → delete)

`DecodingOutput` is one of Spyglass's five merge masters (PK is `merge_id` only). Two consequences for your case:

1. `DecodingOutput & {"nwb_file_name": "j1620210710_.nwb"}` is a **silent footgun** — the master's heading has no `nwb_file_name` field, so DataJoint drops the unknown attribute and the restriction matches **the entire merge master**. Use `merge_restrict({...})` instead.
2. `(DecodingOutput & key).merge_delete()` would silently drop the restriction (classmethod-discard). Always pass the restriction as an argument: `DecodingOutput.merge_delete(key)`.

### Phase 1 — Inspect (run this first; do **not** delete yet)

```python
from spyglass.decoding import DecodingOutput

key = {"nwb_file_name": "j1620210710_.nwb"}

# Use merge_restrict (NOT `& key`) — the master only knows merge_id.
affected = DecodingOutput().merge_restrict(key)
print(len(affected), "decoding entries will be removed")
print(affected.fetch(as_dict=True))   # preview
```

Send me back:

- The row count.
- The output of `affected.fetch(as_dict=True)` (or a slice of it).

If the count is `0`, the restriction didn't match — stop and re-check the filename (note the trailing `_` before `.nwb`; you wrote `j1620210710_.nwb`, which is the canonical Spyglass form).

If the count is unexpectedly large (e.g. dozens of entries), I want to confirm with you before proceeding — you may have intended Option C (one specific entry) instead.

### Phase 2 — What will cascade

A `DecodingOutput.merge_delete(key)` will:

- Route through the merge part tables (`DecodingOutput.ClusterlessDecodingV1`, `DecodingOutput.SortedSpikesDecodingV1`), which hits `cautious_delete` — i.e. the team-permission check fires. If `j1620210710_.nwb` was ingested by another lab member, you'll get a `PermissionError` and the right answer is to coordinate with that experimenter, not bypass.
- Cascade to remove the master `merge_id` rows for those parts.
- **Not** automatically remove the `.nc` / `.pkl` files on disk; those become orphans you sweep with `DecodingOutput().cleanup(...)` afterward.

If you need a disk-impact estimate before deciding, on the parts (which carry `analysis_file_name`) you can run:

```python
DecodingOutput.ClusterlessDecodingV1.get_table_storage_usage(
    restriction=key, human_readable=True
)
DecodingOutput.SortedSpikesDecodingV1.get_table_storage_usage(
    restriction=key, human_readable=True
)
```

### Phase 3 — Confirm, then delete (only after you reply)

Once I have the inspect output and your explicit go-ahead ("yes, delete"), the call is:

```python
# Classmethod form — pass the restriction as an argument, do NOT chain it.
DecodingOutput.merge_delete(key)
```

### Phase 4 — Reclaim disk for the now-orphaned result files

```python
DecodingOutput().cleanup(dry_run=True)   # LOGS paths it would remove
# Inspect the log; if the paths look right:
# DecodingOutput().cleanup(dry_run=False)
```

Note: `cleanup()` is global — it sweeps every orphan from every session, not just `j1620210710_`. If you have other ongoing decoding work, look at the logged paths carefully before running `dry_run=False`.

### Phase 5 — Verify

```python
from spyglass.decoding import DecodingOutput
print(len(DecodingOutput().merge_restrict({"nwb_file_name": "j1620210710_.nwb"})))
# Should be 0 if you deleted everything for this session.
```

---

## What I won't do

- Hand you `DecodingOutput.merge_delete({"nwb_file_name": "j1620210710_.nwb"})` as a single line without the inspect step. Even with the right call shape, deletes against the Spyglass DB are irreversible and the cost of an unintended cascade is much higher than one extra round-trip.
- Reach for `super_delete` / `merge_delete_parent` / `force_permission=True` if the team check raises `PermissionError`. Those bypass team permissions; the default response to a `PermissionError` is to coordinate with the experimenter named in the error.

## Reply with

1. **A or B or C?** (rows for this session / orphan-file sweep / one specific merge entry)
2. The output of the Phase 1 inspect block above (row count + preview).
3. Explicit go-ahead.

Then I'll send the exact destroy call.
