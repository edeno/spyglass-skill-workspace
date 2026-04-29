## Short answer

No — please don't swap in `.fetch()[0]`. That looks like it just "picks any row," but on `PositionOutput` it picks an arbitrary entry from a *different source pipeline* every time, and the rows it's picking between aren't equivalent. "Any position for that session" is almost never what downstream code actually needs. Let's fix the real problem (your restriction is too loose) instead.

## Why your `fetch1()` is failing

`PositionOutput` is a **merge master**. Its only primary key is `merge_id` (UUID); `nwb_file_name` is *not* on the master at all — it lives on the four part tables that feed it (source: `src/spyglass/position/position_merge.py:31-35`):

- `PositionOutput.TrodesPosV1` — LED tracking via Trodes
- `PositionOutput.DLCPosV1` — DeepLabCut pose
- `PositionOutput.CommonPos` — legacy `IntervalPositionInfo`
- `PositionOutput.ImportedPose` — pre-computed pose imported from NWB

Two things are happening with your line:

```python
(PositionOutput & {'nwb_file_name': 'j1620210710_.nwb'}).fetch1()
```

1. **The `& {'nwb_file_name': ...}` is a silent no-op on a merge master.** DataJoint only matches on attributes in the heading, and the master heading is just `(merge_id, source)`. So the `&` step doesn't actually restrict to your session — it returns the *whole* `PositionOutput` table. (Common Mistake #6 in this skill, "silent no-op on merge masters.")
2. `fetch1()` then sees N>1 rows and raises `expected one tuple`. The error is correct; it's just pointing at a different problem than you think.

## Why `.fetch()[0]` is the wrong patch

Because the `&` was a no-op, `.fetch()[0]` doesn't pick "the first row for your session" — it picks the first row of **the entire `PositionOutput` table**, which is almost certainly from a different session entirely.

Even if you fix the restriction so it scopes to this session (using `merge_restrict` / `merge_get_part`, see below), `[0]` is still dangerous on a merge master:

- A given session can have rows from **multiple sources** (Trodes + DLC + CommonPos + ImportedPose) and from **multiple intervals / param sets within each source**.
- The sources are not interchangeable: Trodes is centroid-of-LEDs, DLC is body-part keypoints, CommonPos is the legacy pre-v1 path, ImportedPose came from upstream and may use different timestamps and a different sampling rate.
- Even within one source, different `*_params_name` values mean different smoothing / filtering / interpolation choices.
- `PositionOutput.fetch1_dataframe()` is a **dispatcher** — it routes to the part class. `ImportedPose` doesn't implement `fetch1_dataframe`, so a `[0]` that happens to land on an ImportedPose merge entry will then fail at the dispatch step (`src/spyglass/position/position_merge.py:81-92`).

So `.fetch()[0]` either silently gives you data from the wrong session, or silently gives you the wrong source for this session, or blows up later when the dispatcher hits a part that doesn't support what you're asking for. None of those are "any position for that session."

## What to do instead

Pick one of these two paths.

### Path A — recommended: tighten the restriction to exactly one row

Look at what's actually there and add PK fields until you have a unique row:

```python
from spyglass.position import PositionOutput

# 1) Use merge_restrict (NOT bare `&`) to scope to your session.
sess = {'nwb_file_name': 'j1620210710_.nwb'}
view = PositionOutput.merge_restrict(sess)
print(len(view))                              # how many candidates exist?
view.fetch(as_dict=True)                      # inspect source / interval / params
```

That gives you rows annotated with their `source` (`TrodesPosV1` / `DLCPosV1` / `CommonPos` / `ImportedPose`) plus the upstream PK fields (interval name, params name, etc.). Pick the source you actually want, and add fields until `len(...) == 1`:

```python
key = {
    'nwb_file_name': 'j1620210710_.nwb',
    'source': 'TrodesPosV1',
    'interval_list_name': 'pos 1 valid times',         # whichever you want
    'trodes_pos_params_name': 'default',               # or your params name
}
assert len(PositionOutput.merge_restrict(key)) == 1
df = (PositionOutput
      & PositionOutput.merge_get_part(key).fetch1('KEY')
     ).fetch1_dataframe()
```

The exact secondary fields differ by source — Trodes uses `trodes_pos_params_name`, DLC uses `dlc_si_cohort_selection_name` / `dlc_pos_params_name`, ImportedPose uses synthesized `interval_list_name`s. Use the `view.fetch(as_dict=True)` step above to discover the right field names for your case.

### Path B — if you genuinely want source-agnostic, pick the source explicitly

If the analysis really doesn't care which pipeline produced the position (rare — usually you do care), still make the choice explicit instead of letting `[0]` choose for you. Resolve through `merge_get_part` with a stated preference:

```python
sess = {'nwb_file_name': 'j1620210710_.nwb'}

# Stated preference order — pick the first source that has rows.
for src in ('TrodesPosV1', 'DLCPosV1', 'CommonPos', 'ImportedPose'):
    key = {**sess, 'source': src}
    if len(PositionOutput.merge_restrict(key)):
        merge_key = PositionOutput.merge_get_part(key).fetch1('KEY')
        break
else:
    raise RuntimeError(f"No PositionOutput rows for {sess['nwb_file_name']}")

df = (PositionOutput & merge_key).fetch1_dataframe()
```

You'll still need to narrow further if more than one interval/params row exists for that source. The point is the choice is *visible in the code* — a future reader (or you in three months) can see which source got picked and why, and the failure mode if there's >1 candidate within the chosen source is a loud `fetch1` error, not silent wrong data.

> Caveat on `ImportedPose`: it doesn't implement `fetch1_dataframe`. If your fallback chain lands on it, call `PositionOutput.fetch_pose_dataframe()` (which dispatches correctly) or read directly from `ImportedPose().fetch_pose_dataframe(key)`. Source: `src/spyglass/position/v1/imported_pose.py:110`.

## TL;DR

- `.fetch()[0]` doesn't fix the bug; it hides it. The `& {'nwb_file_name': ...}` was already a silent no-op, so `[0]` is picking from the whole table, not your session.
- The right fix is to scope through `PositionOutput.merge_restrict({'nwb_file_name': f})`, inspect `.fetch(as_dict=True)`, then add `source` + the source's PK fields until exactly one row matches; resolve to the master via `merge_get_part(key).fetch1('KEY')` and fetch through `(PositionOutput & merge_key).fetch1_dataframe()`.
- If you really want source-agnostic, encode the source preference explicitly — don't delegate that choice to array indexing.
