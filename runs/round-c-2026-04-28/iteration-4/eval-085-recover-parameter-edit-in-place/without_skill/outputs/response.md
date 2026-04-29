# Recovering from an in-place edit of `RippleParameters`

## What actually happened

DataJoint identifies a row by its **primary key**, not by its content.
`RippleParameters` keys on `ripple_param_name`, so when you bumped
`zscore_threshold` from 2 → 3 *in place* on `Kay_ripple_detection_v2`,
the primary key was unchanged. Every downstream row in `RippleTimesV1`
(and anything downstream of *that*) still points at
`ripple_param_name="Kay_ripple_detection_v2"`, but the parameter blob
they were computed against no longer exists. The provenance is broken
silently — DataJoint will not tell you the downstream rows are stale,
because from its point of view nothing was deleted.

This is exactly the failure mode the "params are content-addressed by
name, never edit in place" convention is designed to prevent.

## Two recovery paths

Pick one. Path A is the clean fix; Path B is the escape hatch if you
*also* want to keep the `threshold=2` results around.

---

### Path A — accept the new value, recompute downstream (recommended)

You've already mutated the row, and you've decided `threshold=3` is
what you want going forward. The only correct state is "downstream
matches current parameters", so delete and repopulate.

```python
from spyglass.ripple.v1.ripple import RippleTimesV1
# (or wherever your downstream RippleTimesV1 lives)

# 1. Find the affected downstream rows.
stale = RippleTimesV1 & {"ripple_param_name": "Kay_ripple_detection_v2"}
print(len(stale))           # sanity-check the count
print(stale.fetch("KEY"))   # eyeball the keys before nuking

# 2. Cascade-delete them. This will also remove anything downstream of
#    RippleTimesV1 that depends on these keys (e.g. merge-table parts,
#    decoding rows that consumed these ripple times). DataJoint will
#    list everything it is about to drop and ask you to confirm —
#    READ THAT LIST before typing 'yes'.
(RippleTimesV1 & {"ripple_param_name": "Kay_ripple_detection_v2"}).delete()

# 3. Repopulate. The selection table (RippleTimesV1Selection or the
#    equivalent in your version) still has the entries; populate()
#    will recompute against the new threshold=3.
RippleTimesV1.populate(reserve_jobs=True, display_progress=True)
```

Things to verify before step 2:

- **What is downstream of `RippleTimesV1`?** Run
  `dj.Diagram(RippleTimesV1) + 2` in a notebook, or
  `RippleTimesV1.descendants()`, so you know what the cascade will
  take with it. If any of those descendants are expensive (decoding
  runs, paper exports, figure caches), budget the recompute time
  before you delete.
- **Are any of those rows in a merge table?** If `RippleTimesV1` rows
  feed a merge table (e.g. `RippleTimesOutput`), the cascade also
  removes the merge entries, which can break references in any
  analysis notebook that fetched them by merge UUID. You will need to
  re-run those fetches after repopulating.
- **Are you the only writer?** If a collaborator's job is mid-populate
  on these keys, coordinate first.

After repopulate, confirm:

```python
# Spot-check: the new ripple times should be a *subset* (or at least
# different) compared to what threshold=2 would produce, since 3σ is
# stricter.
times = (RippleTimesV1 & {"ripple_param_name": "Kay_ripple_detection_v2"}
         ).fetch1("ripple_times")
print(len(times))
```

---

### Path B — preserve both versions

If you actually want `threshold=2` results *and* `threshold=3` results
side by side (e.g. for a methods comparison), the in-place edit was
the wrong move. Reverse it:

1. **Restore the original parameter row** under its original name.
   Insert with `skip_duplicates=False` after deleting the mutated row,
   or just `update1` it back to `threshold=2`:

   ```python
   RippleParameters().update1({
       "ripple_param_name": "Kay_ripple_detection_v2",
       "ripple_param_dict": {..., "zscore_threshold": 2, ...},
   })
   ```

   Now the existing `RippleTimesV1` rows are no longer stale — they
   match the parameters again.

2. **Insert a *new*, differently named parameter row** for the 3σ
   variant:

   ```python
   RippleParameters().insert1({
       "ripple_param_name": "Kay_ripple_detection_v2_z3",
       "ripple_param_dict": {..., "zscore_threshold": 3, ...},
   })
   ```

3. Add the new selection entries (`RippleTimesV1Selection` or
   equivalent) keyed on `Kay_ripple_detection_v2_z3` and
   `populate()`. Both versions now coexist.

This only works if you still have the original parameter dict
recorded somewhere — git history of an analysis notebook, a paper
draft, a previous `fetch1()` printout, etc. If you don't, you have to
go with Path A.

---

## How to avoid this next time

Treat `*Parameters` rows as **immutable, content-addressed by name**:

- Never `update1` an existing param row whose key has been used
  downstream.
- New parameter values → new `*_param_name` (e.g. `..._z2`, `..._z3`,
  or a hash suffix).
- If you really do need to retire an old parameter set, cascade-delete
  it explicitly so the staleness is loud, not silent.

Some labs enforce this with a pre-insert check that hashes the param
dict into the name; if your group does this often, it's worth adding.

## Quick decision guide

- **Just want correctness, don't care about the old results** → Path A.
- **Want to compare threshold=2 vs threshold=3** → Path B (and you
  need the original param dict).
- **Don't know what's downstream** → run `dj.Diagram(RippleTimesV1) + 2`
  *before* deleting anything.
