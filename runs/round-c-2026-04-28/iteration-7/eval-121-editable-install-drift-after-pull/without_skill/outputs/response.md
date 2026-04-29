A fresh `git pull` on its own does not normally remove a class like `SortedSpikesDecodingV1` — that class still exists in `spyglass/decoding/v1/sorted_spikes.py` on master. So this is almost certainly an *environment* problem, not a code problem. Let me lay out what's most likely happening and how to confirm.

## The most likely cause: stale install vs. updated source

You have two copies of Spyglass on your machine right now:

1. The **source tree** you just `git pull`-ed (e.g. `~/spyglass/src/spyglass/...`).
2. The **installed package** Python actually imports from (somewhere under `site-packages/`).

If Spyglass was installed with a regular `pip install .` (not `-e`), `pip install` from a wheel, or via conda, then `import spyglass` resolves to a *snapshot* in `site-packages` — your `git pull` updated the source tree but the installed copy is unchanged. Worse: if the installed copy is *older* than the version where `SortedSpikesDecodingV1` was added (or the module path it lives in), the import fails exactly as you describe.

A second flavor of the same problem: you have a `__pycache__/sorted_spikes.cpython-*.pyc` left over from before the pull, and somewhere on `sys.path` an old `spyglass/` directory is being preferred over the new one.

A third flavor: an editable install (`pip install -e .`) whose `.egg-link` / `*.pth` points at a *different* checkout than the one you just pulled in.

## How to confirm in 30 seconds

Run this in the same Python you use for Spyglass:

```python
import spyglass, spyglass.decoding.v1.sorted_spikes as m
print(spyglass.__file__)
print(spyglass.__version__)
print(m.__file__)
print([n for n in dir(m) if "Decoding" in n])
```

What you're looking for:

- **`spyglass.__file__`** — does this point inside the repo you just pulled, or inside `site-packages/spyglass/`? If it's `site-packages`, your install is *not* tracking your checkout.
- **`m.__file__`** — same question for the submodule. If it points at a stale copy, that's your answer.
- **`dir(m)`** — confirms whether the class is missing entirely, or just renamed/moved. (As of current master, `SortedSpikesDecodingV1` is defined in `spyglass/decoding/v1/sorted_spikes.py`.)

Then, separately:

```bash
cd /path/to/your/spyglass/checkout
git log -1 --oneline
git status
grep -n "class SortedSpikesDecodingV1" src/spyglass/decoding/v1/sorted_spikes.py
```

If the `grep` finds the class in your checkout but `m.__file__` points elsewhere, the pull did not break anything — your environment is just importing a different copy.

## Fixes, in order of how often they're the right one

1. **Re-install editable against the checkout you just pulled**, from inside an isolated env (conda env or venv — never base):
   ```bash
   pip install -e .
   ```
   This rewires `site-packages` so it follows your source tree. After `git pull`, you generally don't need to reinstall *unless* `pyproject.toml` / `setup.cfg` / entry points changed — but doing it once now will make future pulls "just work."

2. **Clear bytecode caches** in case a stale `.pyc` is winning:
   ```bash
   find /path/to/spyglass -name __pycache__ -type d -exec rm -rf {} +
   ```

3. **Check for a duplicate install** shadowing the editable one:
   ```bash
   python -c "import spyglass; print(spyglass.__file__)"
   pip show spyglass
   pip list | grep -i spyglass
   ```
   If you see *both* an editable entry and a regular install, `pip uninstall spyglass` repeatedly until `pip show spyglass` reports nothing, then `pip install -e .` once.

4. **Check you pulled the branch you think you pulled.** `SortedSpikesDecodingV1` is the v1 API; if you happen to be on a very old branch or a feature branch where v1 was removed/renamed, the import will fail by design. `git log -1` and `git branch --show-current` will tell you.

5. **Migration check (less likely but worth ruling out):** if upstream moved the symbol, the import path changes. Search the new tree:
   ```bash
   grep -rn "class SortedSpikesDecodingV1" src/spyglass/
   ```
   Whatever file that prints is the current canonical path. If it's no longer under `decoding/v1/sorted_spikes.py`, update your import.

## Bottom line

`git pull` did not "break" your code — it updated your source, but Python is almost certainly still importing an older installed copy (or a stale cache). The diagnostic is `print(spyglass.__file__)`; the fix is usually `pip install -e .` inside your Spyglass conda/venv environment. Don't do this in base Python — keep it in the same isolated environment you normally use for Spyglass work.
