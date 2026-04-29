# Recovering a partial `populate_all_common` — diagnose before you destroy

Short answer: **don't delete anything, and don't blindly re-run yet.** The driver completed without raising because its default is `raise_err=False`, which catches per-table exceptions and writes a one-line message to `common_usage.InsertError` instead of letting the traceback escape (`src/spyglass/common/populate_all_common.py:151-156, 159-161`). `Electrode` and `ElectrodeGroup` being empty while `Session`, `IntervalList`, and `Raw` are populated is the classic signature of one or more silently-swallowed per-table failures. There is a dedicated reference for exactly this case — see [`populate_all_common_debugging.md`](../../../../skills/spyglass/references/populate_all_common_debugging.md).

## Step 1 — Inspect `common_usage.InsertError` first (no DB writes, no deletes)

This is the safe diagnostic. The driver records every swallowed failure here, keyed in part by `nwb_file_name`:

```python
from spyglass.common.common_usage import InsertError

# Use the *copied* (trailing-underscore) filename — that's what
# `insert_sessions` registers and what `populate_all_common` was called with.
nwb_file_name = "j1620210710_.nwb"

errs = InsertError & {"nwb_file_name": nwb_file_name}
print(len(errs))
errs.fetch("table", "error_type", "error_message", as_dict=True)
```

The `InsertError` schema is `(id, dj_user, connection_id, nwb_file_name, table, error_type, error_message, error_raw)` (`src/spyglass/common/common_usage.py:43-54`). The `table` column will tell you whether `ElectrodeGroup` failed first (and `Electrode` then had nothing to depend on), or whether they both failed independently. `error_message` is truncated to 255 chars but usually identifies the failure type (e.g., a probe-type mismatch, a missing `ndx-franklab-novela` field, an `ElectrodeGroup` row collision).

Two cheaper signals you may also still have:
- The summary `logger.error(...)` line near the end of the original run names the failed tables (`populate_all_common.py:265-272`). Worth scrolling back through the 20-minute-old log.
- If the call site captured the return value (`failed = populate_all_common(...)`), `failed` is the list of `InsertError` keys for this run.

## Step 2 — Re-run only the affected table(s) with `raise_err=True` to surface the full traceback

`error_message` alone often isn't enough. The supported way to get a real Python traceback is `raise_err=True` (`populate_all_common.py:159-161, 152-153`):

```python
from spyglass.common import populate_all_common

# Fresh kernel recommended (clean connection, no stale transaction state).
# Pass the same copied filename used originally.
populate_all_common("j1620210710_.nwb", raise_err=True)
```

Because `Session`/`IntervalList`/`Raw` are already populated, the driver's idempotent inserts will short-circuit them; the rerun will mostly just retry the previously failed tables and now propagate the exception. From the traceback, route to [`runtime_debugging.md`](../../../../skills/spyglass/references/runtime_debugging.md) and match the failure signature.

If you'd rather isolate even more tightly than `populate_all_common` allows, the faithful per-table form for these `SpyglassIngestion` tables is the driver's own pattern, **not** `T().populate(...)`:

```python
from spyglass.common import ElectrodeGroup, Electrode

ElectrodeGroup().insert_from_nwbfile("j1620210710_.nwb")  # exception now propagates
Electrode().insert_from_nwbfile("j1620210710_.nwb")
```

`populate_all_common_debugging.md` explains why `T().populate(...)` is the wrong faithful isolation — it bypasses `entries.yaml` config that the driver applies, so a table that succeeds under the driver can fail under bare `populate()` for unrelated reasons.

## What NOT to do

- **Do not delete `Session`, `IntervalList`, or `Raw`.** Those rows ingested correctly. Deleting them isn't recovery — `Session` is a top-level parent for nearly the whole common schema and many downstream pipelines, so a `.delete()` cascades far beyond what you can see, and recovery from a cascading delete is much more expensive than a re-ingest. (Even if you *did* want a clean slate later, the supported path is `insert_sessions(..., reinsert=True)`, not a manual delete — but you don't need a clean slate here. See [`destructive_operations.md`](../../../../skills/spyglass/references/destructive_operations.md) for the inspect-before-destroy rule.)
- **Do not re-run the full `populate_all_common(...)` blindly without first inspecting `InsertError`.** Re-running with the same default `raise_err=False` will silently re-fail in exactly the same place; you'll burn another 20 minutes and learn nothing new. If the underlying cause is a malformed NWB field (probe metadata, electrode group naming, missing extension), no number of reruns will fix it — only patching the NWB or the lookup data will.
- **Do not jump to `super_delete()` / `force_permission=True` / `rollback_on_fail=True`.** `rollback_on_fail` calls `super_delete` on the `Nwbfile` row and is destructive (`populate_all_common.py:260-263`); only consider it after you understand the failure and have decided you actually want to re-ingest from scratch.

## TL;DR ordering

1. `InsertError & {"nwb_file_name": "j1620210710_.nwb"}` — read which table failed and why.
2. `populate_all_common("j1620210710_.nwb", raise_err=True)` on a fresh kernel — get the real traceback.
3. Fix the root cause (NWB content, lookup row, or extension), then re-run; only then consider whether anything needs to be deleted, and only with the inspect-before-destroy pattern from [`destructive_operations.md`](../../../../skills/spyglass/references/destructive_operations.md).

Full reference: [`populate_all_common_debugging.md`](../../../../skills/spyglass/references/populate_all_common_debugging.md).
