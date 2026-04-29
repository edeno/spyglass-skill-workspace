# Why 8 NWB epochs became 6 IntervalList rows

Short answer: `insert_sessions` does not blindly copy `nwb.epochs` row-for-row into `IntervalList`. It builds a *name* for each epoch and inserts with `skip_duplicates=True`. Whenever two NWB epochs collide on that constructed name (or an epoch produces an unusable name / unusable interval), the second one silently disappears. Two missing rows out of eight almost always means two name collisions, not "the data was dropped."

Below: where this happens, the four mechanisms that can drop epochs, and exactly how to find which two of yours were lost.

## Where the population happens

In `spyglass.common.common_session.Session.make()` (and helpers in
`spyglass.common.common_interval` / `spyglass.common.common_task`), the path during `insert_sessions` is roughly:

1. `insert_sessions(nwb_file_name)` registers the NWB file in `Nwbfile`, copies it into the analysis store, then calls `populate_all_common(nwb_file_name)`.
2. `populate_all_common` populates `Session`, whose `make()` method opens the NWB, iterates `nwbf.epochs.to_dataframe()`, and for each row builds an `interval_list_name` and inserts a row into `IntervalList` with `(nwb_file_name, interval_list_name, valid_times)`.
3. `TaskEpoch` then links a subset of those intervals to entries in `Task`/`TaskEpoch` based on `nwb.tasks` and the `task_epochs` association.

So the *primary key* on `IntervalList` is `(nwb_file_name, interval_list_name)`. If two NWB epoch rows generate the same `interval_list_name`, only one survives.

## The four ways NWB epochs go missing

### 1. Name collisions (by far the most common cause of "n in NWB → n−k in IntervalList")

Spyglass typically forms `interval_list_name` from the epoch's `tags` column, often as something like `"02_r1"` (epoch index zero-padded + tag). If your file has, for example:

- two "sleep" epochs both tagged `s1`
- a `home` epoch with no tag and another `home` epoch with no tag
- two epochs that share an identical `tags` string and the index logic strips/duplicates the prefix

…then two rows in `nwb.epochs` map to one `interval_list_name`. `IntervalList.insert(..., skip_duplicates=True)` silently drops the second. **No warning is raised.**

This is by far the most likely cause of an 8 → 6 drop: two pairs of duplicate names, or one pair of duplicate names plus one separate drop.

### 2. NaN / inf / empty `start_time` or `stop_time`

Spyglass treats `valid_times` as a `(n, 2)` array of `[start, stop]` floats. Epochs with `NaN`, `inf`, or `start_time >= stop_time` are filtered before insertion (or fail silently in some versions). Re-check your epochs with:

```python
df = nwb.epochs.to_dataframe()
print(df[["start_time", "stop_time", "tags"]])
print(df.isna().sum())
print((df["stop_time"] <= df["start_time"]).sum())
```

If `j1620210710` was assembled by a trodes-to-NWB converter, sleep-box epochs sometimes get `NaN` stops when the recording stopped without a clean trial-end marker.

### 3. Empty `tags` triggering a fallback that collides with another epoch

Some NWB files store `epochs.tags` as an empty `VectorData` for non-task epochs (sleep, rest, transport). Spyglass's name builder falls back to a generic name in that case (historically things like `"unknown"` or just the index). If two epochs both fall through to the same fallback, they collide.

### 4. Epoch is a task-epoch but the linked task wasn't ingested

This drops *task-epoch links* in `TaskEpoch`, not `IntervalList` rows — so it's not your case (you're missing `IntervalList` rows). Mentioning only so you don't chase it.

## How to confirm which mechanism applies to your file

Run this against the same NWB file you ingested:

```python
import pynwb
from spyglass.common import IntervalList

# 1. What did Spyglass actually keep?
keys = (IntervalList & {"nwb_file_name": "j1620210710_.nwb"}).fetch(
    "interval_list_name"
)
print("Kept names:", sorted(keys))

# 2. What did the NWB file claim?
with pynwb.NWBHDF5IO("j1620210710.nwb", "r", load_namespaces=True) as io:
    nwbf = io.read()
    df = nwbf.epochs.to_dataframe()
print(df[["start_time", "stop_time", "tags"]])

# 3. Reconstruct what Spyglass would have called each row
def epoch_name(i, row):
    tag = ",".join(row["tags"]) if len(row["tags"]) else "untagged"
    return f"{i:02d}_{tag}"

constructed = [epoch_name(i, r) for i, r in df.iterrows()]
print("Constructed names:", constructed)

# 4. Find duplicates among the constructed names
from collections import Counter
print("Duplicates:", [n for n, c in Counter(constructed).items() if c > 1])
```

Note the exact name builder may differ between Spyglass versions (the
common-table layer has been refactored a few times); check
`spyglass.common.common_session.Session.make` in the version you have
installed for the authoritative formula. The point of step 3 is to
find rows whose names *would have* matched.

If step 4 lists two duplicates, that's your answer — those are the two epochs that got merged into existing rows on insert.

## Fixes (once you know which ones dropped)

- **If it's a name collision:** rebuild the NWB file giving the duplicate epochs distinct `tags` (e.g. `s1`, `s2` instead of both `sleep`). Or, if the conversion is owned by you, change the converter so each epoch gets a unique `(start_time, stop_time, tags)` signature.
- **If it's NaN/inf times:** find the bad epoch, fix the converter to write a real `stop_time` (often the last sample's timestamp), and regenerate the NWB.
- **Either way, you'll need to re-ingest:** delete the existing `Session` entry for this NWB (`(Session & {"nwb_file_name": "..."}).delete()` — this cascades through `IntervalList`, `TaskEpoch`, etc.) before re-running `insert_sessions`. Otherwise the partial state from the first ingest sticks around.

## What to *not* assume

- Do **not** assume Spyglass logs a warning when it drops an epoch. The `skip_duplicates=True` path is silent in DataJoint.
- Do **not** assume the dropped epochs are the last two in `nwb.epochs`. They're whichever ones lost the collision — typically the *later* of each duplicate pair.
- Do **not** patch Spyglass to allow duplicate `interval_list_name`s. That key is referenced by every downstream pipeline (`TaskEpoch`, `IntervalPositionInfo`, `LFPSelection`, sorting, decoding). Fix it at the NWB level.

## TL;DR

Two of your eight epochs collided with two of the other six on the `interval_list_name` Spyglass constructs from `(epoch_index, tags)`. They were silently dropped by `insert(..., skip_duplicates=True)`. Reproduce the constructed names from `nwb.epochs.to_dataframe()`, find the two duplicate names, fix the tags (or the times, if any are NaN), `delete()` the partial Session, and re-ingest.
