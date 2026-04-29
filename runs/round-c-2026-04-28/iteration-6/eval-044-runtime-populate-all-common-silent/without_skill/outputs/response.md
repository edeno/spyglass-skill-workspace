# Silent ingest: `populate_all_common` swallows per-table exceptions by default

Yes — this is a known, well-defined silent-failure pattern in Spyglass, and you have not actually hit a bug in your NWB file. What is happening is that `insert_sessions` is a thin wrapper that delegates the real work to `populate_all_common`, and `populate_all_common` defaults to **`raise_err=False`**, which catches every per-table exception, writes a 255-char summary to `common_usage.InsertError`, and keeps going. From the caller's perspective the run "succeeded" — `Nwbfile` and `Session` get inserted in an early transaction, so they are present — but `Raw`, `DIOEvents`, `PositionSource`, etc., can all be empty and you only see a one-line "Errors occurred during population" log line at the very end (easy to miss in a notebook).

You can confirm this by reading the source:

- `src/spyglass/data_import/insert_sessions.py` — `insert_sessions(..., raise_err=False)` ends with `return populate_all_common(out_nwb_file_name, rollback_on_fail=..., raise_err=raise_err)`.
- `src/spyglass/common/populate_all_common.py` — `populate_all_common(nwb_file_name, rollback_on_fail=False, raise_err=False)` calls `single_transaction_make(...)` for each batch of tables. Inside that helper, every `make` / `insert_from_nwbfile` call is wrapped in `try / except Exception as err: if raise_err: raise err; log_insert_error(table=table, err=err, ...)`. So with the default, a failure in `Raw.make` (or `DIOEvents.make`, or `PositionSource.make`, ...) is caught, summarised into `InsertError`, and the loop moves on to the next table.

The reason `Session` and `Nwbfile` are populated but `Raw` is empty is exactly the table ordering inside `populate_all_common`: `Session` is in the second transaction batch, `Raw`, `DIOEvents`, `SampleCount`, etc. are in the same batch but each is wrapped in its own try/except, and `PositionSource` is in the third batch. Anything that throws in batch 2 or later just shows up as an `InsertError` row.

## Primary fix — re-run with `raise_err=True`

You do **not** need to edit `populate_all_common.py` and you do **not** need to redo `insert_sessions` (the file copy and `Nwbfile` row are fine). Just call `populate_all_common` directly on the already-registered file with the kwarg flipped:

```python
from spyglass.common import populate_all_common

populate_all_common('j1620210710_.nwb', raise_err=True)
```

That uses the function's own built-in parameter (no source edits, no monkey-patching) and propagates the first underlying exception with a full traceback so you can actually see what failed — typically things like a `fetch1` cardinality error, an `IntegrityError` from a missing parent row, an NWB schema mismatch, or a missing optional field.

## First, look at what was already logged

Before you re-run, query the error log — `populate_all_common` already wrote one row per failed table:

```python
from spyglass.common.common_usage import InsertError

(InsertError & {'nwb_file_name': 'j1620210710_.nwb'}).fetch(
    'table', 'error_type', 'error_message', as_dict=True
)
```

The `error_message` column is truncated to 255 chars (see the `InsertError.definition` in `common_usage.py`), and `error_raw` holds the longer string but **not the traceback** — the traceback is what `raise_err=True` gets you. Still, the table name + error type usually narrows the suspect immediately (e.g. `Raw` + `KeyError` vs `PositionSource` + `IndexError` point in very different directions).

## Alternative — bypass the driver and populate tables individually

If you want to isolate which table is failing without re-running the ones that already succeeded (e.g. `Session` inserted fine, you don't want to reinsert it), skip `populate_all_common` and call each table's `populate` directly. `populate` will let exceptions through normally — it does not have the silent-error wrapper:

```python
from spyglass.common import Session, Raw, DIOEvents, PositionSource

key = {'nwb_file_name': 'j1620210710_.nwb'}
for T in [Session, Raw, DIOEvents, PositionSource]:
    T().populate(key)   # exception propagates with full traceback
```

This is the right choice if you want to skip already-populated tables, or if you suspect only one specific table (e.g. `PositionSource`) is the problem — call just that one. Note this is the **alternative**, not the primary fix; the simplest path remains `populate_all_common(..., raise_err=True)`.

## Why this design exists (so you know what you're trading)

The default `raise_err=False` is intentional: in batch ingest of many sessions, it lets a flawed file degrade gracefully rather than aborting the whole run. The cost is exactly what you observed — a single-file ingest looks "clean" while half the common pipeline is missing. For interactive single-file work, always pass `raise_err=True`. You can also pass `rollback_on_fail=True` if you want a clean slate (it `super_delete`s the `Nwbfile` row when any error fires), but that interacts with `raise_err=True` such that no rollback happens once you raise — read the docstring before combining them.

## Summary of what to do, in order

1. Inspect `common_usage.InsertError & {'nwb_file_name': 'j1620210710_.nwb'}` to see which tables failed and the truncated message.
2. Re-run with `populate_all_common('j1620210710_.nwb', raise_err=True)` to get a real traceback for the first failure.
3. Fix the underlying issue (most often: missing/wrong field in the NWB file, or a parent-table dependency that didn't get inserted), and re-run.
4. If you want to target one specific failing table without re-running the others, call `T().populate({'nwb_file_name': ...})` directly — exceptions propagate as usual.

Do **not** edit `populate_all_common.py` to change the default — `raise_err` is exactly the supported knob for this, and editing source would mask the same issue for every other user.
