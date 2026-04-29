# Safe next step after partial `populate_all_common`

Short answer: **don't re-run the ingest yet.** The pattern you describe (some
tables populated, `Electrode.probe_id` null, `Probe` missing the relevant
`probe_type`) is the exact fingerprint of a *silently-skipped* upstream
insert. The diagnostic you need almost certainly already exists; you just
have to read it.

## 1. Read what `populate_all_common` already recorded

By default `populate_all_common(...)` is called with `raise_err=False`.
When that flag is false, exceptions raised by individual table inserts
are caught and logged to `common_usage.InsertError` rather than
propagated. The downstream tables that depended on the failed insert
then either skip or insert with NULLs in nullable FK columns — which
matches your symptom exactly (`Electrode` populated, but its `probe_id`
column, which is a nullable FK to `Probe.Electrode`, is null because the
matching `Probe` row never got created).

So before doing anything else, query the error log restricted to this
NWB file:

```python
from spyglass.common.common_usage import InsertError

errs = (InsertError & {"nwb_file_name": "j1620210710_.nwb"}).fetch(as_dict=True)
for e in errs:
    print(e["table"], "|", e["error_type"], "|", e["error_message"])
```

That tells you *which* table actually raised and *what* the message was.
Read this list carefully — there may be more than one entry, and the
order matters (an upstream failure usually generates a cascade of
downstream "missing dependency" entries).

## 2. Expect the failure to be upstream of `Probe`, not on `Probe` itself

This is the part that trips people up. `Probe` does **not** stand on its
own — its definition has a hard FK to `ProbeType`, and a nullable FK to
`DataAcquisitionDevice`:

```
probe_id : varchar(80)
---
-> ProbeType                          # required
-> [nullable] DataAcquisitionDevice
contact_side_numbering : enum(...)
```

`ProbeType` is populated in an *earlier* transaction batch than `Probe`
in `populate_all_common`. If reading the probe-type metadata out of the
NWB file (or matching it against a yaml config) raised — e.g. an
unrecognized `probe_type` string, a missing required field, a yaml
config mismatch — then:

- the `ProbeType` row is never inserted,
- the `Probe` insert in the next batch fails its FK check and is
  logged to `InsertError`,
- `Probe.Electrode` never gets created,
- and the later `Electrode` (the ephys-side table that links
  `ElectrodeGroup` → `Probe.Electrode`) inserts with `probe_id = NULL`
  because that FK is nullable.

So when you see "missing `Probe` rows", the bug is almost always one
level up — typically `ProbeType`, occasionally `DataAcquisitionDevice`.
The InsertError message will name the actual table that raised.
You confirmed via HDFView that the tetrode metadata is in the NWB; the
question is whether Spyglass *interpreted* it as a known `ProbeType` /
`DataAcquisitionDevice`, which is a separate concern from "is the data
in the file".

## 3. Reproduce the failure with a real traceback

Once you know which table failed from `InsertError`, re-run with
`raise_err=True` so the exception isn't swallowed:

```python
from spyglass.common import populate_all_common
populate_all_common("j1620210710_.nwb", raise_err=True)
```

That gives you a real Python traceback pointing at the offending line.
You can also call the specific table's populate/insert path directly
restricted to this file, again with `raise_err=True`, if you want to
isolate it.

Tip: do this in a fresh kernel/process so you're not carrying any
stale connection state from the failed run.

## 4. Fix the root cause, then top up

Once you know what the upstream table objected to, the fix is usually
one of:

- adding a missing `ProbeType` row (e.g. tetrode probe types sometimes
  need to be inserted manually if your NWB labels them with a
  non-canonical name and there's no auto-mapping),
- adding a missing `DataAcquisitionDevice` / amplifier / system row,
- correcting the relevant entry in `entries.yaml` (the config consulted
  during `populate_all_common`).

After that, re-running the populate will fill in the previously-skipped
rows. You generally do *not* need to delete the `Session` / `Raw` /
`IntervalList` / `Electrode` rows that already inserted — the
populate step is idempotent for those, and downstream rows like
`Probe` and proper `Electrode.probe_id` linkage will fill in once
their parents exist. If `Electrode` rows are pinned to a null
`probe_id` and re-population doesn't update them in place, you may
need to delete just those `Electrode` rows for this nwb file (via
the table's own delete with the standard cautious_delete path) and
let them re-insert with the correct FK. Confirm against the
InsertError trail before doing that — don't pre-emptively wipe rows
that are fine.

## 5. What not to do

- **Don't** force-reinsert the session (e.g. `insert_sessions(...,
  reinsert=True)`) before reading `InsertError`. You'll re-trigger
  the same silent skip and overwrite the diagnostic trail.
- **Don't** super_delete / bypass the cautious-delete path on the
  rows that *did* populate (`Session`, `IntervalList`, `Raw`,
  `Electrode`). They're correct; deleting them cascades destructively
  downstream and removes evidence.
- **Don't** assume the bug is in `Probe`. The `Probe` table itself is
  almost never the thing that raised — it just can't insert because
  its `ProbeType` parent (or, less commonly, a
  `DataAcquisitionDevice` it references) didn't make it in.

## TL;DR

1. `(InsertError & {"nwb_file_name": "j1620210710_.nwb"}).fetch(as_dict=True)`
2. Re-run with `raise_err=True` to get a real traceback.
3. Look at `ProbeType` first (and `DataAcquisitionDevice` second) —
   that's where the silent skip almost always lives when `Probe` rows
   are missing.
4. Add the missing parent row, re-populate. Don't blast the
   already-good rows.
