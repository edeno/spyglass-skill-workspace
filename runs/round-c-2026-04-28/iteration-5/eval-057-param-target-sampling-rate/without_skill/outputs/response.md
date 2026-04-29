# `LFPSelection.target_sampling_rate` — what it controls and why it matters for ripple analysis

## What the field controls

`LFPSelection` (in `spyglass.lfp.v1.lfp`) is the parameter table you populate before `LFPV1.populate()` runs. The `target_sampling_rate` field tells the LFP pipeline **what sampling rate, in Hz, the output LFP should be written at** after filtering and decimation.

Concretely, when `LFPV1.make()` runs it:

1. Loads the raw broadband ephys at its native rate (typically 20–30 kHz for SpikeGadgets / Neuropixels).
2. Applies the LFP band filter from `FirFilterParameters` (a low-pass / band-pass FIR — by default a "LFP 0–400 Hz" filter, occasionally a narrower 0–125 Hz one).
3. **Decimates** the filtered signal down by an integer factor chosen so that the resulting rate is as close as possible to `target_sampling_rate` (without going below it / without aliasing past the filter cutoff).
4. Writes the decimated, filtered trace to a new NWB `ElectricalSeries` and registers it in `LFPV1` / `LFPOutput`.

So `target_sampling_rate` is essentially a **knob for the output LFP rate**, expressed as a target rather than a hard value because the decimation factor has to be an integer divisor of the raw rate. The achieved rate (stored as `lfp_sampling_rate` on the populated row) will be the closest realizable rate at or above your target.

The default in the Frank-lab pipeline is **1000 Hz**, which is the rate the downstream ripple, theta, and spectral pipelines were designed against.

## What goes wrong if you set it too low for ripple analysis

Hippocampal sharp-wave ripples are a **150–250 Hz** oscillation (some pipelines widen the band to ~125–300 Hz). Two independent things break if `target_sampling_rate` sits too low.

### 1. Nyquist — the band you want literally isn't there

Nyquist says you can only represent frequencies up to `fs / 2`. If you set `target_sampling_rate = 500`, your Nyquist is 250 Hz and the upper edge of the ripple band sits right at it. If you set it to **400 Hz, 300 Hz, or the often-tempting 250 Hz**, the upper part of the ripple band is *gone* — and worse, anything above Nyquist that wasn't fully suppressed by the anti-alias / LFP filter gets **aliased** back into lower frequencies, contaminating the band you do keep. The downstream `LFPBandV1` ripple-band filter (typically 150–250 Hz) will then be filtering a signal whose passband is partially missing or polluted, and the ripple envelope you compute from it will not faithfully represent the true 150–250 Hz power.

Practical rule of thumb: you want the LFP rate to be at least **~3× the highest frequency of interest**, so for a 250 Hz ripple ceiling that's **≥ 750 Hz, and 1000 Hz is the safe, conventional choice**. Going to 1250 or 1500 Hz is also fine if your raw rate divides evenly; going below 1000 Hz for ripple work is asking for trouble.

### 2. Re-running is expensive and the merge-table chain is sticky

`LFPV1` feeds `LFPOutput` (a merge table), which feeds `LFPBandV1`, which feeds `RippleParameters` / `RippleTimesV1`. If you populate the whole chain at 500 Hz and only later notice the ripple envelope looks attenuated or weirdly noisy, you have to:

- insert a new `LFPSelection` row with a higher `target_sampling_rate`,
- re-`populate()` `LFPV1`,
- insert a new `LFPOutput` merge entry,
- re-populate `LFPBandV1` for the ripple band against the new merge key,
- re-populate ripple detection on top of that.

None of that is hard, but it's a multi-table, multi-hour rerun on real ephys that you avoid by picking the rate correctly the first time.

### 3. Subtler issue: filter design and edge effects

Most ripple-band FIR filters in the Spyglass `FirFilterParameters` table are designed assuming a 1000 Hz input. If you feed `LFPBandV1` a 500 Hz LFP, the filter coefficients (and their transition bands, group delay, ringing) are no longer in their designed regime. You'd need a separate `FirFilterParameters` entry tuned for the lower rate. Forgetting to do this is a quiet bug — `populate()` won't necessarily fail, it'll just produce a filtered trace whose passband and phase response don't match the documented 150–250 Hz spec.

## Recommended setting

For any pipeline that will eventually run ripple, theta, gamma, or spectral analyses up to a few hundred Hz, set:

```python
LFPSelection.insert1({
    ...,
    "target_sampling_rate": 1000,   # Hz; matches default ripple/theta filters
})
```

If your raw rate is 30 kHz, this gives a clean integer decimation factor of 30. If you have a specific high-frequency need (e.g. fast gamma or 300 Hz ripple work), bump it to 1250 or 1500 Hz and use a matching FIR filter parameter set — but don't go below 1000 Hz for ripple work.

## How to verify after population

After you populate, check the *achieved* rate (it may not exactly equal your target):

```python
(LFPV1 & key).fetch1("lfp_sampling_rate")
```

and confirm it's ≥ ~3× the upper edge of any band you plan to extract downstream. If it isn't, fix `LFPSelection` and re-populate the chain before doing any ripple science on top of it.
