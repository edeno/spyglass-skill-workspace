# `SortGroup.set_group_by_electrode_group` on v1 — does it exist?

**Short answer: No.** `set_group_by_electrode_group` is a **v0-only** helper.
On v1's `SortGroup`, calling `SortGroup.set_group_by_electrode_group(nwb_file_name)`
will raise `AttributeError`. The v1 equivalent is **`set_group_by_shank`**, and v1
does not ship an "electrode-group" variant at all.

## What's actually defined where

I verified this by reading the Spyglass source directly rather than relying on
memory. The two `SortGroup` classes live in different modules and have
different method surfaces:

### v0 — `spyglass/spikesorting/v0/spikesorting_recording.py`

```text
class SortGroup(SpyglassMixin, dj.Manual):       # line 33
    ...
    def set_group_by_shank(...):                 # line 48
    def set_group_by_electrode_group(            # line 94
        self, nwb_file_name: str
    ):
        # delete any current groups
        (SortGroup & {"nwb_file_name": nwb_file_name}).delete()
        # one sort group per unique electrode_group_name on non-bad channels
        ...
```

So on v0 you have **two** grouping helpers: by shank, or by electrode group.

### v1 — `spyglass/spikesorting/v1/recording.py`

```text
class SortGroup(SpyglassMixin, dj.Manual):       # line 34
    ...
    @classmethod
    def set_group_by_shank(                      # line 51
        cls,
        nwb_file_name: str,
        references: dict = None,
        omit_ref_electrode_group: bool = False,
        omit_unitrode: bool = True,
    ):
        ...
```

That's the **entire** classmethod surface on v1's `SortGroup`. There is no
`set_group_by_electrode_group`, no other group-builder helper. (The class also
defines a `SortGroupElectrode` part table, but no additional group-population
method.)

A few other v0-vs-v1 differences worth flagging since they bite people in the
same way:

| Aspect | v0 `SortGroup` | v1 `SortGroup` |
|---|---|---|
| Module | `spyglass.spikesorting.v0.spikesorting_recording` | `spyglass.spikesorting.v1.recording` |
| `set_group_by_shank` | instance method, calls `self.insert(..., skip_duplicates=False)` | **classmethod**, calls `cls.insert(..., skip_duplicates=True)` |
| `set_group_by_electrode_group` | present (line 94) | **absent** |

So even `set_group_by_shank` itself isn't a drop-in: in v1 you call it on the
class (`SortGroup.set_group_by_shank(nwb_file_name)`); in v0 you typically call
it on an instance (`SortGroup().set_group_by_shank(nwb_file_name)`). Either
form usually works at runtime in v1 because it's a classmethod, but lifting v0
docs verbatim is the kind of thing that produces silently-wrong code.

## Why the v0 docs don't apply

The v0 and v1 spike-sorting pipelines are **separate schemas with separate
table classes that happen to share names**. They're co-installed; importing
`SortGroup` from `spyglass.spikesorting.v0.spikesorting_recording` and from
`spyglass.spikesorting.v1.recording` gives you two unrelated DataJoint tables
backed by different schema definitions. v1 was a redesign, and the
electrode-group helper was deliberately not carried over — the v1 sort-group
abstraction is shank-centric.

This is also why "the v0 docs show X" isn't a reliable guide for v1: if you're
running the v1 pipeline (anything you populate via
`SpikeSortingRecording`/`SpikeSortingRecordingSelection` from
`spyglass.spikesorting.v1`), you need to use the v1 grouping API.

## How to verify yourself (don't trust memory, including mine)

Any of these will tell you authoritatively which methods a given `SortGroup`
exposes:

1. **Python introspection on the imported class** — fastest:

   ```python
   from spyglass.spikesorting.v1.recording import SortGroup as V1SortGroup
   from spyglass.spikesorting.v0.spikesorting_recording import SortGroup as V0SortGroup

   [m for m in dir(V1SortGroup) if "set_group" in m]
   # -> ['set_group_by_shank']

   [m for m in dir(V0SortGroup) if "set_group" in m]
   # -> ['set_group_by_electrode_group', 'set_group_by_shank']
   ```

   If you ever wonder "is this on v1?", `dir(...)` plus a substring filter is
   the ground truth.

2. **A version-specific source read** — `grep -n "def set_group" \
   $SPYGLASS_SRC/src/spyglass/spikesorting/v1/recording.py` returns exactly
   the one method (`set_group_by_shank`, line 51). Same grep against
   `spikesorting/v0/spikesorting_recording.py` returns both (lines 48 and 94).

3. **Agent code-graph tool** (if you use the project's `code_graph.py`):
   `code_graph.py find-method set_group_by_electrode_group` will return only
   the v0 owner; `find-method set_group_by_shank` will return both owners,
   one per version.

I checked options (1)-(2) above against the source at
`/Users/edeno/Documents/GitHub/spyglass/src/spyglass/spikesorting/v{0,1}/`
before writing this answer.

## What to do instead on v1

For the standard v1 spike-sorting pipeline (and for clusterless / waveform
workflows that build on it), use:

```python
from spyglass.spikesorting.v1.recording import SortGroup

SortGroup.set_group_by_shank(
    nwb_file_name=nwb_file_name,
    references=None,            # or {electrode_group_name: ref_electrode_id, ...}
    omit_ref_electrode_group=False,
    omit_unitrode=True,         # drop probes with a single channel
)
```

This populates `SortGroup` and its `SortGroupElectrode` part table for that
NWB file based on shank geometry. From there you continue with
`SpikeSortingRecordingSelection.insert_selection(...)` →
`SpikeSortingRecording.populate(...)` etc., all in
`spyglass.spikesorting.v1.recording`.

If the reason you wanted `set_group_by_electrode_group` was specifically "one
sort group per electrode group" (e.g. one tetrode = one group), you usually
get the same outcome from `set_group_by_shank` for tetrode data, because each
tetrode is a single-shank probe and ends up as its own sort group. For
non-tetrode probes where you genuinely need per-electrode-group bundling that
v1 doesn't provide, you'd have to insert into `SortGroup` /
`SortGroup.SortGroupElectrode` manually — but that's a custom workflow, not a
v1 helper.

**Do not** port the v0 `set_group_by_electrode_group` call into v1 code; it
will fail at the attribute lookup, and "fixing" it by silently switching
imports between v0 and v1 across a project is exactly the kind of cross-
version mix-up that leaves orphaned rows in one schema and populated rows in
the other.

## Summary

- `set_group_by_electrode_group` exists **only** on v0's `SortGroup`
  (`spyglass/spikesorting/v0/spikesorting_recording.py:94`).
- v1's `SortGroup` (`spyglass/spikesorting/v1/recording.py:34`) exposes only
  `set_group_by_shank` (line 51) as a classmethod.
- The v0 docs describe the v0 schema; don't apply them to v1. Use
  `SortGroup.set_group_by_shank(nwb_file_name=...)` on v1.
- Verified against the live source under
  `/Users/edeno/Documents/GitHub/spyglass/src/spyglass/spikesorting/`, not
  from memory. You can re-verify any time with
  `dir(SortGroup)` after importing from the v1 module
  (`spikesorting_v1_pipeline.md`-style workflow).
