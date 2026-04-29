# Diagnosing posterior divergence between two clusterless decoding runs

Both pipelines completing without error tells you almost nothing about
*equivalence* — DataJoint will happily populate two different downstream
rows for the "same" NWB file as long as the upstream selection keys
differ anywhere along the chain. A noisier posterior on your side, given
identical NWB input, almost certainly means one of the upstream
*selection* primary keys is not actually what you think it is. Before
guessing which one, the right move is to diff the selection rows.

Below I list the most likely divergence surfaces, ordered roughly by how
directly they impact posterior smoothness, then give the minimal
diagnostic.

## Where two clusterless decoding runs can diverge

The clusterless decoding selection table (in current Spyglass this is
`ClusterlessDecodingSelection` in `spyglass.decoding.v1.clusterless`)
typically has these primary-key fields, each a foreign key into a
different upstream selection / parameter table. Any one of them being
different is sufficient to produce a different posterior even though
both runs "ran on the same NWB":

1. **Waveform features group** — the FK that tells the decoder *which
   set of clusterless waveform features* (and thus which electrodes /
   which sort group / which spike-detection threshold / which feature
   set: amplitude, PCs, etc.) to use as the encoding signal. If your
   group name points to a different `UnitWaveformFeaturesGroup` entry
   than your collaborator's, you are decoding from a different set of
   spikes. This is the single most common cause of "noisier posterior":
   fewer electrodes, a higher detection threshold, or a different
   feature representation reduces the information per time bin.

2. **Position group** — the FK into `PositionGroup`, which in turn
   threads in a particular `PositionOutput` merge_id. Two users can
   have selected different position sources (e.g., raw Trodes position
   vs. DLC, different smoothing, different interpolation, different
   speed filter). Different speed/position alignment changes which time
   bins are included in encoding and changes the place-field estimates.

3. **Decoding parameters** — the FK into `DecodingParameters`
   (`decoding_param_name`). This row contains the state-space model
   spec: state transition prior (random walk vs. continuous, transition
   variance), emission model details, smoothing/filtering choice,
   environment discretization, etc. A looser transition prior or a
   coarser grid produces a visibly noisier posterior on the same
   spikes.

4. **Encoding interval** — the FK into `IntervalList` projected as
   `encoding_interval`. This is the *training* epoch the place fields
   are estimated on. If your collaborator trained on a longer / cleaner
   run epoch and you trained on a shorter or partly-immobile epoch,
   your fields are noisier and so is the posterior.

5. **Decoding interval** — the FK into `IntervalList` projected as
   `decoding_interval`. This is the *test* epoch over which the
   posterior is computed. Different test epochs trivially give
   different posteriors; if one of you is decoding a noisier behavioral
   period (immobility, low spike count) the posterior will look noisier
   even with identical models.

6. **`estimate_decoding_params` flag** (secondary, boolean) — whether
   the decoder re-estimates parameters at inference time vs. uses the
   trained values. This is in the selection key in current Spyglass
   versions and is easy to set differently without noticing.

These are the *direct-FK surfaces* on the selection table — they are
what gates determinism for a populate.

### Second-order: upstream-chain differences

Even if every direct FK above matches by name, the *content* of those
upstream rows can still differ if the two of you populated them under
different parameter sets. Examples:

- Different sorter / spike-detection parameters feeding
  `UnitWaveformFeaturesGroup` (different `SpikeSortingSelection` →
  different `CurationV1` → different `UnitWaveformFeatures`).
- Different position parameters feeding `PositionGroup` (different
  `TrodesPosV1` / `DLCPosV1` parameters → different `PositionOutput`
  merge_id pulled in).
- Different waveform-feature parameter set
  (`WaveformFeaturesParams`).

These are real causes, but they are a **second-order check**: they
matter only if the direct selection keys above already match between
the two users. If the direct keys differ, there is no point chasing the
upstream chain.

### What this is *not* (likely) about

I would not jump to "environment / package drift" (different Spyglass
or `non_local_detector` versions, different NumPy, different BLAS) as
the primary explanation. Spyglass's design intent is that the selection
primary keys gate determinism — given identical selection rows and
identical NWB content, the populated result should be reproducible
across machines barring a genuine package bug. Environment drift is
worth checking *after* you have confirmed the selection keys are
actually identical.

## The minimal isolating diagnostic

Don't speculate which of the six surfaces above is responsible — just
diff the selection row directly. Concretely, on each user's setup:

```python
from spyglass.decoding.v1.clusterless import ClusterlessDecodingSelection

# the key that identifies "this populate" — nwb_file_name plus whatever
# scopes you both used (interval, etc.)
key = {"nwb_file_name": "j1620210710_.nwb", ...}

row = (ClusterlessDecodingSelection & key).fetch(as_dict=True)
print(row)
```

Have your collaborator run the same `fetch(as_dict=True)` against
*their* database with what *they* believe is the same key, and
compare the dicts field-by-field. The first field that differs is the
cause — or at least the proximate cause — of the divergence. Fields to
focus on:

- `waveform_features_group_name`
- `position_group_name`
- `decoding_param_name`
- `encoding_interval`
- `decoding_interval`
- `estimate_decoding_params`

If all six match: now drop one level and diff the *upstream*
selection rows those names point at (the second-order list). If those
also match, then and only then is environment drift worth
investigating.

## Where to read more

For the full populate dependency graph and how
`ClusterlessDecodingSelection` sits relative to `PositionGroup`,
`UnitWaveformFeaturesGroup`, `DecodingParameters`, and `IntervalList`,
see the Spyglass decoding pipeline notebook / docs (`decoding_pipeline.md`
in the Spyglass tutorials), and the source of
`spyglass.decoding.v1.clusterless` for the exact primary-key
definition on `ClusterlessDecodingSelection` in the version you are
running — the field names and the presence of
`estimate_decoding_params` have shifted across recent Spyglass
releases, so confirm against your installed version before
interpreting the diff.
