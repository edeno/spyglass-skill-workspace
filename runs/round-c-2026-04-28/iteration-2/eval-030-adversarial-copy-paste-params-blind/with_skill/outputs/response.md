# Not good to go — three independent problems with this plan

Short answer: **no, don't insert it as `ripple_param_name='default'` and don't move on.** Three things are wrong here, in increasing order of how silently they bite. Let's walk through each, then I'll show what to do instead.

---

## Problem 1: You can't defend params you don't understand

"Their analyses looked good" is not evidence that these values are right *for your experiment*. Different rats, different recording rigs, different brain states, different downstream questions all push these knobs in different directions. And if a populate fails, or a reviewer asks why you used `zscore_threshold=2.0` instead of `3.0`, "I copied it from a labmate" is not an answer you can give.

Here's what each field in that blob actually does (Kay detector — `src/spyglass/ripple/v1/ripple.py`, with the consumer `make()` body at ripple.py:280-330):

| Field | What it controls |
| --- | --- |
| `speed_name` (`'head_speed'`) | Which speed column to read out of the `PositionOutput` dataframe. `head_speed` is the Trodes-with-DLC convention; `speed` is the plain-Trodes convention. Pick the one that matches the position pipeline you actually populated. |
| `ripple_detection_algorithm` (`'Kay_ripple_detector'`) | Picks the detector. Registered options live in `RIPPLE_DETECTION_ALGORITHMS` at `ripple.py:23` — currently `Kay_ripple_detector` and `Karlsson_ripple_detector`. They differ in how the band-power envelope is thresholded; Kay is the more common Frank-lab default. |
| `speed_threshold` (`4.0` cm/s) | Movement-exclusion cutoff. Candidate ripple events are kept only when the animal's speed is `<= speed_threshold` at both event start and end (i.e. immobility). **Direction matters**: raising it (e.g. 4 → 10) *loosens* the immobility filter and admits *more* peri-movement events, which may not be true SWRs. Lower it for cleaner / fewer SWRs. |
| `zscore_threshold` (`2.0` SD) | The band-power cutoff used to flag a candidate event. Higher = stricter, fewer events. **Critical caveat**: the SD is estimated over the input interval, so if you run on a short slice, your SD estimate is bad and the threshold is meaningless. Run over an interval long enough to span representative behavior. |
| `minimum_duration` (`0.015` s = 15 ms) | Drops events shorter than this. Filters out brief blips that aren't real ripples. |
| `smoothing_sigma` (`0.004` s = 4 ms) | Gaussian smoothing window applied to the ripple-band envelope before thresholding. |
| `close_ripple_threshold` (`0.0` s) | Merges events whose endpoints are within this distance of each other. `0.0` means no merging. |

**Not in the blob (and intentionally):** `sampling_frequency` is *not* stored here. It flows in from `LFPBandV1.lfp_band_sampling_rate` at populate time (`ripple.py:286: sampling_frequency = ripple_lfp_nwb["lfp_band_sampling_rate"]`). So if your `LFPBandV1` row is at 1000 Hz vs. 1500 Hz, the detector adapts automatically — but only because you pinned the right `LFPBandV1` upstream.

If you want a sane baseline written by someone who *did* understand each field, read `RippleParameters.insert_default()` at `ripple.py:144` — that's the canonical reference. The `make()` body of `RippleTimesV1` at `ripple.py:280-330` shows exactly how each field flows into the detector call. And the upstream `ripple_detection` package (imported at `ripple.py:9`) is the algorithmic source of truth for the Kay detector.

## Problem 2: The name `'default'` collides with a row Spyglass already ships

This one will silently bite you regardless of whether the values are right.

`RippleParameters().insert_default()` (`ripple.py:144-178`) ships **two pre-populated rows** with `ripple_param_name='default'` and `ripple_param_name='default_trodes'`. The `'default'` row has *literally the same dict* as what your labmate sent you — `speed_name='head_speed'`, `Kay_ripple_detector`, `speed_threshold=4.0`, `minimum_duration=0.015`, `zscore_threshold=2.0`, `smoothing_sigma=0.004`, `close_ripple_threshold=0.0`. (Compare ripple.py:146-156 to your blob — identical.)

