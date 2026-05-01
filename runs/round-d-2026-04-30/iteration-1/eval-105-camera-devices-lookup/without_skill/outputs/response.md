# Finding camera IDs for `j1620210710_.nwb`

I can't fetch the answer for you (I don't have DB access in this session), but here's exactly the query to run. The cameras that recorded position for a session live in two places in Spyglass: `TaskEpoch` (which has a `camera_names` blob listing the cameras associated with each epoch) and `VideoFile` (which records the actual video files registered against each `TaskEpoch`, one row per camera per epoch). Both reference `CameraDevice`, where the `camera_id` you need for DLC actually lives.

## Quickest answer — list cameras and their IDs for that NWB file

```python
import datajoint as dj
from spyglass.common import VideoFile, CameraDevice, TaskEpoch

nwb = "j1620210710_.nwb"

# All camera_names that show up in VideoFile entries for this session,
# joined to CameraDevice so you also get camera_id (what DLC config wants).
cams = (
    (VideoFile & {"nwb_file_name": nwb})
    * CameraDevice
).fetch(
    "epoch", "video_file_num", "camera_name", "camera_id",
    as_dict=True,
)
for row in cams:
    print(row)
```

That gives you, per epoch, the `camera_name` recorded in the NWB ImageSeries device and the corresponding integer `camera_id` from `CameraDevice` — which is the field DLC configs key on.

## If you want just the unique camera IDs

```python
unique_ids = sorted({
    r["camera_id"]
    for r in cams
})
print(unique_ids)
```

## Cross-check via `TaskEpoch.camera_names`

`TaskEpoch` stores a `camera_names` blob per epoch (the list of cameras associated with that epoch, populated from the NWB task metadata). Useful if you want to confirm which epochs were position-tracked vs. e.g. sleep box without a camera:

```python
TaskEpoch & {"nwb_file_name": nwb}
# inspect the `camera_names` and `camera_id` (single-camera FK) columns per epoch
```

## Why this is the right table to look at

In the Spyglass schema (`/spyglass/common/common_behav.py` and `/spyglass/common/common_device.py`):

- `VideoFile` is `-> TaskEpoch` with a `camera_name: varchar(80)` field, populated from `video_obj.device.camera_name` on the NWB `ImageSeries` device. Primary key is `(nwb_file_name, epoch, video_file_num)`.
- `CameraDevice` has primary key `camera_name`, with `camera_id : int` as a secondary attribute. That `camera_id` is the integer DLC's `camera` field expects.
- `TaskEpoch` has both a single-camera FK to `CameraDevice` and a `camera_names` blob listing all cameras for that epoch, so multi-camera epochs are captured there.

## One caveat about the file name

The NWB file name `j1620210710_.nwb` has a trailing underscore before `.nwb`, which is a little unusual — Spyglass typically stores files as `<animal><date>_.nwb` (e.g. `j16_20210710_.nwb` or `j1620210710_.nwb`). Make sure the string you pass to `nwb_file_name` exactly matches the entry in `Nwbfile`:

```python
from spyglass.common import Nwbfile
Nwbfile & "nwb_file_name LIKE 'j16%20210710%'"
```

Use whatever `nwb_file_name` that returns as the key in the queries above. If the lookup comes back empty, the session probably hasn't been ingested yet (`populate_all_common(nwb_file_name)` would need to run first to populate `VideoFile` and `TaskEpoch`).
