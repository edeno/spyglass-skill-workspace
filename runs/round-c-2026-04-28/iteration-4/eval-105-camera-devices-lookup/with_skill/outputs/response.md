# Cameras for `j1620210710_.nwb`

I can't read your database from here, so I can't print the actual `camera_name` values for `j1620210710_.nwb` directly. What I *can* give you is the verified schema path and the canonical query — run it against your DB and the rows it returns are the camera IDs you need for DLC.

## Where camera identity lives in Spyglass

Per `skills/spyglass/references/common_tables.md`:

- `CameraDevice` — **PK is `camera_name`**. There is no separate `camera_id` field; `camera_name` *is* the camera identifier the rest of Spyglass uses.
- `TaskEpoch` — PK `(nwb_file_name, epoch)`; per-epoch FK to `CameraDevice` (relationship summary: `TaskEpoch (1:many) → Task, CameraDevice`).
- `VideoFile` — per-session video registry; also carries a camera reference per video file.

So "what camera(s) recorded position for this session" resolves through `TaskEpoch` (camera per epoch) and/or `VideoFile` (camera per video file).

## Query to run

```python
from spyglass.common import TaskEpoch, CameraDevice, VideoFile

nwb_file = "j1620210710_.nwb"

# 1. Per-epoch camera assignment (most common answer to "which camera?"):
print((TaskEpoch & {"nwb_file_name": nwb_file}).fetch(
    "epoch", "task_name", "camera_name", as_dict=True
))

# 2. Distinct cameras across the whole session:
cams = sorted(set((TaskEpoch & {"nwb_file_name": nwb_file}).fetch("camera_name")))
print("cameras for", nwb_file, "->", cams)

# 3. Full hardware metadata for each camera (manufacturer, model,
#    pixel resolution, meters_per_pixel, etc. — useful for DLC):
print((CameraDevice & [{"camera_name": c} for c in cams]).fetch(as_dict=True))

# 4. Cross-check via VideoFile (one row per video; carries camera_name too):
print((VideoFile & {"nwb_file_name": nwb_file}).fetch(
    "epoch", "video_file_num", "camera_name", as_dict=True
))
```

A couple of things to verify in your session before trusting the output (per the skill's evidence expectations and pre-`fetch1` cardinality rule):

- Confirm `camera_name` is the field name on your install: `TaskEpoch.heading` and `VideoFile.heading`. The PK on `CameraDevice` is `camera_name`, and `TaskEpoch` declares a FK to it — but I haven't read the source for *your* exact Spyglass version here, so a quick `.heading` check is worth it.
- If `(TaskEpoch & {"nwb_file_name": nwb_file})` returns 0 rows, ingestion either skipped this session or dropped epochs on a tag-format mismatch (see `references/ingestion.md` "TaskEpoch silently drops epochs"). In that case `VideoFile` is your fallback source for camera assignment.
- If query #2 returns more than one camera and you only want the camera tied to the position epoch you're about to DLC, restrict by `epoch` first (e.g. `TaskEpoch & {"nwb_file_name": nwb_file, "epoch": 2}`) so you don't accidentally feed the wrong camera's intrinsics into DLC.

## What I am NOT going to do

I won't guess at specific camera names for `j1620210710_.nwb` (e.g. "camera_0", "overhead_cam"). Per the skill's "do not invent identifiers" directive, runtime row contents are evidence-backed only via a fetch / `db_graph.py describe`, not from prose. The query above is the verifiable answer — its output, on your DB, is the authoritative camera ID list for downstream DLC.

If you paste the output of query #2 back, I can help map those camera entries to `DLCPoseEstimationSelection` / `DLCProject` — that step needs the camera's pixel resolution and `meters_per_pixel` from `CameraDevice`, which query #3 returns.
