# Diverging clusterless posteriors on the same NWB — where to look first

Both populates succeeding tells you nothing about whether you ran the *same*
analysis. The selection row gates that, not the populate. Before reaching for
environment / package drift, diff the selection rows — the keys are
load-bearing for determinism.

## What `ClusterlessDecodingSelection` is keyed on

From `src/spyglass/decoding/v1/clusterless.py:83-91`:

```
@schema
class ClusterlessDecodingSelection(SpyglassMixin, dj.Manual):
    definition = """
    -> UnitWaveformFeaturesGroup
    -> PositionGroup
    -> DecodingParameters
    -> IntervalList.proj(encoding_interval='interval_list_name')
    -> IntervalList.proj(decoding_interval='interval_list_name')
    estimate_decoding_params = 1 : bool # 1 to estimate the decoding parameters
    """
```

So for the same `nwb_file_name = "j1620210710_.nwb"`, two rows can differ on
**five direct foreign-key surfaces plus one secondary bool** — any one of
which can produce a noisier posterior while both populates "succeed":

1. **`waveform_features_group_name`** (FK → `UnitWaveformFeaturesGroup`) —
   different units / waveform-feature sets feeding the decoder. Different
   tetrodes included, different curation choices, or a different
   `WaveformFeaturesParams` (`"amplitude"` vs `"amplitude, spike_location"`)
   upstream all collapse here. Fewer/noisier features → noisier posterior.
2. **`position_group_name`** (FK → `PositionGroup`) — different
   `PositionOutput` `merge_id`s threaded into the part table. This changes
   the behavioral track / speed / interpolation that the encoding model is
   conditioned on; even subtle shifts (e.g. a different DLC vs Trodes
   `pos_merge_id`, a different `upsample_rate`, different `position_variables`)
   degrade the encoding fit.
3. **`decoding_param_name`** (FK → `DecodingParameters`) — *the* most
   common silent divergence. Different state-transition prior, different
   smoothing, or contfrag vs nonlocal classifier all live here. Note that
   the stock defaults are *version-suffixed*
   (`contfrag_clusterless_{non_local_detector_version}`,
   `decoding/v1/core.py:48`), so two users on different
   `non_local_detector` versions can each "use the default" and still land
   on different rows.
4. **`encoding_interval`** (FK → `IntervalList.proj(encoding_interval=...)`) —
   the training epoch. A shorter or behaviorally atypical encoding interval
   produces a worse place-field fit and therefore a noisier posterior at
   decode time.
5. **`decoding_interval`** (FK → `IntervalList.proj(decoding_interval=...)`) —
   the test epoch. Could just be that one of you decoded a quiet/SWR-rich
   epoch and the other decoded a run epoch.
6. **`estimate_decoding_params`** (bool, default `1` per
   `clusterless.py:90`) — toggles between two materially different
   `make()` branches: the True branch runs Baum-Welch and re-estimates
   transitions/initial conditions inside `make()`
   (`clusterless.py:289`), while the False branch uses the parameters
   from `DecodingParameters` as-is and concatenates per-interval results
   (`clusterless.py:333`). Same nominal `decoding_param_name`, different
   posterior — and the table default being `1` means it's easy for one
   user to leave it implicit and the other to set it to `0` explicitly.

## Minimal isolating diagnostic — run this first

Don't speculate on a cause. Fetch and diff the actual selection rows
between the two users:

```python
from spyglass.decoding.v1.clusterless import ClusterlessDecodingSelection

key = {"nwb_file_name": "j1620210710_.nwb"}

# Each of you runs this on your own DB connection:
mine = (ClusterlessDecodingSelection & key).fetch(as_dict=True)
# share the dict via copy-paste / json — these are all small strings + a bool

# Then diff field-by-field on the six attributes above:
for row in mine:
    print({k: row[k] for k in (
        "waveform_features_group_name",
        "position_group_name",
        "decoding_param_name",
        "encoding_interval",
        "decoding_interval",
        "estimate_decoding_params",
    )})
```

If only one of those six attributes differs between your row and theirs,
that's your suspect — no further investigation needed until you've
re-populated with the matching key and confirmed the posteriors agree.

If the six fields are *identical* across both users, **then** it's a
second-order check: the FK targets resolve to the same name on each side
but the upstream contents differ. That can happen when:

- the same `waveform_features_group_name` was created from different
  `SpikeSortingOutput` / `CurationV1` / sorter-parameter rows on the two
  databases (different sort, same group name);
- the same `position_group_name` was created from different
  `PositionOutput` `merge_id`s (different DLC model or Trodes params,
  same group name);
- the same `decoding_param_name` was inserted with different
  `decoding_params` / `decoding_kwargs` blobs (rare if you both used
  `DecodingParameters().insert_default()`, more common with custom
  inserts).

You'd verify those by walking the part tables
(`UnitWaveformFeaturesGroup.UnitFeatures`, `PositionGroup.Position`) and
comparing the underlying merge_ids / curation_ids / sorter params on each
side. But that's the *second* step, not the first.

## What is NOT (yet) the likely cause

- **Environment / package drift alone.** The selection-key surfaces above
  are what gate determinism in this pipeline. Two matching selection rows
  with mismatched envs can still produce identical posteriors for the
  fixed-parameter branch (or numerically very close ones for the
  estimate branch). Mismatched selection rows produce different
  posteriors *even on the same env*. So drift is downstream of, not a
  substitute for, the diff above. (One narrow exception worth noting
  *after* the diff: a `non_local_detector` version mismatch will change
  the version-suffixed `decoding_param_name` default, which would show
  up as a `decoding_param_name` difference in step 1 — i.e. it surfaces
  through the FK, not around it.)

For the broader workflow context — selection insert shape, the
estimate-vs-fixed branches inside `make()`, and how to fetch results — see
[`decoding_pipeline.md`](../../../skills/spyglass/references/decoding_pipeline.md).

Bottom line: **diff `ClusterlessDecodingSelection & key` first.** Don't
commit to a cause until you've seen which of the six fields differs.
