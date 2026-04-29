# Target sampling rate for `LFPSelection` with downstream ripple analysis

## Short answer

**Pick `target_sampling_rate = 1000` Hz.** It is the conventional choice for ripple-band (150–250 Hz) analysis in hippocampal LFP and is what most Spyglass / Frank-lab pipelines use.

## Why 1000 Hz

1. **Nyquist headroom.** Ripples top out near 250 Hz. The Nyquist criterion says you need a sample rate strictly greater than 2× the highest frequency of interest, i.e. > 500 Hz. 1000 Hz gives you a 4× margin over the upper ripple edge, which leaves comfortable room for:
   - the analog/digital anti-alias filter roll-off (filters are not brick walls),
   - a clean band-pass at 150–250 Hz without ringing artifacts at the band edges,
   - any envelope/Hilbert step downstream (you want the carrier well below Nyquist so the analytic signal is well-behaved).

2. **It's the de-facto Spyglass default for LFP.** Raw ephys is typically acquired at 20 kHz or 30 kHz. The `LFPV1` / `LFPElectrodeGroup` populate step decimates to a `target_sampling_rate` that the user picks on `LFPSelection`. 1000 Hz is the value used throughout the Spyglass tutorials and the Frank-lab notebook examples, and downstream tables that consume LFP (e.g. ripple detection, theta phase) are written assuming this rate.

3. **Compatible with ripple detection downstream.** Spyglass's `RippleLFPSelection` / `RippleParameters` / `RippleTimes` pipeline (and the underlying `ripple_detection` package) is built and tested against ~1 kHz LFP. Picking the same rate avoids an extra resample step and matches the parameter defaults (e.g. smoothing windows, minimum-duration thresholds) that ship in `RippleParameters`.

4. **Storage and compute are reasonable.** 1 kHz × 32–256 channels × hours of recording is tractable on disk and in memory, and decimating from 30 kHz to 1 kHz is a clean integer factor of 30 (or 20 from 20 kHz acquisition), which keeps the polyphase/decimation filter well-conditioned.

## When you might deviate

- **If you also care about high-gamma (>250 Hz) or sharp-wave-ripple waveform detail**, bump to 1500 or 2000 Hz. Some labs analyzing fine ripple morphology (peak-to-trough timing, intra-ripple frequency) prefer 2 kHz.
- **If you only care about theta/delta**, you could go lower (e.g. 500 Hz), but then you cannot reuse the LFP for ripples — so don't, given your stated downstream plan.
- **Never go below ~600 Hz** for ripple analysis; you will alias the upper ripple band.

## What to check before populating

- Confirm the raw `Raw` sampling rate divides cleanly by your target (decimation factor should be an integer; if not, Spyglass uses `scipy.signal.resample_poly` which is fine but adds a tiny bit of filter overhead).
- Confirm the `FirFilterParameters` entry referenced by `LFPSelection` has a passband consistent with 1 kHz output (typically a low-pass around 400 Hz for 1 kHz LFP).

## Bottom line

```python
LFPSelection.insert1({
    ...,
    "target_sampling_rate": 1000,   # Hz — standard for ripple (150–250 Hz) analysis
})
```
