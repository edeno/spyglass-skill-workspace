I want to push back gently here, because I don't think the function you're describing exists in the form you've remembered it.

## There is no such top-level function

To my knowledge:

- **`spyglass.compact()`** — does not exist. Spyglass is a DataJoint-based pipeline package; it doesn't expose a top-level `compact()` entry point for cleanup. You can verify this in your own session:

  ```python
  import spyglass
  print([x for x in dir(spyglass) if "compact" in x.lower()])   # likely []
  ```

- **`dj.compact()`** — does not exist in DataJoint either. DataJoint's public surface (`dj.Table`, `dj.Schema`, `dj.config`, `dj.U`, etc.) has no `compact` function. Same check:

  ```python
  import datajoint as dj
  print([x for x in dir(dj) if "compact" in x.lower()])         # likely []
  ```

If either of those prints something non-empty in your environment, please share it and I'll revise — but I'd be surprised. My best guess is that you're remembering either a blog post, a function from a different package, or conflating two different things you read.

## What you probably actually want

"Orphaned analysis files" is ambiguous in a Spyglass/DataJoint context — it could mean two different things, and they have different fixes:

### (1) Orphaned table rows (DJ entries with no downstream children)

Spyglass tables that inherit from `SpyglassMixin` expose a `delete_orphans()` method (defined in `spyglass.utils.mixins.helpers`). It returns the rows in `self` that have no entries in any child table. The signature, from the source:

```python
def delete_orphans(self, dry_run: bool = True, **kwargs):
    ...
```

`dry_run=True` is the **default** — a bare call previews what would be removed without touching anything. Only flip the flag once you've inspected the preview:

```python
from spyglass.lfp.v1.lfp import LFPV1   # or whichever table you care about
orphans = LFPV1().delete_orphans()      # dry_run=True by default → preview
print(orphans)                           # inspect carefully
LFPV1().delete_orphans(dry_run=False)   # only after review
```

### (2) Orphaned `.nwb` files on disk (files with no DJ row pointing at them)

For analysis NWB files specifically, there's `AnalysisNwbfile().cleanup()` in `spyglass.common.common_nwbfile`. This walks the analysis-file store and removes files that no `AnalysisNwbfile` row references:

```python
from spyglass.common.common_nwbfile import AnalysisNwbfile
AnalysisNwbfile().cleanup(dry_run=True)    # preview first
AnalysisNwbfile().cleanup(dry_run=False)   # delete after review
```

Heads up: the default of `dry_run` on `AnalysisNwbfile.cleanup` is **not** the same as on `delete_orphans` — confirm in your installed version before relying on a bare call. Always pass `dry_run=True` explicitly the first time.

## Safety note

Both of these are destructive bulk operations, and they're hard to undo if the wrong scope gets selected. Two rules I'd hold to:

1. **Always run with `dry_run=True` first** and read the output. Don't trust your mental model of which rows or files will be affected; let the preview tell you.
2. **Never run a fresh-from-memory `dry_run=False` call** because somebody (or some doc) said it was the "right cleanup function." The fabricated `spyglass.compact()` you remembered is a good example of why — if it had existed and you'd run it on faith, you might have wiped state you wanted to keep.

If you can point me at where you read about `spyglass.compact()` / `dj.compact()`, I'd like to see it — there's a small chance it's a helper in a downstream lab fork I don't know about, but the much more likely explanation is misremembered API.
