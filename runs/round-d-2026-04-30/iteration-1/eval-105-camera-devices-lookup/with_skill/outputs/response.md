# Cameras for `j1620210710_.nwb`

I can't read your live database from here, so I can't hand you the
camera IDs themselves — but I can hand you the queries that will
return them, plus a heads-up about a real footgun in this corner of
Spyglass that bites people writing exactly this kind of lookup.

## The footgun first (so you don't trip it)

`CameraDevice` is **not** keyed by `nwb_file_name`. Its only PK is
`camera_name` (`spyglass.common.common_device.CameraDevice`,
`PK = camera_name`). That means:

```python
# WRONG — silently returns the entire CameraDevice table
CameraDevice & {"nwb_file_name": "j1620210710_.nwb"}
```

DataJoint drops the unknown attribute and gives you every camera in
the lab — not the cameras for this session. This is the same
"silent wrong-count" shape called out in the skill's common-mistakes
list (#6). To resolve cameras for a session you have to go through a
table that *is* keyed by `nwb_file_name` — `TaskEpoch` or
`VideoFile` — and then carry the `camera_name` over to
`CameraDevice`.

There is also no declared FK from `VideoFile` to `CameraDevice`.
`VideoFile.camera_name` is a *secondary attribute* (`varchar(80)`,
`common_behav.py:470`); the string match is enforced only at ingest
time inside `VideoFile._prepare_video_entry` (`common_behav.py:505`),
which raises `KeyError` if the camera isn't already in
`CameraDevice`. So the join on `camera_name` works (both tables
expose the column), it's just not FK-driven — don't expect
`CameraDevice` to inherit `nwb_file_name` through propagation,
because there's no FK to propagate along.

## What "camera ID" means here

Two different things in this corner of Spyglass go by "ID", and DLC
configs can want either, so pick deliberately:

1. **`camera_name`** — the PK of `CameraDevice`, a string like
   `"camera1"` or whatever your lab uses. This is the canonical
   identifier and the one the relational layer hands you back.
2. **The integer in the NWB device name** — Spyglass's ingest
   parses `"camera_device <N>"` out of `video_obj.device.name` with
   the regex `r"camera_device (\d+)"` (`common_behav.py:478, 511`).
   That `<N>` is what some DLC pipelines call a "camera ID".

`TaskEpoch` also carries a per-epoch `camera_names: blob` (plural
list) plus a single nullable `-> CameraDevice` FK
(`common_task.py:124`), so a single epoch can reference more than
one camera.

## The queries you actually want

```python
from spyglass.common import TaskEpoch, VideoFile, CameraDevice

nwb_file = "j1620210710_.nwb"

# 1. Per-epoch camera assignments (what the task metadata says)
#    -> CameraDevice FK on TaskEpoch is nullable; camera_names is
#    the plural list per epoch.
(TaskEpoch & {"nwb_file_name": nwb_file}).fetch(
    "epoch", "camera_id", "camera_names", as_dict=True
)

# 2. Cameras that actually have video files for this session
#    (this is usually what you want for a DLC config)
cam_names = (
    (VideoFile & {"nwb_file_name": nwb_file})
    .fetch("camera_name")
)
set(cam_names)  # distinct camera_names used by this session

# 3. Look those up in CameraDevice to get the full hardware row
#    (meters_per_pixel, manufacturer, model, etc.)
CameraDevice & [{"camera_name": c} for c in set(cam_names)]
# or, equivalently, a natural join (works because both tables expose
# camera_name even though it isn't an FK):
VideoFile * CameraDevice & {"nwb_file_name": nwb_file}
```

Quick cross-check that nothing got dropped silently:

```python
print(len(VideoFile & {"nwb_file_name": nwb_file}))   # should be > 0
print(len(TaskEpoch & {"nwb_file_name": nwb_file}))   # should be > 0
```

If `VideoFile` is empty for this session but `TaskEpoch` has rows,
the videos weren't ingested (Spyglass logs a warning when an NWB has
`ImageSeries` but no `TaskEpoch`, see the docstring at
`common_behav.py:461`) — in that case fall back to query (1) on
`TaskEpoch.camera_names` for the lab-recorded list.

## Mapping `camera_name` to the integer DLC sometimes wants

If your DLC config wants the integer from `camera_device <N>` rather
than the `CameraDevice.camera_name` string, the source-of-truth
mapping lives on the raw NWB file, not on a Spyglass table — open
the file with pynwb and read each `ImageSeries`'s `device.name` and
`device.camera_name`:

```python
import pynwb
from spyglass.common import Nwbfile

abs_path = Nwbfile.get_abs_path(nwb_file)
with pynwb.NWBHDF5IO(abs_path, "r", load_namespaces=True) as io:
    nwbfile = io.read()
    for name, obj in nwbfile.acquisition.items():
        if isinstance(obj, pynwb.image.ImageSeries):
            print(name, obj.device.name, obj.device.camera_name)
```

`obj.device.name` will be the `"camera_device <N>"` form whose `<N>`
ingest extracts; `obj.device.camera_name` is the string that lands
in `CameraDevice.camera_name` and `VideoFile.camera_name`.

## TL;DR

- Don't restrict `CameraDevice` by `nwb_file_name` — it has no such
  field and you'll get every camera in the lab back.
- For "what cameras recorded this session", run query (2) above
  (`VideoFile.camera_name` distinct, restricted by `nwb_file_name`).
- For the per-epoch task-metadata view (and for DLC where each
  epoch's camera assignment matters), use query (1) on `TaskEpoch`.
- If your DLC config wants the integer suffix instead of
  `camera_name`, read it off the NWB file's `ImageSeries.device.name`
  via pynwb — Spyglass doesn't store it as a separate column.

If you paste back what query (2) returns for
`j1620210710_.nwb`, I can help you wire those camera names (or
their integer suffixes) into the DLC config.
