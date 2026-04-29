# `populate_all_common` returned without raising — what to look at first

Good news: this run is **not** fully silent. Before opening any reference file, surface two recoverable signals that current Spyglass produces, in this order.

## 1. Scroll your shell for the summary `logger.error` line

At the end of the run, `populate_all_common` itself logs a one-line summary naming every table that failed. From the source (`src/spyglass/common/populate_all_common.py:265-272`):

```python
if err_query:
    err_tables = err_query.fetch("table")
    logger.error(
        f"Errors occurred during population for {nwb_file_name}:\n\t"
        + f"Failed tables {err_tables}\n\t"
        + "See common_usage.InsertError for more details"
    )
    return err_query.fetch("KEY")
```

So in your scrollback, search for a line shaped like:

```
Errors occurred during population for j1620210710_.nwb:
    Failed tables [...,'Electrode',...]
    See common_usage.InsertError for more details
```

If `Electrode` is in that `Failed tables` list, that's your confirmation that `Electrode` was attempted and the per-table insert raised — the driver caught it (default `raise_err=False`) and kept going. That's exactly why the call "returned without raising" but `Electrode` has zero rows.

## 2. The function also *returns* the failure inventory — re-run capturing it

Same code block above: the function returns `err_query.fetch("KEY")` — i.e., a list of **`InsertError` keys**, one per failed table. Most users discard the return value, and if your scrollback got truncated or lost (long buffer, killed pager, remote shell hiccup), the cheapest way to recover the same information is to re-run with the return captured:

```python
from spyglass.common import populate_all_common

failed = populate_all_common("j1620210710_.nwb")
print(failed)   # list of InsertError keys; empty/None means no failures this run
```

These are the two things to read off your shell **before** opening anything else. The run is quieter than a normal traceback, but it isn't fully silent.

## What to open next: `populate_all_common_debugging.md`

Once you've confirmed which tables failed (from the logger line or the returned list), open [`references/populate_all_common_debugging.md`](../../../../skills/spyglass/references/populate_all_common_debugging.md). It's scoped specifically to this symptom — per-table errors swallowed by the `populate_all_common` driver because of the default `raise_err=False` — and walks through the per-table triage flow.

Why that page and not the more general `runtime_debugging.md`: `runtime_debugging.md` keys off failure *signatures* in a Python traceback you already have in hand. You don't have a traceback here — the driver caught it. So the first move is to recover the traceback (the debugging page tells you to re-run with `raise_err=True`), and only then route into `runtime_debugging.md` to match a signature.

## Where the actual stack-trace details live

The summary `logger.error` only names which tables failed — it doesn't include each per-table traceback. Those live in the `common_usage.InsertError` table, which the driver writes to as it catches each per-table exception. Query it scoped to your file:

```python
from spyglass.common.common_usage import InsertError

InsertError & {"nwb_file_name": "j1620210710_.nwb"}
```

Each row corresponds to one failed table for this NWB file and carries the captured error message. For `Electrode` specifically, restrict further:

```python
InsertError & {"nwb_file_name": "j1620210710_.nwb", "table": "Electrode"}
```

This is usually enough to point at the cause (probe / electrode-group mismatch, missing `ndx-franklab-novela` metadata, etc.) without re-running. If the captured message is too short, the canonical next step is to re-run with `raise_err=True` to surface the full Python traceback.

## On bundled scripts — there isn't one for this

Heads-up so you don't go looking: the skill ships only two user-facing diagnostic scripts, neither relevant here:

- `scripts/scrub_dj_config.py` — redacts secrets from your DataJoint config (use this instead of `cat`-ing `dj_local_conf.json`).
- `scripts/verify_spyglass_env.py` — install/env sanity check.

There is **no bundled populate-diagnostic script** under `skills/spyglass/scripts/`. If anything suggests running a populate-status or populate-diagnose helper from this skill, it's invented — the canonical populate-failure flow is the logger line + the `InsertError` query + `raise_err=True`, exactly as above.

## Recap — the order

1. Scroll your shell for `Errors occurred during population for j1620210710_.nwb` (`populate_all_common.py:265-272`).
2. If you can't find it, re-run as `failed = populate_all_common("j1620210710_.nwb")` and inspect `failed`.
3. Query `InsertError & {"nwb_file_name": "j1620210710_.nwb"}` (and optionally `"table": "Electrode"`) to read the captured per-table error.
4. Open `populate_all_common_debugging.md` for the full per-table triage flow, including the `raise_err=True` re-run that gives you the real traceback.
