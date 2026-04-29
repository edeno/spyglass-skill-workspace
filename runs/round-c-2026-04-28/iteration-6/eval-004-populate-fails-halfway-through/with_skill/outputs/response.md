# Isolating the failing key in a partially-completed `LFPV1.populate()`

Yes — you don't need to rerun anything one-at-a-time by hand. There are three legitimate, complementary ways to find the broken key, all from standard DataJoint. Spyglass ships **no** `debug_populate` / `populate_one` helper; `PopulateMixin.populate` just delegates to DataJoint's `populate()` (`src/spyglass/utils/mixins/populate.py:48-122`), so all the recovery levers below are stock-DataJoint facilities.

One important up-front fact: Spyglass's default is `_use_transaction = True` (`src/spyglass/utils/mixins/populate.py:10`). When a `make()` raises, DataJoint rolls the transaction back, so post-mortem you will not see partial residue in `LFPV1` for the failing key — its row never landed. That's good (no cleanup), but it means the only record of *what failed* is whatever you can recover from the jobs table or by re-running.

## Symptom

`LFPV1.populate()` ran on ~20 sessions, succeeded on most, failed on one (or a few), with a deep DataJoint traceback that doesn't name the offending `key`.

## Most likely root cause

A single key in `LFPV1.key_source` (which defaults to `LFPSelection.proj()` — `LFPV1` is `dj.Computed` with no custom `key_source` override) hit a data-shape or upstream-lookup problem inside `make()`. With transactions on, the failing row was rolled back; the parent `populate()` re-raised one exception from the loop and you saw frames from DataJoint's orchestration rather than the user-code frame.

## Three legitimate ways to identify the failing key

Pick whichever fits — they're not mutually exclusive.

### Option 1 — Manual try/except over `key_source`

Most explicit. Gives you a clean per-key traceback the moment something breaks:

```python
from spyglass.lfp.v1 import LFPV1

# Enumerate the keys LFPV1 would normally process
keys = LFPV1.key_source.fetch("KEY")
print(f"{len(keys)} keys in key_source")

failures = []
for k in keys:
    try:
        LFPV1().populate(k, reserve_jobs=False)
    except Exception as e:
        print(f"FAILED on key: {k}")
        print(f"  {type(e).__name__}: {e}")
        failures.append((k, e))
        # `break` if you want to stop at the first one;
        # leave it to collect every failure in one pass.
```

Combine with `processes=1` (which is already the default in Spyglass's `populate` wrapper — see `populate.py:61`) so the traceback isn't filtered through a worker pool. Already-populated keys are skipped automatically; this won't redo work.

If you want a still-narrower repro once you have the key, bypass `populate()` entirely and call `make()` directly — it gives the most informative traceback because there's no orchestration in the way:

```python
LFPV1().make(failing_key)
```

### Option 2 — `suppress_errors=True, return_exception_objects=True`

Most efficient. One pass; DataJoint runs every remaining key, captures exceptions instead of raising, and returns a list of `(key, exception)` pairs:

```python
errors = LFPV1().populate(
    suppress_errors=True,
    return_exception_objects=True,
    reserve_jobs=False,
)
for key, exc in errors:
    print(key, "->", type(exc).__name__, exc)
```

This is the right shape when you want to see *all* failures in one shot rather than stopping at the first.

### Option 3 — Inspect the `~jobs` table

If the original overnight run used `reserve_jobs=True`, DataJoint has already recorded the failing key plus its traceback in the schema's `~jobs` table under `status='error'`. You don't need to rerun anything to find it:

```python
import datajoint as dj

# Derive the schema from the failing table — don't hard-code 'lfp_v1',
# because Spyglass schemas are split across many DB names.
schema_name = LFPV1.database              # the underlying schema
jobs = dj.Schema(schema_name).jobs

errors = jobs & {
    "table_name": LFPV1.table_name,       # the symptom table specifically
    "status": "error",
}
errors.fetch(as_dict=True)                # key + full traceback per failed row
```

Each row contains the failing primary key plus the captured traceback string, so you get the exception text without re-running. After you've fixed the cause, `errors.delete_quick()` clears the reservations so the next `populate()` retries them.

If your overnight run did *not* set `reserve_jobs=True`, this table will be empty for `LFPV1` — fall back to Option 1 or 2.

## Suggested order

1. Check `~jobs` first (Option 3). If the original run reserved jobs, the failing key and traceback are already there — zero re-run cost.
2. If `~jobs` has nothing useful, run Option 2 (`suppress_errors=True, return_exception_objects=True`) to enumerate every failure in one pass.
3. Once you have a specific failing key, reproduce it with `LFPV1().make(failing_key)` for the cleanest single-key traceback, then triage from there (compare it against a succeeding key — different interval, electrode count, NaN-only epoch, missing upstream row, etc.).

## Watch-outs

- **`use_transaction=True` is Spyglass's default** (`populate.py:10`). On failure, the partial row is rolled back, so don't expect to find half-written `LFPV1` entries for the broken key — they were never committed. That's why the jobs table or a re-run is the only post-mortem signal.
- **Don't reach for a Spyglass-specific debug helper** — there isn't one. `PopulateMixin.populate` just forwards to `super().populate(...)` when transactions are on (`populate.py:96-98`), so all standard DataJoint flags (`suppress_errors`, `return_exception_objects`, `reserve_jobs`, `processes`) work as documented.
- **Avoid `processes>1` while debugging.** Spyglass's wrapper defaults to `processes=1`; bumping it up hides which worker died. Single-process serial reruns give the cleanest traceback.
- **Reserved-but-not-cleared jobs** from a crashed run will silently skip on the next populate and look like "nothing is happening." If you adopt Option 3, remember to `delete_quick()` the error rows once the underlying bug is fixed, or future populates will keep skipping those keys.
