# Camera lookup for `j1620210710_.nwb`

To find the camera(s) that recorded position for `j1620210710_.nwb` and get their IDs for DLC processing, you need to query Spyglass's `CameraDevice` table joined with the session's video files. Here's how:

## The lookup

```python
import datajoint as dj
from spyglass.common import Nwbfile, VideoFile, CameraDevice
from spyglass.common.common_behav import RawPosition

nwb_file_name = "j1620210710_.nwb"

# Option 1: Cameras associated via VideoFile (most direct for DLC)
cameras_via_video = (VideoFile & {"nwb_file_name": nwb_file_name}) * CameraDevice
print(cameras_via_video.fetch("camera_id", "camera_name", "epoch", as_dict=True))

# Option 2: Cameras listed on the session itself (Session.DataAcquisitionDevice / Session-level link)
# The link table varies slightly across Spyglass versions; in current main it's:
session_cameras = (Session & {"nwb_file_name": nwb_file_name}) * CameraDevice
print(session_cameras.fetch("camera_id", "camera_name", as_dict=True))
```

`VideoFile` is the table you want for DLC: it has one row per (nwb_file, epoch, video_file_num) and joins to `CameraDevice` via `camera_name`. That gives you the per-epoch camera assignment, which is what `DLCProjectCreator` / `DLCPoseEstimation` will ask for.

## What the IDs actually are

- `camera_id` is the primary key on `CameraDevice` — an integer assigned at insert time, unique per camera in your lab's database. This is the value you pass into the DLC pipeline (e.g. `DLCModelInput`, `DLCPoseEstimationSelection`).
- `camera_name` is the human-readable name (e.g. `"HomeBox_camera"`, `"SleepBox_camera"`) and is what the NWB file actually stores; Spyglass resolves it to `camera_id` on ingest.

## What I cannot tell you from here

I do not have access to your DataJoint database, so **I cannot return the specific `camera_id` value(s) for `j1620210710_.nwb`** — that's lab-specific and depends on what was inserted from this NWB's `/general/devices` group. The filename prefix `j16` suggests this is from the Frank lab's J16 rat, which typically has either one overhead camera per epoch or separate home-box / sleep-box / track cameras across epochs, but you need to run the query above to get the actual IDs.

## Quick sanity checks before handing IDs to DLC

1. **Confirm the file is ingested**: `Nwbfile & {"nwb_file_name": "j1620210710_.nwb"}` should return one row.
2. **Check epoch coverage**: `VideoFile & {"nwb_file_name": ...}` should have one row per behavioral epoch with video. If epochs are missing, the NWB may not have populated `processing/video_files` correctly and DLC won't see them.
3. **Verify camera metadata is non-null**: `CameraDevice` rows for those `camera_name`s should have `meters_per_pixel`, `lens`, etc. populated — DLC project creation will warn (or some downstream steps fail) if these are missing.
4. **Watch for multiple cameras per epoch**: if a session used two cameras simultaneously, you'll get multiple rows for the same epoch with different `camera_id`s; pick the one matching the behavior you're tracking.

Run the first query above against your database and you'll have the camera IDs you need.
