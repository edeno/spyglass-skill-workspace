# Why your `fetch_results` returns data and your labmate's returns empty

The symptom proves your two pipeline states are *not* identical, even though you both "ran the same selection + populate" on `j1620210710_.nwb`. `fetch_results` is `DecodingOutput`-only (`src/spyglass/decoding/decoding_merge.py:74`); it routes `key` through `merge_restrict_class(key).fetch_results()`, so an empty return means the merge restriction resolved to a row whose underlying part-table row either doesn't exist, points at different upstream content, or was produced by a different code path. Below are the four most plausible state differences. Don't commit to one until you've inspected both sides side-by-side.

## Plausible state differences (any one can produce an empty fetch)

1. **Different `params_name` on the selection.** "Same parameters" at the prompt level very often means *different named entries* in the params table. Decoding pulls the params blob via the params-name PK (e.g. `decoding_param_name` on `DecodingParameters`), and your labmate's `params_name` may resolve to a row that doesn't exist or — more insidiously — exists with subtly different blob contents. Two rows with the same blob but different names also count: the FK is on the name, not the content.

2. **Selection & key exists, but the populate hasn't actually run on theirs.** `fetch_results` returns empty when the downstream Computed row simply isn't there. If `(SortedSpikesDecodingSelection & key)` (or `ClusterlessDecodingSelection & key`) has 1 row on both sides but `(SortedSpikesDecodingV1 & key)` has 1 row on yours and 0 on theirs, their `populate(key)` either silently no-op'd (DataJoint silently does nothing when `key_source & key` is empty — no error, no warning), erred mid-run on a different key in the batch, or hasn't been executed yet. The merge master is then either missing the corresponding part row, or `merge_restrict_class` finds nothing to fetch from.

3. **Different upstream restriction.** "Same key on the same NWB" can still resolve to different upstream rows for the two users. A decoding selection key carries `position_group_name` (which references a `PositionOutput` `merge_id` indirectly through `PositionGroup`), `sorted_spikes_group_name` or `unit_filter_params_name` (which depend on a particular `SpikeSortingOutput.merge_id`), and an `encoding_interval` / `decoding_interval`. If their selection row resolved to a different `DLCPosV1` `merge_id` (e.g. a re-run of DLC produced a new merge_id and their selection points at the older or newer one), or a different `SpikeSortingRecording` UUID, the actual "what got computed" diverges even though the surface key looks identical. `(Selection & key).fetch1('KEY')` looks the same to a human; the part-table merge_ids underneath are not.

4. **Environment / package version drift between you and your labmate.** Spyglass actually records this — `common.UserEnvironment` (`src/spyglass/common/common_user.py:28`) stores per-user conda/pip exports keyed by `env_id`, with an MD5 `env_hash`, the full `env` blob, and a `has_editable` flag. Different `env_id`s on otherwise-identical selection rows are evidence the populate ran under different package versions, which can change either populate behavior (e.g. spike-sorting backend version) or output shape. The cheap diagnostic is to fetch both users' env blobs and diff against your currently-running env (rather than vaguely "check your env"):

   ```python
   from spyglass.common import UserEnvironment

   # If your selection rows carry an env_id, restrict by it:
   yours    = (UserEnvironment & {"env_id": YOUR_ENV_ID}).fetch1("env")
   theirs   = (UserEnvironment & {"env_id": THEIR_ENV_ID}).fetch1("env")

   # And compare to what's running right now in your shell.
   # `has_matching_env` does the per-package diff for you:
   UserEnvironment().has_matching_env(env_id=THEIR_ENV_ID, show_diffs=True)
   # or pull a single dependency:
   UserEnvironment().get_dep_version("spyglass-neuro", env_id=THEIR_ENV_ID)
   ```

   If `env_hash` differs between your and your labmate's `env_id`, you have a concrete divergence to investigate; if the hashes match, you can rule env drift out and move on.

## First diagnostic: inspect both users' Selection & key side-by-side

Before guessing, run the same restriction in both sessions and compare. This is a cardinality + content check, not a fetch:

```python
# In your session AND theirs (or via shared notebook), run on the same key.
from spyglass.decoding.v1.sorted_spikes import SortedSpikesDecodingSelection
from spyglass.decoding.v1.sorted_spikes import SortedSpikesDecodingV1
# (or the clusterless equivalents)

key = {"nwb_file_name": "j1620210710_.nwb", ...}   # the same key both ran

rel = (SortedSpikesDecodingSelection & key)
print(len(rel))                                    # cardinality on each side
rows = rel.fetch(as_dict=True)
for r in rows:
    print(r)                                       # exact selection row content

# Now check whether the downstream Computed actually has it:
print(len(SortedSpikesDecodingV1 & key))           # 1 on yours, 0 on theirs?
```

Diff the two `rows` outputs field-for-field. The cause usually announces itself in one of: a different `*_param_name`, a different `*_group_name`, a different interval-list name, or a different `env_id`.

If both sides show 1 row with byte-identical content, escalate to the merge layer:

```python
from spyglass.decoding import DecodingOutput
print(len(DecodingOutput.SortedSpikesDecodingV1 & key))   # part-row presence
# DecodingOutput.fetch_results uses merge_restrict_class internally — verify
# the merge_id you'd be fetching against:
DecodingOutput().merge_restrict_class(key).fetch1("KEY")
```

## What this is *not*

`cautious_delete` (the `.delete()` alias on `SpyglassMixin` tables) is a deletion gate — it enforces team-based permissions on `delete()` calls. It does **not** gate writes or `populate()`, so it cannot cause `fetch_results` to return empty. Don't reach for `super_delete()` / `force_permission=True` here; those are deletion-side escape hatches and irrelevant to this symptom.

Also: don't claim the two pipeline states "must be identical" — the symptom is direct evidence they aren't. The whole point of this check is to find *where* they diverge.

## Notes on what's verified vs. unconfirmed

- `UserEnvironment` schema and methods (`env_hash`, `env`, `has_editable`, `has_matching_env`, `get_dep_version`) are confirmed at `src/spyglass/common/common_user.py:28-540`.
- `DecodingOutput.fetch_results` is the `DecodingOutput`-only entry point and calls `merge_restrict_class(key).fetch_results()` (`src/spyglass/decoding/decoding_merge.py:74`).
- The exact selection-table class names (`SortedSpikesDecodingSelection` vs `ClusterlessDecodingSelection`) and the exact PK field names in your decoding params table (`decoding_param_name` etc.) depend on which decoding flavor you ran. Check `Table.heading.primary_key` on the actual selection class you used to confirm before substituting names into the snippets above.
