# Should you monkey-patch `LFPV1.make()` at runtime?

Short answer: **don't**. You can technically do it (Python lets you reassign
methods on classes at runtime), but for a Spyglass / DataJoint pipeline this is
the wrong tool, and it will bite you. Below is why, and what to do instead.

## Why monkey-patching `LFPV1.make` is a bad idea here

1. **DataJoint couples `make()` to the table's `definition`.** `LFPV1` is a
   `dj.Computed` table whose `definition` string declares its primary key,
   secondary attributes, and foreign-key references (e.g. to
   `AnalysisNwbfile`). The framework's contract is that `make(key)` computes
   *exactly* the row described by `definition` and `self.insert1(...)`s it.
   If your patched `make()` writes an extra preview file or tries to insert
   extra columns, one of two things happens:
   - the insert fails because the columns don't exist in the live schema, or
   - the insert succeeds with the original columns but your "extra" preview is
     an orphan on disk — DataJoint has no record of it, no foreign key to it,
     and no way to clean it up on cascade delete. That's exactly the kind of
     dangling artifact Spyglass's `AnalysisNwbfile` accounting is designed to
     prevent.

2. **Runtime patches don't persist and don't share.** A monkey-patch in a
   notebook only lives in that kernel.
   - `LFPV1.populate()` run from a different shell, a cron job, a Slurm
     worker, or a colleague's notebook will silently use the original
     unpatched `make()`. Half your rows will have previews, half won't, and
     there's no record of which is which.
   - Parallel populates (`reserve_jobs=True`, multi-process) almost always
     spawn worker processes that re-import the module fresh. They will not
     see your patch.
   - When you restart the kernel, the patch is gone. Anyone reading your
     notebook later has no idea the live code path was different from what
     the source on disk says.

3. **The schema is shared across the lab.** `spyglass.lfp.v1.LFPV1` is the
   *same Python class object* used by every other person in the lab and every
   downstream table that joins against `LFPV1`. Modifying its `make` (or any
   other method) from your notebook is global mutable state inside a shared
   library — exactly the situation where a stray import order in someone
   else's code can trigger your patch, or where your patch silently disagrees
   with what `git blame` on `lfp.py` shows.

4. **You lose provenance.** One of the central reasons to use DataJoint /
   Spyglass at all is that every artifact has a row, every row has a
   make-time and a key, and the dependency graph reflects what actually
   happened. A monkey-patch that writes side files breaks that contract: the
   preview isn't queryable, isn't restrictable, isn't part of `LFPV1 *
   downstream`, and won't show up in DANDI/Kachery exports.

## What to do instead: a new downstream `dj.Computed` table

If your goal is "I want a downsampled preview alongside each `LFPV1` row,"
the idiomatic Spyglass shape is a new **downstream table** in *your own*
schema module that depends on `LFPV1`. The preview becomes a real,
first-class artifact with its own `make()`, its own `AnalysisNwbfile` entry,
and its own place in the dependency graph.

Sketch:

```python
# my_lab/schema/lfp_previews.py
import datajoint as dj
from spyglass.lfp.v1.lfp import LFPV1
from spyglass.common.common_nwbfile import AnalysisNwbfile
from spyglass.utils import SpyglassMixin

schema = dj.schema("testuser_lfp_previews")


@schema
class LFPPreview(SpyglassMixin, dj.Computed):
    definition = """
    -> LFPV1
    preview_downsample_factor : int
    ---
    -> AnalysisNwbfile
    preview_object_id : varchar(40)
    """

    def make(self, key):
        # 1. fetch the source LFP from LFPV1 using `key`
        # 2. downsample by `preview_downsample_factor`
        # 3. create a new AnalysisNwbfile, write the downsampled series,
        #    capture its object_id
        # 4. self.insert1({**key, "preview_downsample_factor": ...,
        #                  "analysis_file_name": ...,
        #                  "preview_object_id": ...})
        ...
```

Why this is the right shape:

- `SpyglassMixin` is listed first in the MRO so Spyglass's mixin behavior
  (export tracking, cascade delete hooks, etc.) takes precedence over
  DataJoint defaults.
- `-> LFPV1` makes the preview a strict descendant: it can only exist for
  rows that already exist in `LFPV1`, and it cascades correctly on delete.
- `-> AnalysisNwbfile` plus a stored `object_id` keeps the preview file
  inside Spyglass's file-accounting system — it will be tracked, exportable,
  and cleanable.
- You can run `LFPPreview.populate()` as a normal pipeline step. Workers,
  cron jobs, and lab members all see the same definition.
- Querying becomes natural: `LFPV1 * LFPPreview & {"nwb_file_name": "..."}`.

If you don't want every `LFPV1` row to have a preview, add a "selection"
table (`LFPPreviewSelection`) upstream of `LFPPreview` where you decide which
keys to compute. That's the standard Spyglass selection / computed pattern.

## What if you actually want to change `LFPV1` itself?

If your real intent is "the canonical `LFPV1.make()` should change for
everyone" — e.g. you've found a bug, or you think every preview should be a
core part of `LFPV1`'s output — that is a **PR upstream to
LorenFrankLab/spyglass**, not a runtime patch. Open an issue describing the
behavior change, then submit a PR that updates the `definition` and `make()`
together, with a migration path for existing rows. That's the only
legitimate way to alter `LFPV1`'s own behavior, and it's a categorically
different action from a notebook monkey-patch — don't conflate the two.

## Summary

- No, don't monkey-patch `LFPV1.make` at runtime — it breaks the
  `definition`/`make` contract, doesn't persist across kernels or workers,
  and silently diverges from what the rest of the lab is running.
- Do create a new `dj.Computed` **downstream table** in your own schema that
  consumes `LFPV1` and produces the downsampled preview as its own artifact,
  with `SpyglassMixin` first in the MRO and an `-> AnalysisNwbfile` reference
  for the preview file.
- If you really want to change `LFPV1` for everyone, open an upstream PR.
