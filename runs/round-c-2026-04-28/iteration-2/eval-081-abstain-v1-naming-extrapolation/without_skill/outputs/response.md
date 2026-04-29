# `SpikeSortingV1.populate(key)` vs `SpikeSortingV1().populate(key)`

Short answer: in practice, **both work** — DataJoint's `populate` is defined
on the table class but is also accessible on instances, because DataJoint
table classes return a fresh instance for most operations and `populate`
doesn't depend on per-instance state. So either form will run the sort.

The convention you'll see most often in the Spyglass tutorials and the
DataJoint docs themselves is the **instance form**:

```python
SpikeSortingV1().populate(key)
```

That's what I'd recommend writing, for two reasons:

1. **Consistency with DataJoint idioms.** DataJoint's own examples almost
   always instantiate the table before calling `.populate()`, `.fetch()`,
   `.insert1()`, etc. Even when the class-form works, the instance-form
   is the documented style.
2. **Some methods only exist on instances.** `populate` happens to work
   either way, but `fetch`, `&` (restriction), `proj`, etc. are
   instance-bound. Mixing class-form and instance-form in the same
   script reads inconsistently. Pick one; instance-form is the safer
   default.

So:

```python
from spyglass.spikesorting.v1 import SpikeSortingV1

# after you've inserted into SpikeSortingSelection:
SpikeSortingV1().populate(key)
```

That will pull the matching `SpikeSortingSelection` row(s), run the
configured sorter (MountainSort / Kilosort / etc., whatever's encoded in
the selection key), and write results into the `SpikeSortingV1` table.

A few extra notes that usually trip people up at this step:

- `populate(key)` is restricted to keys that match — if your `key` doesn't
  uniquely identify the selection row, it'll silently populate every row
  that matches the partial key. Use `populate(key, display_progress=True)`
  if you want a progress bar, and pass a fully-specified primary key to
  avoid surprises.
- If the sort fails partway, the row is left in an incomplete state.
  `(SpikeSortingV1 & key).delete()` and re-run.
- `populate` is the right call here; you do **not** need to call any
  `make()` method directly — DataJoint does that for you.

In short: `SpikeSortingV1().populate(key)` is the form to write, but if
you've already typed `SpikeSortingV1.populate(key)` in a script it'll
still work.
