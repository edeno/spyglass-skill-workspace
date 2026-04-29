Yes — this is the canonical silent-failure pattern in the common-ingest path. `insert_sessions` dispatches to `populate_all_common`, which is the driver that actually fills `Raw`, `Session`, `DIOEvents`, `PositionSource`, etc. By default `populate_all_common` runs with `raise_err=False`, so it catches per-table exceptions, writes a short message to `common_usage.InsertError`, and returns. `Nwbfile` and `Session` get inserted by `insert_sessions` *before* the driver runs, which is why those rows show up — but if any per-table call inside `populate_all_common` fails (very commonly `Raw`), you end up exactly where you are: the ingest looks clean, `Nwbfile` + `Session` exist, and the rest of common is empty.

Two things to know before the fix:

- The ingest is "quieter than a normal exception" but not totally silent. `populate_all_common` emits a summary `logger.error(...)` line at the end of the run naming the failed tables (`src/spyglass/common/populate_all_common.py:265-272`) and *returns* a list of `InsertError` keys for the failed tables. Most users discard the return value and miss the one-line error in a long log.
- The filename you pass to `populate_all_common` (and that lives in `Nwbfile`/`Raw`) is the **copied, trailing-underscore** form. `insert_sessions('j1620210710.nwb')` calls `copy_nwb_link_raw_ephys` to produce `j1620210710_.nwb` and then passes that copy through. So `Raw & {'nwb_file_name': 'j1620210710_.nwb'}` is querying the right key — your missing rows are because the per-table insert failed inside the driver, not because of a name typo.

## Primary fix — pass `raise_err=True`

`populate_all_common` has the kwarg built in (`src/spyglass/common/populate_all_common.py:159-161`, `raise_err: bool = False`). Re-run the driver with it on to surface the real traceback:

```python
from spyglass.common import populate_all_common

# Use the COPIED filename (trailing underscore) — this is the name that
# lives in Nwbfile, and the form populate_all_common expects.
populate_all_common('j1620210710_.nwb', raise_err=True)
```

You don't need to re-run `insert_sessions` — `Nwbfile` is already there, and `populate_all_common` is idempotent for the tables that already succeeded. Once you have the traceback, route to the matching signature in `runtime_debugging.md` — usually signature A (`fetch1` cardinality, e.g. an under-specified upstream restriction) or signature H (`IntegrityError`, e.g. a missing ancestor row or device/probe-type lookup miss).

## Inspect what the driver already logged

Before re-running, look at the per-table short-message log so you know which table to focus on:

```python
from spyglass.common.common_usage import InsertError

InsertError & {'nwb_file_name': 'j1620210710_.nwb'}
# .fetch(as_dict=True) for the full rows
```

You'll get one row per failed table with a short message — enough to confirm whether `Raw` itself is what failed, or something earlier (e.g., an `Electrode`/`ElectrodeGroup` insert that `Raw`'s upstream depends on).

## Alternative — skip the driver and isolate the failing table

Useful when you want to avoid re-running tables that already succeeded, or when the driver is slow and you suspect one specific table. Note: the faithful isolation pattern is *not* `T().populate(...)` — `populate_all_common` calls `table().insert_from_nwbfile(nwb_file_name, config=...)` directly for `SpyglassIngestion` tables (most common-tier tables, including `Session`, `Raw`, `DIOEvents`, `PositionSource`). Bare `populate()` skips the `entries.yaml` config and can fail differently than the driver did.

```python
from spyglass.common import Session, Raw, DIOEvents, PositionSource

copy_name = 'j1620210710_.nwb'
for T in [Session, Raw, DIOEvents, PositionSource]:
    T().insert_from_nwbfile(copy_name)   # exception propagates
```

Treat this as the alternative, not the primary fix — `raise_err=True` is the function's intended escape hatch and matches the driver's exact path.

## Do not edit `populate_all_common.py`

The right knob is the kwarg, not the source. The skill explicitly calls out that editing the installed Spyglass package desyncs your DB schema from what other labs run and gets silently reverted by `pip install -e .` — push back if anyone suggests changing `raise_err`'s default in source.

## Watch-outs

- **Filename form.** Always query/populate with the trailing-underscore copied name (the one in `Nwbfile`). Restricting `Raw & {'nwb_file_name': 'j1620210710.nwb'}` (no underscore) returns nothing because that's the *raw* filename, not the copy.
- **`Session` rows existing is not proof of success.** `Session` is among the things the driver populates; it can sometimes succeed when downstream tables fail (the per-table loop is sequential and continues past failures unless `rollback_on_fail=True`). So "Session is there" doesn't mean the rest of common is.
- **Once you have the traceback,** common root causes for `Raw`-level failures are: malformed experimenter / subject metadata, device or probe-type names that don't match the lookup tables, missing `ndx-franklab-novela` / `ndx-pose` extension objects in the NWB, or an `Electrode`/`ElectrodeGroup` upstream that itself failed. The traceback will name the exact field; route from there using `runtime_debugging.md` signatures A or H.
