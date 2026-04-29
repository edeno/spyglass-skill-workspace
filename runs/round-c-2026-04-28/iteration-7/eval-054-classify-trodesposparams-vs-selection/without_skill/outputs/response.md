They look similar because they're both small tables you insert into by hand, but they play very different roles in the DataJoint pipeline. Once you see the role each one plays, the choice is mechanical.

## Short answer

- **`TrodesPosParams`** is a **parameter library**. One row = one named *recipe* (a bundle of processing settings: smoothing, speed thresholds, LED selection, etc.). You insert into it once per parameter set and reuse those rows across many epochs.
- **`TrodesPosSelection`** is the **"do this" table**. One row = one *job*: "run Trodes position processing on *this raw position interval* using *this parameter set*." Inserting here is what schedules the work.
- Neither one *computes* anything. The actual data lands in **`TrodesPosV1`** (a `dj.Computed` table), which you populate after the Selection row exists.

So the flow is:

```
TrodesPosParams      RawPosition (or the interval/epoch keys it depends on)
       \                  /
        \                /
       TrodesPosSelection      <-- you insert one row per (interval, params) you want processed
              |
              v
         TrodesPosV1.populate(key)   <-- this is what actually fills your data
```

You insert into **both**, but in different amounts and for different reasons.

## Why the pattern exists (the DataJoint convention)

Spyglass follows a recurring three-table pattern for every processing step:

1. **`...Params`** — `dj.Lookup` or `dj.Manual`. A catalog of named parameter sets. Primary key is just a name like `"default"` or `"my_smoothed_50ms"`. The blob holds the actual settings dict.
2. **`...Selection`** — `dj.Manual`. Joins a parameter set to a specific upstream key (e.g. an interval / epoch / raw position entry). Primary key = the upstream key + the params name. This is the "queue" of work to do.
3. **`...V1`** (or `...Output`) — `dj.Computed`. Has a `make()` method. You don't insert here directly; you call `.populate()` and DataJoint walks every row in Selection that doesn't yet have a matching computed row, runs `make()` on it, and inserts the result.

`TrodesPosParams` / `TrodesPosSelection` / `TrodesPosV1` are just the position-pipeline instance of that pattern. `LFPSelection`, `SpikeSortingSelection`, `RippleParameters`, etc. all follow the same shape.

## Concrete walkthrough

Assume you have raw position already ingested (so `RawPosition` has rows for your session).

### 1. Make sure a params row exists (usually you don't even need to do this)

`TrodesPosParams` ships with a `"default"` row already inserted as part of the lookup defaults. You only insert here if you want non-default settings:

```python
from spyglass.position.v1 import TrodesPosParams

TrodesPosParams.insert1(
    {
        "trodes_pos_params_name": "my_params",
        "params": {
            "max_separation": 9.0,
            "max_speed": 300.0,
            "position_smoothing_duration": 0.125,
            "speed_smoothing_std_dev": 0.100,
            "led1_is_front": 1,
            "is_upsampled": 0,
            "upsampling_sampling_rate": None,
            "upsampling_interpolation_method": "linear",
        },
    },
    skip_duplicates=True,
)
```

You do this **once per recipe**, not once per session.

### 2. Insert into Selection — this is the per-session step

This is the row that actually schedules processing for a specific interval:

```python
from spyglass.position.v1 import TrodesPosSelection

key = {
    "nwb_file_name": "mysession_.nwb",
    "interval_list_name": "pos 1 valid times",   # or whatever epoch you want
    "trodes_pos_params_name": "default",         # references TrodesPosParams
}
TrodesPosSelection.insert1(key, skip_duplicates=True)
```

That row is now in the queue.

### 3. Populate to actually compute

```python
from spyglass.position.v1 import TrodesPosV1

TrodesPosV1.populate(key)
```

This is the step that reads the raw LEDs, applies your smoothing/speed/etc. settings, and writes the processed position back into `TrodesPosV1`. After this, `(TrodesPosV1 & key).fetch1_dataframe()` will give you your data.

### 4. (Usually) insert into the merge table

In current Spyglass, downstream consumers read from `PositionOutput` (a merge table), not `TrodesPosV1` directly. So the last step is typically:

```python
from spyglass.position import PositionOutput

PositionOutput.insert1_from_selection(TrodesPosSelection() & key)
# or, depending on the version of spyglass you're on:
# PositionOutput.TrodesPosV1.insert1(key, skip_duplicates=True)
```

Check your installed version — the merge-insert API has shifted a bit between releases.

## Quick decision rule

Ask: **"Is this thing about *what settings to use* or *what data to run on*?"**

- *What settings* (smoothing constants, speed thresholds, which LED is front) → `TrodesPosParams`.
- *What data + which settings combo* (this nwb file, this interval, using params named X) → `TrodesPosSelection`.

If you ever find yourself wanting to put the nwb file name into `TrodesPosParams`, or wanting to put smoothing constants into `TrodesPosSelection`, you've crossed the wires — back up.

## One more thing that usually trips people up

Inserting into `TrodesPosSelection` does **not** run the computation. It just enqueues it. If you insert a Selection row and then `fetch` from `TrodesPosV1` and get nothing back, it's not broken — you just haven't called `.populate()` yet. The Selection row sits there waiting until something populates the downstream Computed table.

So to answer your literal question: you insert into **both**, but the one that triggers your data getting populated (after `.populate()`) is `TrodesPosSelection`. `TrodesPosParams` is just the named recipe it points at.
