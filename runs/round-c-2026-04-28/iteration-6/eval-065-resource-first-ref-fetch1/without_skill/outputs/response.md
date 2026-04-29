# Which reference file would I open first?

Honest caveat first: I don't have the Spyglass skill loaded right now,
so I'm reasoning about what a well-organized Spyglass skill *likely*
contains rather than reading its actual table of contents. Based on
the conventions I've seen in similar skills (and on the shape of the
error), here's my best guess at the right first stop.

## First stop: `common_mistakes.md`

The error

```
DataJointError: fetch1 should only be called on one tuple,
but 47 were returned
```

is the canonical "I built a restriction that didn't narrow far enough,
then asked for a single row" footgun. It's a cardinality mismatch, not
a schema bug, not a populate bug, not an NWB bug — so it belongs in
the bucket of recurring beginner/intermediate traps.

A skill with a `references/` directory almost always has a file called
something like `common_mistakes.md`, `pitfalls.md`, or
`troubleshooting.md` whose entire job is to catalogue exactly this
class of error. `fetch1` cardinality is usually right at the top of
that list, because it's the single most common DataJoint runtime
error people hit. So: open `common_mistakes.md` first and look for
the entry on `fetch1` / under-restricted queries.

The diagnostic pattern that file almost certainly recommends is:

```python
print(len(restricted_table))  # check cardinality before fetch1
restricted_table  # or just display it in a notebook to see the rows
```

If `len(...)` is anything other than 1, your restriction is wrong and
no amount of fiddling with `fetch1` arguments will fix it. The fix is
to add the missing key parts (often `nwb_file_name` plus an
analysis-specific key like `interval_list_name`,
`sort_interval_name`, `lfp_band_sampling_rate`, etc.) until you get
exactly one row, then call `fetch1`.

## Likely follow-up: `datajoint_api.md`

If `common_mistakes.md` doesn't have what I need, the next file I'd
reach for is whatever covers the DataJoint fetch surface itself —
something like `datajoint_api.md` or `fetch_patterns.md`. That's
where the broader mechanics live: `fetch` vs `fetch1`, the
`as_dict=True` flag, `KEY` projection, heading/primary-key semantics,
and when to use `(table & restriction).fetch1("KEY")` to get a
restriction-shaped key dict instead of a row dict. Useful if the real
question turns out to be "how do I structure the restriction" rather
than "what does this error mean."

## One-line rationale

Cardinality errors are the page-one footgun, so the
recurring-mistakes file is the highest-yield first read; the
DataJoint API reference is the natural follow-up if you need the
fetch/fetch1/restriction mechanics in more depth.
