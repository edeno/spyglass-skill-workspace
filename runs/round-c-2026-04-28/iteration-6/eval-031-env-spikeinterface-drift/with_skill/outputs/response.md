# `module 'spikeinterface' has no attribute 'WaveformExtractor'` — env drift, not a Spyglass bug

## First: did anything in your environment change?

Before I name a fix, can you confirm one thing: **did you (or `pip` / `conda` / a co-installed package) upgrade `spikeinterface` recently** — even indirectly? "Working last week, broken now, with no Spyglass change" almost always means the env moved out from under Spyglass. Useful one-liners:

```bash
python -c "import spikeinterface; print(spikeinterface.__version__)"
pip show spikeinterface | grep -E '^(Name|Version|Location):'
# Anything that depends on spikeinterface and might have pulled a newer one:
pip show probeinterface sortingview spikeinterface-gui mountainsort5 2>/dev/null
```

Common ways this happens by accident:

- A `pip install -U <something>` whose deps re-resolved `spikeinterface`.
- A fresh `pip install` of a sibling tool (e.g. `mountainsort5`, a notebook helper, a curation viewer) that has a looser SI pin than Spyglass and happily upgrades it.
- A teammate updated a shared `environment.yml` / Docker image.
- `conda update --all` or `pip install -U`.

If the answer is "no, I didn't touch anything," still run `pip show spikeinterface` and compare its version to the Spyglass pin (next section) — `WaveformExtractor` was removed *after* SI 0.99.x, so the only realistic way to land on this exact `AttributeError` in a previously-working env is a SpikeInterface bump out of Spyglass's pinned range.

## What's actually broken

This is a **version-coupling** failure, not a code or config bug.

- SpikeInterface removed the top-level `WaveformExtractor` class after the 0.99.x line and replaced the whole waveform-extraction surface with `SortingAnalyzer` / `create_sorting_analyzer(...)` in 0.100+.
- Spyglass's spike-sorting v1 pipeline still imports the old API at module top:

  ```python
  # src/spyglass/spikesorting/v1/burst_curation.py:8-11
  from spikeinterface.postprocessing.correlograms import (
      WaveformExtractor,
      compute_correlograms,
  )
  ```

  Other v1 modules (`metric_utils.py`, `metric_curation.py`) also reference `si.WaveformExtractor` in their signatures. The v0 modules do too (`spikesorting/v0/spikesorting_curation.py`, `spikesorting/v0/spikesorting_burst.py`).

- Your traceback says "blows up on import" before `populate(key)` runs anything — that's consistent: the failing `from spikeinterface... import WaveformExtractor` happens at module-load time as soon as anything pulls `spyglass.spikesorting.v1` (or v0) into the import graph, e.g. via `from spyglass.spikesorting.v1 import SpikeSorting`.

So Spyglass is pinned to the old API, your environment now has the new API, and the pipeline can't even be imported. Nothing about your data, your `key`, or the populate call is wrong.

## The pin lives in `pyproject.toml`, not in the skill

I won't paste a specific version string from memory because the pin moves over time and your local checkout is the source of truth. Read it directly:

```bash
grep -n -E 'spikeinterface' /path/to/spyglass/pyproject.toml
# also check, in case something diverged:
grep -n -E 'spikeinterface' /path/to/spyglass/environment.yml 2>/dev/null
```

You're looking for a line like `"spikeinterface>=0.99.x,<0.100"` in the `dependencies = [...]` block. Whatever that range says is the supported window — there is no benefit to landing anywhere else.

## Fix

**Reinstall SpikeInterface inside Spyglass's pinned range.** Substitute the actual range you found in `pyproject.toml` for the placeholder:

```bash
pip install 'spikeinterface>=0.99.1,<0.100'   # whatever pyproject.toml says
python -c "import spikeinterface; print(spikeinterface.__version__)"
# then re-import and retry:
python -c "from spyglass.spikesorting.v1 import SpikeSorting"
```

That's it — once the import resolves, `SpikeSorting.populate(key)` should work again.

## What *not* to do

- **Don't patch Spyglass to call `SortingAnalyzer`.** Editing `src/spyglass/spikesorting/v1/burst_curation.py`, `metric_utils.py`, `metric_curation.py`, etc. to bridge to the new API:
  - desyncs your install from every other lab running the schema,
  - silently reverts the next time you `pip install -e .`,
  - and the Spyglass policy is "don't edit the installed package" — push back if anyone suggests it.
- **Don't downgrade to the v0 spike-sorting pipeline as a "newer SI works there" workaround.** It doesn't — v0's code paths are *also* tied to the old SI API (and additionally hit other version-shift errors like `BinaryRecordingExtractor` -> `BinaryFolderRecording`). v0 is not maintained against modern SpikeInterface; the answer if you really need a newer SI is to migrate to v1, not to retreat to v0.
- **Don't `pip install -U` SpikeInterface again** to "see if a newer version fixes it." It won't — the symbol is gone, not renamed.

## If you specifically need a newer SpikeInterface

The honest answer is: you can't, while running Spyglass's current pipeline. The v1 pipeline is coupled to the 0.99-era API surface and will need an upstream Spyglass change to migrate to `SortingAnalyzer`. Until that happens, "stay in the pinned range" is the only supported configuration. If a newer SI is a hard requirement (e.g. for a sorter that only ships there), the right path is to open an issue / track Spyglass migration progress, not to monkey-patch locally.

## Quick checklist to confirm the fix

1. `pip show spikeinterface` -> Version is inside the `pyproject.toml` range.
2. `python -c "from spikeinterface.postprocessing.correlograms import WaveformExtractor"` -> no error.
3. `python -c "from spyglass.spikesorting.v1 import SpikeSorting"` -> no error.
4. Re-run `SpikeSorting.populate(key)`.

If step 4 still fails, the new error will be a different one (not the `WaveformExtractor` AttributeError) and we can triage it separately.

## Sources

- Skill reference: `skills/spyglass/references/dependencies.md` -> "SpikeInterface / Spyglass version coupling" (the symptom-to-SI-version table is what classifies your error).
- Spyglass source confirming v1 still uses the old API:
  - `src/spyglass/spikesorting/v1/burst_curation.py:8-11` (`from spikeinterface.postprocessing.correlograms import WaveformExtractor`)
  - `src/spyglass/spikesorting/v1/metric_utils.py:7,16,32,38,54,67` (`si.WaveformExtractor` in signatures)
  - `src/spyglass/spikesorting/v1/metric_curation.py:381,611` (`si.extract_waveforms(...)`, `si.WaveformExtractor` parameter)
- Source of truth for the pin: Spyglass repo `pyproject.toml` (`dependencies = [...]`, look for the `spikeinterface` line).
