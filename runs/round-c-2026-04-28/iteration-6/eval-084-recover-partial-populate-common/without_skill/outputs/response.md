# Diagnosing a partial `populate_all_common` run

You're in good shape — the function exited cleanly so DataJoint's transactions
committed everything that *did* succeed (Session, IntervalList, Raw), and the
empty tables (Electrode, ElectrodeGroup) just mean a downstream `make()` call
either silently skipped or had its exception swallowed. Before you delete or
re-run anything, walk through these steps in order. Stop as soon as one of them
gives you the answer.

## 1. Don't delete anything yet

Deleting `Session` (or any of the parent rows that *did* land) will cascade
through the whole schema via DataJoint's foreign-key delete semantics. You
would lose IntervalList and Raw too, and possibly anything else that already
hangs off this NWB file. Recovery is forward (re-populate the missing
children), not backward (wipe the parents and start over).

Same logic applies to a blanket re-run of `populate_all_common(...)`. If
something is silently swallowing the per-table failure, re-running the wrapper
will silently swallow it again and you'll be no closer to a diagnosis.

## 2. Look for whatever the wrapper logged on its way past the failure

`populate_all_common` is almost certainly a convenience wrapper around several
`Table.populate()` calls. Wrappers like this typically have one of two
shapes — figure out which one yours has:

- It calls each table's `populate()` with `reserve_jobs=True`. In that case
  DataJoint records every failure in the `~jobs` virtual table on the schema.
  Inspect it:

  ```python
  from spyglass.common import schema  # or whatever module owns Electrode
  schema.jobs & {"table_name": "__electrode"}  # note the mangled name
  schema.jobs.fetch(format="frame")            # full picture
  ```

  Each failed job carries `error_message` and `error_stack` columns — that's
  the swallowed traceback you need.

- It catches exceptions and logs them somewhere project-specific (a log file,
  a status table, a `print` to stderr). Grep the codebase for the wrapper:

  ```bash
  grep -rn "def populate_all_common" $SPYGLASS_SRC/src/spyglass/
  ```

  Read the function. Two things to check: (a) does it pass `raise_err` /
  `suppress_errors` / similar through to `populate()`, and (b) does it stash
  failures in a side table (something like `common_usage.InsertError` is a
  common Spyglass pattern). If yes, restrict that table to your file:

  ```python
  from spyglass.common import common_usage
  (common_usage.InsertError & {"nwb_file_name": "j1620210710_.nwb"}).fetch(
      format="frame"
  )
  ```

This is the cheapest, safest diagnostic — it's pure read, no side effects, and
it should tell you both *which* table failed and *why*.

## 3. Re-run only the affected table, with errors raised

Once you know it's `Electrode` (and `ElectrodeGroup` is empty as a downstream
consequence), re-run *just that table* with errors no longer suppressed:

```python
from spyglass.common import Electrode

key = {"nwb_file_name": "j1620210710_.nwb"}
Electrode.populate(key, reserve_jobs=False, suppress_errors=False)
# or, if the wrapper accepts it:
# populate_all_common("j1620210710_.nwb", raise_err=True)
```

Run it on a fresh kernel so you're not inheriting any half-imported NWB
handles from the original session. The full traceback will then point at the
real cause — typically one of:

- The NWB file's `/general/extracellular_ephys/electrodes` table is missing a
  required column (often a project-specific extension like `probe_id`,
  `bad_channel`, or a `ndx-franklab-novela` field).
- The probe / electrode group referenced in the NWB file isn't yet inserted
  into `Probe` / `ProbeType`, so the FK insert into `ElectrodeGroup` fails.
- A units mismatch (impedance in Ω vs MΩ, location string vs enum) trips a
  DataJoint type check.
- The NWB file was written by a slightly different `ndx-*` version than the
  Spyglass insert code expects.

## 4. Once you have the traceback, fix forward

Whatever the root cause, the recovery is:

1. Fix the input (patch the NWB file, install the missing probe definition,
   bump the extension version) **or** fix the make function if it's a code
   bug.
2. Clear any stuck `jobs` / `InsertError` row for this key so the next
   `populate()` will retry it.
3. Re-run `Electrode.populate(key)` — *not* the whole `populate_all_common`,
   since the rest already succeeded.
4. Then `ElectrodeGroup.populate(key)` (and any other downstream that was
   gated on Electrode).

## Summary

- **Do not** delete Session/IntervalList/Raw — they're correct, and the delete
  cascades.
- **Do not** blindly re-run `populate_all_common`; whatever swallowed the
  error will swallow it again.
- **Do** inspect the schema's `jobs` table and any project-level error table
  (e.g. `common_usage.InsertError`) restricted to this `nwb_file_name`.
- **Do** re-run only the failing table with `suppress_errors=False` (or the
  wrapper's `raise_err=True` equivalent) on a fresh kernel to surface the
  traceback.
- **Then** fix the underlying cause and re-populate forward, table by table.
