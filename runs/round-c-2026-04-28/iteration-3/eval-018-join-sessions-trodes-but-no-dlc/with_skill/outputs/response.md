# Sessions with Trodes position but no DLC

## TL;DR — the portable answer

```python
from spyglass.position.v1 import TrodesPosV1, DLCPosV1

trodes_sessions = set(TrodesPosV1.fetch("nwb_file_name"))
dlc_sessions    = set(DLCPosV1.fetch("nwb_file_name"))

needs_dlc = trodes_sessions - dlc_sessions
print(f"{len(needs_dlc)} session(s) still need DLC tracking:")
for f in sorted(needs_dlc):
    print(" ", f)
```

That is the form I recommend — it's legible, it's robust to the schema collisions described below, and it deduplicates `nwb_file_name` automatically (a single session can have many Trodes rows: one per interval × params combination).

## Why not the obvious DataJoint antijoin?

The DataJoint-native shape would be:

```python
# DOES NOT WORK — raises at query-build time
(TrodesPosV1 - DLCPosV1).fetch("nwb_file_name")
```

This **raises** before it ever hits the database:

```
DataJointError: Cannot join query expressions on dependent attribute 'analysis_file_name'
```

### Source check — why the collision exists

Both tables inherit `-> AnalysisNwbfile` and the same three NWB object-ID columns as **secondary** attributes:

`src/spyglass/position/v1/position_trodes_position.py:178-190`
```python
class TrodesPosV1(SpyglassMixin, dj.Computed):
    definition = """
    -> TrodesPosSelection
    ---
    -> AnalysisNwbfile
    position_object_id    : varchar(80)
    orientation_object_id : varchar(80)
    velocity_object_id    : varchar(80)
    """
```

`src/spyglass/position/v1/position_dlc_selection.py:39-53`
```python
class DLCPosV1(SpyglassMixin, dj.Computed):
    definition = """
    -> DLCPosSelection
    ---
    -> AnalysisNwbfile
    position_object_id      : varchar(80)
    orientation_object_id   : varchar(80)
    velocity_object_id      : varchar(80)
    pose_eval_result        : longblob
    """
```

`analysis_file_name` (the FK from `-> AnalysisNwbfile`) plus `position_object_id`, `orientation_object_id`, and `velocity_object_id` are secondary on **both** sides. The two FK paths to `AnalysisNwbfile` are independent (one through `TrodesPosSelection → RawPosition`, the other through `DLCPosSelection → DLCCentroid/DLCOrientation`), so DataJoint refuses to assume the like-named columns mean the same thing. The same dependent-attribute refusal that breaks `*` also breaks `-` (set-difference / antijoin) — see Common Mistake #9 in the skill's `common_mistakes.md`.

## Working antijoin form (if you really want it)

If you specifically want the DataJoint-native antijoin, project both sides down to PK only first:

```python
# Both .proj() with no args drop all secondaries, leaving only PK fields.
needs_dlc = set((TrodesPosV1.proj() - DLCPosV1.proj()).fetch("nwb_file_name"))
```

`.proj()` with no args reduces each side to its primary key. `nwb_file_name` is in the PK on both sides (it propagates down from `Session` through `RawPosition` / DLC pose-estimation chains), so the remaining shared attribute is a primary on both tables — no dependent-attribute collision, and the antijoin succeeds.

A few notes:

- This works, but it's strictly more fragile than `set(...) - set(...)`. If a future Spyglass change adds a secondary collision through a different FK path, the `set(...) - set(...)` form is unaffected; the `proj() - proj()` form would need to be re-audited.
- The PKs of `TrodesPosV1` and `DLCPosV1` differ a lot below `nwb_file_name` (params, intervals, DLC model identifiers). The antijoin matches on whatever attributes happen to be in *both* PKs — `nwb_file_name`, and possibly `epoch` / `interval_list_name` depending on how the hierarchies line up. That can give you a per-(session, interval) answer rather than a per-session one. If you want **session-level** "needs DLC", deduplicate first:

  ```python
  trodes_sess = set(TrodesPosV1.fetch("nwb_file_name"))
  dlc_sess    = set(DLCPosV1.fetch("nwb_file_name"))
  needs_dlc   = trodes_sess - dlc_sess
  ```

  which is just the TL;DR form again.

## Want a richer report?

If you also want, per session, the count of Trodes rows / intervals that don't have a DLC counterpart:

```python
import pandas as pd
from spyglass.position.v1 import TrodesPosV1, DLCPosV1

trodes_df = pd.DataFrame(TrodesPosV1.fetch("nwb_file_name", as_dict=True))
dlc_files = set(DLCPosV1.fetch("nwb_file_name"))

missing = (trodes_df[~trodes_df["nwb_file_name"].isin(dlc_files)]
           .groupby("nwb_file_name").size()
           .rename("trodes_rows")
           .reset_index()
           .sort_values("trodes_rows", ascending=False))
print(missing.to_string(index=False))
```

## Sanity checks worth running

Before treating "needs DLC" as a to-do list, confirm:

1. **DLC really hasn't run** vs. it ran but failed silently — check whether there are `DLCPoseEstimationSelection` rows for the same sessions that didn't make it through to `DLCPosV1`. A populated selection without a populated `DLCPosV1` usually means a make-time error, not "DLC was never attempted."
2. **The session is actually Trodes-tracked** — some sessions only have imported pose (`ImportedPose`) and never had Trodes/DLC populated; those will show up as "Trodes-only" only if Trodes was also run, which it usually was for any session with LED tracking.
3. **`nwb_file_name`-level granularity is what you want.** A session can be in `DLCPosV1` for one interval but not another. If your real question is "which session × interval combinations need DLC", join through `IntervalList` instead and project on `(nwb_file_name, interval_list_name)`.

## References

- `common_mistakes.md` § 9 — `*` and `-` refuse to join on dependent attributes; same rule fires for both.
- `src/spyglass/position/v1/position_trodes_position.py:178-190` — `TrodesPosV1` definition.
- `src/spyglass/position/v1/position_dlc_selection.py:39-53` — `DLCPosV1` definition.
