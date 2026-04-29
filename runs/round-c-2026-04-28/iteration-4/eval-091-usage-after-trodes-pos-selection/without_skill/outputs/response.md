After inserting a `TrodesPosSelection` row, the next step is to populate `TrodesPosV1` to actually run the position processing. The selection table just *picks* the (NWB file, interval, parameter set) triple you want processed — it doesn't compute anything. The compute happens in the downstream `TrodesPosV1` table's `make()` method when you call `populate()`.

Concrete sequence:

```python
from spyglass.position.v1 import TrodesPosV1, TrodesPosSelection

# the key you used (or a restriction that selects it)
key = {
    "nwb_file_name": "minirec20230622_.nwb",
    "interval_list_name": "pos 0 valid times",
    "trodes_pos_params_name": "default",
}

# 1. Confirm the selection row is there
TrodesPosSelection() & key

# 2. Run the pipeline — this reads raw position from the NWB file,
#    applies the params (smoothing, LED orientation, upsampling, etc.),
#    and writes the result as an analysis NWB file.
TrodesPosV1.populate(key, display_progress=True)

# 3. Inspect the output table
TrodesPosV1() & key
```

After `TrodesPosV1` is populated you'll typically:

1. **Insert into the merge table** so downstream pipelines can find it through a single interface:
    ```python
    from spyglass.position.position_merge import PositionOutput
    PositionOutput.insert([key], part_name="TrodesPosV1")
    # or PositionOutput._merge_insert(...) depending on the version
    ```
    Many newer Spyglass versions auto-insert into `PositionOutput` from `TrodesPosV1.make()`; check whether the merge row already exists with `PositionOutput.TrodesPosV1() & key` before inserting manually.

2. **Fetch the processed position** for analysis or QC:
    ```python
    merge_key = (PositionOutput.TrodesPosV1 & key).fetch1("KEY")
    pos_df = (PositionOutput & merge_key).fetch1_dataframe()
    # columns typically include: time, position_x, position_y,
    # orientation, velocity_x, velocity_y, speed
    ```

3. **Sanity-check the output** before building anything on top of it — plot `position_x` vs `position_y` over the interval, plot `speed` vs time, and confirm there are no large gaps or LED-swap artifacts. If the trajectory looks wrong, revisit the `TrodesPosParams` (LED orientation, smoothing window, max distance between LEDs) and re-run with a new params name rather than overwriting.

4. **Feed it into downstream pipelines** that consume `PositionOutput` — typically `LinearizationSelection` -> `LinearizedPositionV1` for track-linearized position, and from there into ripple detection, decoding (`ClusterlessDecodingV1` / `SortedSpikesDecodingV1`), or place-field analyses.

If `populate()` fails, the most common causes are: (a) the underlying `RawPosition` / `IntervalList` row for that NWB file + interval doesn't exist (ingestion incomplete), (b) the chosen `trodes_pos_params_name` doesn't exist in `TrodesPosParams`, or (c) the LED labels in the NWB file don't match what the params expect.
