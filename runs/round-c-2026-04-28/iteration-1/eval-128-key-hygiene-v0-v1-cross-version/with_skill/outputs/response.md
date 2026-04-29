# No — `set_group_by_electrode_group` does not exist on v1's `SortGroup`

That helper is **v0-only**. The v0 docs you're reading describe `spyglass.spikesorting.v0.spikesorting_recording.SortGroup`, which exposes both `set_group_by_shank` and `set_group_by_electrode_group`. The v1 rewrite (`spyglass.spikesorting.v1.recording.SortGroup`) intentionally dropped the electrode-group helper and only ships `set_group_by_shank`. Treat pipeline version as load-bearing here — porting the v0 call into a v1 workflow will raise `AttributeError`.

## Source evidence (verified by reading the repo, not memory)

**v1 — `SortGroup` defines only `set_group_by_shank`:**
- File: `src/spyglass/spikesorting/v1/recording.py`
- `class SortGroup(SpyglassMixin, dj.Manual):` at line 34
- `def set_group_by_shank(...)` at line 51 (a `@classmethod`)
- The class body ends at line 95; there is no `set_group_by_electrode_group` anywhere in the file.

**v0 — `SortGroup` defines both helpers:**
- File: `src/spyglass/spikesorting/v0/spikesorting_recording.py`
- `def set_group_by_shank(...)` at line 48
- `def set_group_by_electrode_group(self, nwb_file_name: str)` at line 94

Greps used to anchor this:

```
$ grep -n "def set_group" src/spyglass/spikesorting/v1/recording.py \
                          src/spyglass/spikesorting/v0/spikesorting_recording.py
v1/recording.py:51:    def set_group_by_shank(
v0/spikesorting_recording.py:48:    def set_group_by_shank(
v0/spikesorting_recording.py:94:    def set_group_by_electrode_group(self, nwb_file_name: str):
```

You can reproduce this any of three ways:

1. **Agent tool (preferred):**
   ```bash
   python skills/spyglass/scripts/code_graph.py find-method set_group_by_electrode_group
   ```
   Returns the v0 owner (`spyglass/spikesorting/v0/spikesorting_recording.py:94`) only — no v1 hit.

2. **Source read:** the grep above against `$SPYGLASS_SRC`.

3. **Python introspection on the imported v1 class:**
   ```python
   from spyglass.spikesorting.v1.recording import SortGroup
   [m for m in dir(SortGroup) if "set_group" in m]
   # ['set_group_by_shank']    # no set_group_by_electrode_group
   ```

## What to do instead on v1

Use `set_group_by_shank` — it is the only sort-group population helper on v1:

```python
from spyglass.spikesorting.v1.recording import SortGroup

SortGroup.set_group_by_shank(
    nwb_file_name=nwb_file_name,
    references=None,            # optional dict: {electrode_group_name: ref_electrode_id}
    omit_ref_electrode_group=False,
    omit_unitrode=True,
)
```

This places electrodes from 1-shank probes (e.g. tetrodes) into a single group and electrodes from multi-shank probes into one group per shank, dropping bad channels. There is no v1 equivalent of grouping-by-electrode-group; if you genuinely need that grouping topology you'll have to insert into `SortGroup` and `SortGroup.SortGroupElectrode` manually.

If you want the rest of the v1 spike-sorting flow (recording selection → `SpikeSortingRecording.populate` → preprocessing/sorter params → `SpikeSorting`), that's the standard `spikesorting_v1_pipeline.md` path. The v0 helper is documented in `spikesorting_v0_legacy.md` and should only be referenced when reading old code or old data — don't port the API across versions.
