# Finding the failing key in a long `LFPV1.populate()` run

Yes — you don't have to rerun anything one-at-a-time by hand. DataJoint
already gives you several ways to recover which key broke. The trick is
that `populate()` iterates over `LFPV1.key_source` (the set of upstream
keys that don't yet have a downstream entry), and any of the approaches
below either *enumerates* that key set yourself or asks DataJoint to
*report* which entry in that set blew up.

A useful framing first: by default `populate()` runs each `make()` call
inside a transaction, so a failure rolls the partial insert back. That's
why nothing weird is sitting in `LFPV1` after the crash — the table
looks like the failing session never started, which is exactly why the
30-frame traceback alone doesn't tell you which key it was.

Below are three legitimate ways to get the key out, in increasing order
of how lightweight they are.

---

## 1. `suppress_errors=True, return_exception_objects=True` (one shot, easiest)

This is the standard DataJoint facility for exactly this situation.
Instead of bombing out on the first failure, `populate()` continues
through the rest of `key_source` and hands you back a list of
`(key, exception)` pairs at the end:

```python
results = LFPV1.populate(
    display_progress=True,
    suppress_errors=True,
    return_exception_objects=True,
)

# results is a list of (key_dict, exception_instance) for every failure
for key, err in results:
    print(key)
    print(f"  -> {type(err).__name__}: {err}")
```

Pros: one pass over the remaining `key_source`, no manual loop, you get
*all* failures (not just the first one) — handy if more than one session
is broken.

Cons: each failing session is wrapped in DataJoint's transaction
machinery, so the traceback you get back is still the deep one. Once
you know the failing key, re-run that single key (see below) for a
clean stack.

---

## 2. Manual loop over `key_source` (most explicit traceback)

If you want a clean per-key traceback rather than a captured exception
object, loop over the keys yourself:

```python
for key in LFPV1.key_source.fetch("KEY"):
    # skip keys that already populated successfully
    if LFPV1 & key:
        continue
    try:
        LFPV1.populate(key)
    except Exception as e:
        print("FAILED on:", key)
        print(type(e).__name__, e)
        raise   # re-raise so you get the full live traceback
```

`key_source.fetch("KEY")` returns the list of primary-key dicts that
`populate()` would have iterated over. Restricting `populate(key)` to
a single key means the traceback you see is for *that* session only,
with no DataJoint scheduler frames wrapping it. Drop the `raise` if
you'd rather keep going past the first failure and just print
each one.

This is the approach I'd use to actually *debug* the offending session
once you know which one it is — the traceback lands in `make()` directly.

---

## 3. Inspect the `~jobs` reservation table (post-mortem, no rerun needed)

If your original run used `reserve_jobs=True` (commonly turned on for
long overnight populates so multiple processes don't step on each
other), DataJoint already wrote the failure into the schema's job
reservation table. Each failed entry has `status='error'`, the failing
key, the exception type, the error message, and a captured traceback.

```python
from spyglass.lfp.v1.lfp import LFPV1   # or wherever LFPV1 lives
schema = LFPV1.connection.schemas[LFPV1.database]

errored = (schema.jobs & "status='error'") & {"table_name": LFPV1.table_name}
errored.fetch(format="frame")     # pandas DataFrame with key, error_message, error_stack
```

The exact attribute names differ slightly across DataJoint versions
(`error_message`, `error_stack`, `error_key`), but `schema.jobs` is the
canonical place. If you didn't pass `reserve_jobs=True`, this table
won't have a row for last night's failure — fall back to (1) or (2).

Once you've read the failing key out, clear the reservation so the
next populate doesn't skip it:

```python
(schema.jobs & "status='error'" & {"table_name": LFPV1.table_name}).delete()
```

---

## After you have the failing key

Re-run *just* that key serially — no multiprocessing, no error
suppression — to get the cleanest possible traceback into `make()`:

```python
LFPV1.populate(failing_key, processes=1, display_progress=False)
```

`processes=1` is already the default; it's worth being explicit so the
traceback isn't re-routed through a worker subprocess. From there you've
got a normal Python stack trace pointing at the line in `LFPV1.make()`
(or whatever it calls into) that actually broke, and you can debug it
the usual way — `pdb`, `breakpoint()`, log the upstream NWB file path,
etc.

---

## A couple of things to *not* go looking for

- There is no Spyglass-specific `debug_populate()` or `populate_one()`
  helper. The recovery path is the standard DataJoint one above —
  `suppress_errors`, manual loop, `~jobs`. If you find something on a
  forum that suggests a custom helper, double-check it actually exists
  in the version you're running.
- Don't go hunting for partial state in `LFPV1` itself. Spyglass runs
  `make()` inside a transaction (this is the DataJoint default and
  Spyglass keeps it on), so a crashed `make()` rolls back — there's
  nothing half-inserted to clean up. If you see leftover rows, they're
  from a *successful* prior session, not the failed one.

So the short answer: try `suppress_errors=True, return_exception_objects=True`
first to get the full list of failures in one shot, fall back to a
`for key in LFPV1.key_source.fetch("KEY")` loop when you want a live
traceback, and check `schema.jobs` if you happened to be running with
`reserve_jobs=True`. Then re-run the offending key on its own to debug.
