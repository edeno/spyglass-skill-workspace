They look similar because they're both **Manual** tables (you insert into both yourself), but they play different roles in the standard 3-step Spyglass pipeline pattern: **params → selection → populate**.

## The two tables, side by side

**`TrodesPosParams`** — *the recipe*

- Primary key: `trodes_pos_params_name` (just a name like `"default"`)
- Holds the *parameters* of the position-processing algorithm (smoothing, speed thresholds, etc.) inside a `params` blob.
- One row per parameter set. You typically insert it **once** and reuse it across many sessions.
- Has convenience methods `insert_default()` and `get_default()`.

**`TrodesPosSelection`** — *the work order*

- Primary key: `nwb_file_name`, `interval_list_name`, `trodes_pos_params_name`
- Doesn't hold parameter values — it just *picks* which session + which interval + which params row to run on.
- One row per (session, interval, params) combo you actually want computed.
- It's the table `TrodesPosV1.populate()` reads from to know what to compute.

Note that `TrodesPosSelection` has `trodes_pos_params_name` in its key — that's the foreign-key pointer back to `TrodesPosParams`. So the selection row references a params row; it doesn't store the params itself.

## Pipeline flow

```text
RawPosition (common) → TrodesPosSelection → TrodesPosV1 → PositionOutput.TrodesPosV1
                                ↑
                        TrodesPosParams
```

## Which one do I insert into to populate my data?

**Both, in order.** This is the canonical 3-step pattern:

```python
from spyglass.position import PositionOutput
from spyglass.position.v1 import TrodesPosParams, TrodesPosSelection, TrodesPosV1

# 1. Params — insert once, reuse for many sessions
TrodesPosParams().insert_default()   # creates the "default" row

# 2. Selection — pick which session/interval/params combo to run
key = {
    "nwb_file_name": nwb_file,
    "interval_list_name": "pos 1 valid times",
    "trodes_pos_params_name": "default",
}
TrodesPosSelection.insert1(key, skip_duplicates=True)

# 3. Populate — does the actual computation; writes to TrodesPosV1
#    and auto-inserts into PositionOutput merge table
TrodesPosV1.populate(key)
```

Then fetch via the merge table:

```python
merge_key = PositionOutput.merge_get_part(key).fetch1("KEY")
position_df = (PositionOutput & merge_key).fetch1_dataframe()
# Columns: position_x, position_y, orientation, velocity_x, velocity_y, speed
```

## Mental model

- If you have **new processing parameters** to define → insert into `TrodesPosParams`.
- If you have **a session you want processed** with existing params → insert into `TrodesPosSelection`.
- If you want **the actual position output** → call `TrodesPosV1.populate(key)`, then fetch through `PositionOutput`.

If you only insert into `TrodesPosParams`, nothing computes — you've just defined a recipe. If you skip `TrodesPosParams` and only try `TrodesPosSelection`, the insert will fail the foreign-key check because there's no matching `trodes_pos_params_name` row to reference.

This same params → selection → populate shape is used across nearly every Spyglass pipeline (LFP, ripple, decoding, DLC, spike sorting), so once it clicks here it transfers.

## Quick check

To see what's already there:

```python
TrodesPosParams()       # list available parameter sets
TrodesPosSelection()    # list which session/interval/params combos are queued
TrodesPosV1()           # list which ones have actually been computed
```

And to confirm the default params row exists before you reference it:

```python
TrodesPosParams & {"trodes_pos_params_name": "default"}
```
