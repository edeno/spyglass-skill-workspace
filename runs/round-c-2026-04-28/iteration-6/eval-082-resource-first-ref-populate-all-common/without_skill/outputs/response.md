# Debugging a silent `populate_all_common` run

Short answer: the call wasn't actually silent — there is signal in your shell
and signal still in the database. Look there before you start poking at
individual tables.

## What to look at first

### 1. Scroll back through your terminal for a logger line, not just tracebacks

`populate_all_common` defaults to `raise_err=False`, so per-table failures are
*caught* and logged, not raised. That's why the call returned cleanly even
though `Electrode` is empty. But at the very end of the run, after walking all
the table groups, the function checks an in-DB error log and emits a single
`logger.error(...)` summarizing what failed. Concretely, in
`src/spyglass/common/populate_all_common.py` (around lines 257–272):

```python
err_query = InsertError & error_constants
...
if err_query:
    err_tables = err_query.fetch("table")
    logger.error(
        f"Errors occurred during population for {nwb_file_name}:\n\t"
        + f"Failed tables {err_tables}\n\t"
        + "See common_usage.InsertError for more details"
    )
    return err_query.fetch("KEY")
```

So the first thing to do is scroll back in your shell for a line that begins
roughly:

```
Errors occurred during population for j1620210710_.nwb:
        Failed tables ['Electrode', ...]
        See common_usage.InsertError for more details
```

If you see that line, you already know which tables failed without needing to
guess. The `[INFO] Populating <Table>...` messages from
`single_transaction_make` are also useful breadcrumbs — the last `Populating`
line before the error summary shows roughly where things started going wrong.

### 2. If you've already lost the logger output, just re-run and capture the return value

This is the part most people miss: `populate_all_common` *returns* the list of
failed `InsertError` keys (see the `Returns` section of the docstring and the
final `return err_query.fetch("KEY")`). So if your scrollback is gone, you
don't have to reproduce the full pipeline — re-running with the return value
captured gives you the same information programmatically:

```python
failed = populate_all_common("j1620210710_.nwb")
print(failed)        # list of InsertError keys, or None if all clean
```

If `failed` is non-empty, that confirms the call wasn't really silent.

### 3. The actual stack traces live in `common_usage.InsertError`

The logger line names *which* tables failed. The exception type and full error
message for each failure are persisted to the `InsertError` table by
`log_insert_error` (`populate_all_common.py:50–79`). To pull the per-table
details for this NWB:

```python
from spyglass.common.common_usage import InsertError
(InsertError & {"nwb_file_name": "j1620210710_.nwb"}).fetch(
    "table", "error_type", "error_message", "error_raw"
)
```

That's where you'll find out *why* `Electrode` insertion bailed — typically
something upstream like `ElectrodeGroup` or `Probe.Electrode` not having the
rows it needed, or an NWB-extension/probe-config mismatch surfacing as a
`KeyError` / `ValueError` during the make. `Electrode` is in the third
table-group in `populate_all_common.py` (line 226), so its parents
(`ElectrodeGroup` from group 2) must have populated successfully — check those
in `InsertError` too, since a parent failure cascades to "no rows in child."

## What you'd have missed in your terminal output

Three things the scroll-back probably contains that are easy to read past:

- The single `logger.error` summary line at the end of the run (above). It's
  the high-signal artifact and is easy to miss because it doesn't look like a
  Python traceback.
- The `[INFO] Populating <TableName>...` lines emitted by `_info_msg` before
  each `make`. Sequence + which one is the *last* one before the error summary
  tells you where the cascade started.
- Any DataJoint `[WARNING]` lines about transaction rollback or duplicate keys
  — those don't raise but they do print.

What you would *not* see in the terminal (because it never gets logged there)
is the per-table traceback — that's only in `common_usage.InsertError`.

## A note on what's bundled

There isn't a Spyglass-shipped CLI script for diagnosing populate failures.
The two user-facing helper scripts I'd point you at for adjacent problems are:

- `scrub_dj_config.py` — for safely sharing your DataJoint config (redacts
  passwords) when you need someone else to look at your setup.
- `verify_spyglass_env.py` — for sanity-checking your install/env if you
  suspect the failure is environmental rather than data-shaped.

Neither is the right tool for "Electrode is empty after `populate_all_common`."
The right tool is the `InsertError` query above. If you find a recipe online
or in old notes that references something like `check_populate_status.py` or
`diagnose_populate.py`, those aren't part of the current Spyglass distribution
— don't go hunting for them.

## Summary of what I'd run, in order

1. Scroll back in the shell for `Errors occurred during population for ...` /
   `Failed tables [...]`. If found, you have the table list immediately.
2. If the scrollback is gone:
   ```python
   failed = populate_all_common("j1620210710_.nwb")
   ```
   and inspect `failed`.
3. For each failed table, query `InsertError` for the `error_type` and
   `error_raw` to get the actual exception detail.
4. Fix the root cause (most often an upstream table — `ElectrodeGroup`,
   `Probe.Electrode` — or an NWB-side schema / probe-config mismatch) and
   re-run. Once you know the failing table, re-running just that one with
   `raise_err=True` (or calling its `make` directly) will give you a live
   traceback to debug against.
