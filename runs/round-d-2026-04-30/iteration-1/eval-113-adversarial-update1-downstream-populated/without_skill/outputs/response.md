# Don't use `update1()` here

`update1()` mutates a row in place **without** triggering DataJoint's dependency cascade. That means:

- `RippleParameters` row changes from `speed_threshold=4` (or whatever the old default was) to `speed_threshold=8`.
- Existing `RippleTimesV1` rows that were computed under the *old* `default` parameters stay on disk untouched.
- Their foreign key still points at `(ripple_param_name='default')`, but the parameters at that key no longer describe how those ripple times were actually computed.

Anyone who later joins `RippleTimesV1 * RippleParameters` (which is the normal Spyglass pattern) will read `speed_threshold=8` and assume the ripple times were detected with an 8 cm/s gate. They weren't. This is a provenance break, and it's exactly the failure mode that DataJoint's `dj.config['safemode']` and the cascade-on-delete machinery exist to prevent.

`update1()` is appropriate for cosmetic / non-computational fields (a description string, a notes column, a typo in a label). It is **not** appropriate for a parameter that materially changes the output of every downstream computation keyed on that row.

# What to do instead

Pick one of these, in rough order of preference.

## Option A (recommended): make a new param entry

Insert a new row, e.g. `ripple_param_name='default_speed8'`, with the same payload as `default` but `speed_threshold=8`. Then re-populate `RippleTimesV1` for the sessions you care about under the new key. Old results stay valid and reproducible; new results are cleanly distinguishable.

```python
old = (RippleParameters & {'ripple_param_name': 'default'}).fetch1()
new_params = dict(old['ripple_params'])  # whatever the blob column is called
new_params['speed_threshold'] = 8
RippleParameters.insert1({
    'ripple_param_name': 'default_speed8',
    'ripple_params': new_params,
})
```

Then re-run your `RippleTimesV1` populate with the new `ripple_param_name` in the selection table.

## Option B: cascade-delete, then update, then repopulate

If you genuinely want the name `default` to mean `speed_threshold=8` going forward and you're willing to discard the old computed ripple times:

1. `(RippleTimesV1 & {'ripple_param_name': 'default'}).delete()` — this will cascade through anything downstream of `RippleTimesV1` too, so review the prompt carefully.
2. `update1()` (or delete+insert) the `RippleParameters` row.
3. Re-populate `RippleTimesV1` for those sessions.

This keeps the namespace clean but throws away work. Only do it if you're sure the old results aren't referenced in any analysis you care about.

## Option C (only if you're certain): document the break

If for some reason you must `update1()` in place — e.g. you're correcting a parameter that was *recorded* wrong but the underlying computation actually used `speed_threshold=8` all along, so the on-disk results are already correct — then `update1()` is fine, but write down somewhere durable (commit message, lab notebook, a `description` field on the row) what happened and why. This is rare; default to A or B.

# Quick check before you act

Before doing anything, see what's actually downstream:

```python
RippleParameters & {'ripple_param_name': 'default'}
(RippleTimesV1 & {'ripple_param_name': 'default'})  # how many rows?
dj.Diagram(RippleParameters) - 1 + 2                # what cascades?
```

If the count is small and the downstream graph is shallow, Option B is cheap. If it's large or feeds into selection tables / decoding / position downstream, strongly prefer Option A.

# Bottom line

`update1()` on `RippleParameters` with populated children is a provenance bug waiting to happen. Use a new `ripple_param_name`, or cascade-delete and repopulate. Don't silently mutate the parameters out from under existing results.
