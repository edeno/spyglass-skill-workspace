# Part tables of `Probe`

DataJoint exposes the part tables attached to a master via the `parts()` method. One-liner:

```python
from spyglass.common import Probe; print(Probe.parts())
```

(Equivalent: `Probe.parts(as_objects=True)` if you want the actual class objects rather than full table names.)

## The two part tables

`Probe` has exactly two part tables, in `Master.Part` notation:

- `Probe.Shank` — one row per shank on the probe (`probe_shank: int` PK in addition to `probe_id`).
- `Probe.Electrode` — one row per electrode/contact (`probe_electrode: int` PK in addition to `probe_id` + `probe_shank`); carries `contact_size`, `rel_x/y/z`.

Both are populated during NWB ingestion alongside the master `Probe` row.

## Source of truth

Verified against `src/spyglass/common/common_device.py`:

- `class Probe(SpyglassIngestion, dj.Manual)` — line 377
- `class Shank(SpyglassIngestion, dj.Part)` nested under `Probe` — line 390
- `class Electrode(SpyglassIngestion, dj.Part)` nested under `Probe` — line 428

No other `dj.Part` classes are nested in `Probe`. (`ProbeType` is a separate master with its own part table `ProbeType.Shank`, not a part of `Probe`.)