So your insert as `ripple_param_name='default'` will do one of two things, neither of which is what you want:

- If the call uses `skip_duplicates=True` (which `insert_default` itself does at `ripple.py:159`) — your insert silently no-ops and you don't notice. Downstream, you'll be running against the *shipped* `'default'`, not "your" `'default'`. They happen to be identical here, but you don't know that, and the next person who copies this pattern with a *different* blob will think they inserted their own params and actually be running on the shipped defaults.
- If the call uses `replace=True` — you overwrite the lab-shared row, and now everyone else who pinned `ripple_param_name='default'` on their `RippleTimesV1.populate(...)` is silently using *your* version.

Either way: don't name a row `'default'` in a Lookup table that already ships a row named `'default'`.

## Problem 3: Even without the collision, `'default'` fails grep-ability

A year from now, when someone (you, your labmate, a reviewer) grep's the codebase for `ripple_param_name='default'` and tries to figure out what params were actually used, the name tells them nothing. They have to open the table and inspect the blob.

Self-describing names encode the salient choices so that the name *survives a grep*. For this blob:

```
ripple_param_name = 'kay_speed4_zscore2'
```

— encodes detector + the two thresholds you'd change first if you were tuning. Other names in this style: `kay_speed10_zscore3` (looser immobility, stricter z), `karlsson_speed4_zscore2`, etc. You'd never confuse `kay_speed4_zscore2` for the shipped `'default'`, and you can grep for it across the lab's analysis notebooks.

---

## Before you insert, do a content-level search

A subtler trap: a row with these *exact* values may already exist under a *different* name. Names are free text, content is what `populate()` actually consumes. Two rows with identical content but different names mean half the lab's analyses pin to one name and half to the other — silent fragmentation of downstream queries.

Before inserting, check what's already in `RippleParameters`:

```python
from spyglass.ripple.v1 import RippleParameters

existing = RippleParameters.fetch(as_dict=True)
incoming = {
    "speed_name": "head_speed",
    "ripple_detection_algorithm": "Kay_ripple_detector",
    "ripple_detection_params": {
        "speed_threshold": 4.0,
        "minimum_duration": 0.015,
        "zscore_threshold": 2.0,
        "smoothing_sigma": 0.004,
        "close_ripple_threshold": 0.0,
    },
}
match = next(
    (row for row in existing if row["ripple_param_dict"] == incoming),
    None,
)
if match is not None:
    print(f"Equivalent params already exist as '{match['ripple_param_name']}' — reuse this name")
else:
    print("Genuinely new — proceed with an informative insert (e.g. 'kay_speed4_zscore2')")
```

In your specific case, this check will report a hit on the shipped `'default'` row (same blob), which means **you don't need to insert anything at all** — just reference `ripple_param_name='default'` (or `'default_trodes'` if you populated Trodes-only position with `speed` instead of `head_speed`) when you build your `RippleTimesV1.populate` key.

## What to actually do

1. Run `RippleParameters().insert_default()` if it hasn't been run on this DB — it ships the row your labmate's blob describes.
2. Read the field-by-field table above so you can defend each value when asked.
3. Decide on `'default'` vs `'default_trodes'` based on which speed column your `PositionOutput` actually has (`head_speed` for the DLC/Trodes pose pipeline; `speed` for plain Trodes-LED).
4. Use the chosen name in your `RippleTimesV1.populate` key. No new insert needed.
5. **If** you later want a non-default set (e.g. you decide `speed_threshold=10` for active-behavior ripples), insert that as `kay_speed10_zscore2` or similar — never as `'default_v2'` or `'my_params'`.

The principle, generalized: never copy-paste a params blob into a Lookup table without (a) understanding each field, (b) checking name collisions with shipped defaults, and (c) checking content collisions with existing rows. The skill's pre-insert loop and the two self-tests (understand-each-field, name-describes-content) are written exactly for this shape — see `feedback_loops.md` "Pre-insert check on parameter/selection tables" for the full pattern.
