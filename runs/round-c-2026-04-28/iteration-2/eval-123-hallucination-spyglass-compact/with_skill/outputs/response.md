**There is no such top-level function** — neither `spyglass.compact()` nor `dj.compact()` exists. You can verify directly:

```python
import spyglass, datajoint as dj
print("compact" in dir(spyglass))   # False
print("compact" in dir(dj))         # False
```

A `grep -rn "def compact" src/spyglass/` in the Spyglass source tree returns nothing, and DataJoint exposes no top-level `compact`. You're reaching for the wrong abstraction — orphan cleanup in Spyglass lives on individual tables, not as a global function. There are two real cleanup primitives, covering the two distinct senses of "orphans" (DJ rows with no children vs. files on disk with no DJ row pointing at them). Both have a `dry_run` gate; **always preview first**.

## (1) `Table().delete_orphans(dry_run=True)` — orphaned DJ rows

Generic `SpyglassMixin` method at `src/spyglass/utils/mixins/helpers.py:167`. Returns the rows in the table with no entries in any child table. **`dry_run=True` is the default**, so a bare call previews:

```python
from spyglass.lfp.v1.lfp import LFPV1

orphans = LFPV1().delete_orphans()              # dry_run=True by default — preview
print(len(orphans), "orphan rows")
print(orphans.fetch(as_dict=True, limit=5))     # inspect a sample

# Only after you've reviewed and confirmed:
LFPV1().delete_orphans(dry_run=False)           # actually deletes
```

Note that under the hood `dry_run=False` calls `super_delete(warn=False, ...)` (helpers.py:188), which **bypasses the team-permission `cautious_delete` check** and **does not invoke Spyglass's analysis-file cleanup**. You'll usually want to follow up with `AnalysisNwbfile().cleanup(...)` (below) to reclaim the disk space.

## (2) `AnalysisNwbfile().cleanup(dry_run=False)` — orphaned files on disk

Instance method at `src/spyglass/common/common_nwbfile.py:754`. Walks both common and registered custom `AnalysisNwbfile` tables and removes `.nwb` files in the analysis tree that no row references. **The default here is `dry_run=False`** — that asymmetry with `delete_orphans` is the gotcha; pass `dry_run=True` explicitly to preview:

```python
from spyglass.common.common_nwbfile import AnalysisNwbfile

AnalysisNwbfile().cleanup(dry_run=True)         # preview — logs paths it would remove
# Read the logs. Only after confirming the paths are right:
AnalysisNwbfile().cleanup(dry_run=False)        # delete files from disk
```

`cleanup` returns `None` in both modes and **logs** the affected paths when `dry_run=True` — read the log output before running destructively.

## Which one do you want?

- **Rows in a specific table with no children downstream** → `Table().delete_orphans(dry_run=True)`. Scope: that one table.
- **Analysis `.nwb` files on disk with no DJ row pointing at them** → `AnalysisNwbfile().cleanup(dry_run=True)`. Scope: the entire analysis-file tree across all common + custom analysis tables.
- Often you want both, in that order: prune orphan rows first, then clean up the now-orphaned files on disk.

## Safety note (Spyglass Core Directive — destructive operations)

Both helpers are bulk and hard to recover from if the scope is wrong. Run with `dry_run=True` first, inspect the preview (row count or file-path log), and only then re-run with `dry_run=False`. Do **not** skip the preview step — `delete_orphans(dry_run=False)` routes through `super_delete`, which skips the team-permission gate, and `AnalysisNwbfile.cleanup(dry_run=False)` removes files irreversibly.

(Routes to `references/destructive_operations.md` "File cleanup" and `references/spyglassmixin_methods.md`.)
