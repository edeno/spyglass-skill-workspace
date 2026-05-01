# `ClusterlessDecodingV1.populate(key)` returns immediately, no rows added

## Symptom

`ClusterlessDecodingV1.populate(key)` returns instantly with no error and no log output, and `len(ClusterlessDecodingV1 & key) == 0` afterward.

## Most likely root cause

**`populate()` is silently doing nothing because `key_source & key` is empty** — i.e. there is no candidate row in the Selection that matches your `key`. DataJoint's `populate()` is defined to do nothing (no error, no log) when its candidate set is empty, and Spyglass does not wrap that behavior. There are two failure modes that both produce this exact symptom, plus one Selection-table gotcha that's so common it's worth flagging up front:

1. **No `ClusterlessDecodingSelection` row matches your `key`.** The decoder's `key_source` is the Selection projected to its primary key, so if you never inserted the Selection row (or inserted one with different field values), there is nothing to populate.
2. **Your `key` includes fields that are not in `ClusterlessDecodingSelection.key_source.heading`.** DataJoint silently drops unknown attrs from a restriction — those fields become no-ops rather than errors. A `key` made of only such fields can either match nothing or match too much.
3. **An upstream prerequisite was never populated.** Even if `ClusterlessDecodingSelection` has a row, the row's `nwb_file_name` / `waveform_features_group_name` / `position_group_name` / `decoding_param_name` / `encoding_interval` / `decoding_interval` must each resolve to existing upstream rows. If `insert1` succeeded (FKs were satisfied at insert time), the upstream rows do exist — but if any of them lack their own populated outputs (e.g. `UnitWaveformFeatures` not yet populated for everything in the group), downstream `make()` will eventually error rather than silently no-op. The "silent no-op" specifically means the Selection-row layer.

There is no fourth "hidden reservation" cause unless you previously ran `populate()` with `reserve_jobs=True` and it crashed — that's a separate failure mode (signature E in the runtime-debug reference) that you can rule out in step 4 below.

## Why that explanation fits

- `ClusterlessDecodingV1` is `dj.Computed`. Its `key_source` is `ClusterlessDecodingSelection.proj()` (the standard `dj.Computed` default; same pattern as every other `*V1` table in Spyglass). `populate(restriction)` iterates `(key_source & restriction) - ClusterlessDecodingV1.proj()` and calls `make()` on each. If that set is empty, the loop body never runs — no error, no log line.
- Spyglass's `PopulateMixin` does not customize this iteration; it delegates to DataJoint (`src/spyglass/utils/mixins/populate.py`), so the silent-no-op shape is inherited.
- A returning-immediately-with-zero-rows populate, *without an exception*, is the diagnostic fingerprint for the "candidate set is empty" branch (vs. "candidates exist, `make()` errored", which would raise).

## Fastest confirmation checks

Run these in order. The first one that returns `0` (or unexpectedly `0` for the Selection) names the root cause.

```python
from spyglass.decoding.v1.clusterless import (
    ClusterlessDecodingSelection,
    ClusterlessDecodingV1,
)

# 1. Does populate even have a candidate? This is the single most informative line.
print("candidates:", len(ClusterlessDecodingV1.key_source & key))
print("pending:   ", len((ClusterlessDecodingV1.key_source & key)
                          - ClusterlessDecodingV1.proj()))
print("populated: ", len(ClusterlessDecodingV1 & key))

# 2. Does the Selection row exist as you described?
print("selection rows:", len(ClusterlessDecodingSelection & key))
(ClusterlessDecodingSelection & key).fetch(as_dict=True)   # inspect

# 3. Are any fields in your `key` being silently ignored as not-in-heading?
print("key_source PK fields:", ClusterlessDecodingV1.key_source.heading.primary_key)
print("your key fields:     ", list(key.keys()))
# Any field in your key that isn't in the key_source heading is a silent no-op,
# and any PK field of key_source that's missing from your key is unrestricted.

# 4. Is there a stale ~jobs entry from a previous crashed run hiding this key?
import datajoint as dj
jobs = dj.Schema(ClusterlessDecodingV1.database).jobs
(jobs & {"table_name": ClusterlessDecodingV1.table_name}).fetch(as_dict=True)
```

Interpretation:

