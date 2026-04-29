# Don't edit `DLCPosV1` — and you don't have to

Pushing back on the framing here. There are three independent reasons the edit you're describing is the wrong move, and a much smaller answer that gives you what you actually want.

## Why editing `DLCPosV1` is off the table

1. **The skill's Core Directives forbid it.** "Do not edit the installed Spyglass package. Edits to `src/spyglass/...` desync the in-DB schema from what other labs run, and `pip install -e .` silently reverts them." `DLCPosV1` is defined in `spyglass.position.v1` — shared lab code, not yours.

2. **MySQL won't let you anyway** (in most accounts). `position` is one of the lab-shared schemas in `SHARED_MODULES` (`spyglass/utils/database_settings.py`). Writes/ALTERs there require `dj_user` or `dj_admin`. The common `dj_collab` role (default for new lab members) gets a permission error at `dj.schema(...)` / `Table.alter()` time. Even with `dj_admin`, altering a shared table changes the schema for everyone in the DB, which is a coordination event, not a personal edit.

3. **A column on `DLCPosV1` is the wrong shape for bodyparts.** Bodyparts are a *one-to-many* relationship to a single `DLCPosV1` row — a centroid/orientation result is computed from a *cohort* of bodyparts. A scalar column can't hold that without packing them into a varchar/blob, which kills queryability.

## You also don't need to — the data is already there

The bodyparts that fed a given `DLCPosV1` row are already recorded upstream in the existing schema. The DLC pipeline flow (from `position_dlc_v1_pipeline.md`) is:

```text
DLCPoseEstimation → DLCPoseEstimation.BodyPart        (per-bodypart raw pose)
                  → DLCSmoothInterp                    (per-bodypart smoothed)
                  → DLCSmoothInterpCohort              (combines bodyparts)
                  → DLCCentroid / DLCOrientation
                  → DLCPosV1
```

`DLCSmoothInterpCohort` is the table that names the bodypart set used for a given `DLCPosV1`, and `DLCPoseEstimation.BodyPart` is the part table listing each bodypart for a pose-estimation run. To get bodypart names alongside a `DLCPosV1` key, just join — no schema change needed:

```python
from spyglass.position.v1 import (
    DLCPosV1, DLCSmoothInterpCohort, DLCPoseEstimation,
)

# All bodyparts that fed this DLCPosV1 row (via the cohort selection)
bodyparts = (DLCSmoothInterpCohort.BodyPart & dlc_pos_key).fetch("bodypart")

# Or, the bodyparts available from the upstream pose estimation
bodyparts = (DLCPoseEstimation.BodyPart & dlc_pos_key).fetch("bodypart")
```

Verify the exact part-table attribute name on your install with `DLCSmoothInterpCohort.BodyPart.heading` before relying on it — I haven't run that against source line-by-line.

## If you genuinely need a bodypart annotation attached to `DLCPosV1`

The framework-correct move is a **separate custom table in your own schema** that FK-refs `DLCPosV1`. This is exactly the "Single Custom Table (Not a Pipeline)" pattern from `custom_pipeline_authoring.md`. It is small — one table, no `make()`, no merge plumbing — and it cleanly handles the one-to-many shape:

```python
import datajoint as dj
from spyglass.position.v1 import DLCPosV1
from spyglass.utils import SpyglassMixin

# Schema name MUST start with your dj.config["database.user"] prefix —
# e.g. "edeno_dlc_annotations". Anything else (including a "spyglass_"
# prefix) raises a MySQL permission error at dj.schema() time.
schema = dj.schema("yourusername_dlc_annotations")

@schema
class DLCPosV1BodyParts(SpyglassMixin, dj.Manual):
    """Bodypart names associated with each DLCPosV1 row."""

    definition = """
    -> DLCPosV1
    bodypart: varchar(64)
    """
```

This gives you what a "column" would have given you (queryable bodypart names keyed to `DLCPosV1`), but without:

- editing installed Spyglass (Core Directive),
- needing write perms on the `position` schema (you only need write on your own `<user>_*` prefix),
- breaking the one-to-many cardinality.

You said you don't want to deal with a whole new table — I hear that, but the alternative isn't "one column on `DLCPosV1`," it's "edit shared lab code, possibly fail at `pip install -e .` time, and break everyone else's pipeline." The single FK-ref'd `dj.Manual` above is genuinely the minimum.

## Recommendation

In order of preference:

1. **Don't add anything.** Use `DLCSmoothInterpCohort.BodyPart` (or `DLCPoseEstimation.BodyPart`) — the bodypart names are already in the schema, joinable from any `DLCPosV1` key.
2. **If you need annotation/labels beyond what's upstream**, add the small `DLCPosV1BodyParts` `dj.Manual` in your own schema, as above.
3. **Do not** alter `DLCPosV1`'s definition. If you find yourself wanting to, that's a signal to split into a downstream table, not to mutate a shared one.

If your real need is something I've misread (e.g., you want a *single* canonical bodypart label per `DLCPosV1` row for plotting, not the full set), say more and I'll narrow the recommendation — but the editing-the-installed-table path is closed regardless.