- `candidates == 0` and `selection rows == 0` → no Selection row matches; you need to insert one (step "Minimal fix" below).
- `candidates == 0` and `selection rows > 0` → your `key` doesn't intersect the Selection PK as projected. Compare `ClusterlessDecodingV1.key_source.heading.primary_key` with the fields in `key`; the offender is usually a typo (`encoding_interval_name` vs `encoding_interval`) or a wrong `decoding_param_name` (often the version-suffix mismatch — see below).
- `candidates > 0` and `pending == 0` → already populated. Check `len(ClusterlessDecodingV1 & key)` directly; if that is also 0, your `key` is matching `key_source` (which has the Selection's PK) but the populated rows live under a different PK projection — re-examine field names.
- `pending > 0` but `populate()` did nothing → step 4 (jobs table). A reserved/errored job entry from a prior crash will be silently skipped on subsequent populates.

## Minimal fix

The most common version of this bug is a missing/mismatched Selection row. The prerequisites for the Selection insert are documented in the decoding pipeline reference; the load-bearing ones to verify before re-inserting:

```python
from non_local_detector import __version__ as non_local_detector_version
from spyglass.decoding import (
    DecodingParameters, PositionGroup, UnitWaveformFeaturesGroup,
)
from spyglass.common import IntervalList

# All of these must exist (each `len() > 0`) before the Selection insert:
print(len(UnitWaveformFeaturesGroup & {
    "nwb_file_name": nwb_file_name,
    "waveform_features_group_name": features_group_name,
}))
print(len(PositionGroup & {
    "nwb_file_name": nwb_file_name,
    "position_group_name": position_group_name,
}))
print(len(DecodingParameters & {"decoding_param_name": decoding_param_name}))
print(len(IntervalList & {
    "nwb_file_name": nwb_file_name,
    "interval_list_name": encoding_interval_name,
}))
print(len(IntervalList & {
    "nwb_file_name": nwb_file_name,
    "interval_list_name": decoding_interval_name,
}))

# Common version-suffix gotcha: the stock decoding params are keyed
# f"contfrag_clusterless_{non_local_detector_version}", e.g.
# "contfrag_clusterless_v1.2.0" — NOT bare "contfrag_clusterless".
# They are also NOT auto-inserted on import; call once if needed:
DecodingParameters().insert_default()

selection_key = {
    "nwb_file_name": nwb_file_name,                         # required — inherited via both groups
    "waveform_features_group_name": features_group_name,
    "position_group_name": position_group_name,
    "decoding_param_name": f"contfrag_clusterless_{non_local_detector_version}",
    "encoding_interval": encoding_interval_name,            # field name is "encoding_interval", not "encoding_interval_name"
    "decoding_interval": decoding_interval_name,            # likewise
    "estimate_decoding_params": 0,                           # explicit; table default is 1
}

ClusterlessDecodingSelection.insert1(selection_key, skip_duplicates=True)

# Then repopulate. Restrict to a fully-specified PK to avoid populating
# unrelated rows you didn't intend.
sel_pk = (ClusterlessDecodingSelection & selection_key).fetch1("KEY")
ClusterlessDecodingV1.populate(sel_pk, reserve_jobs=False, display_progress=True)

# Verify it landed:
assert len(ClusterlessDecodingV1 & sel_pk) == 1, "populate produced no row; debug this key"
```

If the diagnostic in step 4 found a stale errored job for this key, narrow to that exact key and clear it before re-running:

```python
errors_for_key = jobs & {
    "table_name": ClusterlessDecodingV1.table_name,
    "status": "error",
    **sel_pk,
}
errors_for_key.fetch(as_dict=True)   # inspect first
errors_for_key.delete_quick()         # then clear
ClusterlessDecodingV1.populate(sel_pk, reserve_jobs=False)
```

## Robust fix

Wrap the populate in the pre/post sandwich so this exact silent-no-op is caught the next time:

```python
# Pre-populate: candidate set must be non-empty
candidates = ClusterlessDecodingV1.key_source & sel_pk
if len(candidates) == 0:
    raise RuntimeError(
        f"No candidate in key_source for {sel_pk}. "
        f"key_source PK = {ClusterlessDecodingV1.key_source.heading.primary_key}."
    )

ClusterlessDecodingV1.populate(sel_pk, reserve_jobs=False)

# Post-populate: row must have landed
if len(ClusterlessDecodingV1 & sel_pk) == 0:
    raise RuntimeError("populate produced no row; check ~jobs and make() body.")
```

## Watch-outs

- **Field-name typos are the #1 cause of this exact symptom on decoding.** The Selection's primary-key fields are `encoding_interval` and `decoding_interval` (no `_name` suffix), but the corresponding `IntervalList` field is `interval_list_name`. A `key` built with `encoding_interval_name` will silently no-op the restriction and find zero candidates.
- **Version-suffixed `decoding_param_name`.** Stock defaults are `f"contfrag_clusterless_{non_local_detector_version}"`. A bare `"contfrag_clusterless"` will not match.
- **`nwb_file_name` is required in the selection key.** It is inherited transitively through both `UnitWaveformFeaturesGroup` and `PositionGroup` (`decoding/v1/clusterless.py:83`, `decoding/v1/core.py:130`). Omitting it under-specifies the FK and the `insert1` raises — but if `insert1` was called silently with `skip_duplicates=True` and no row landed, the later `populate(key)` will look like the silent no-op you're seeing.
- **`populate()` does NOT raise on a loose dict** the way `fetch1()` does. A `key` that matches zero rows in `key_source` is indistinguishable, from `populate`'s seat, from "everything is already done." That's why the `len(key_source & key)` print is the load-bearing diagnostic.
- **Don't pass a non-PK dict to `populate()` and expect it to filter.** `populate(restrictions)` restricts against `key_source.heading`, which is just the Selection's PK fields. Any non-PK field in your dict is silently dropped (signature G in the runtime-debug reference). If your `key` was built from upstream-table fields (e.g. a `sort_group_id` from spike sorting), some of those fields may not be in the Selection's PK at all.
- **If `ClusterlessDecodingSelection.insert1(...)` ever succeeded for this `key` previously, then `key_source & key` should be non-empty.** If it isn't, your `key` is using a different field name or value than what's stored — fetch the Selection row directly and compare keys field by field.
