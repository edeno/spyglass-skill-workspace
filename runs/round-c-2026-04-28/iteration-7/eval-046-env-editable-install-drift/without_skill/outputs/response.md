# Why `git pull` updated your source but `import` still fails

Short version: the Python interpreter you're importing from is **not actually loading code from `~/spyglass/`**. `git pull` only changes files on disk — it doesn't rewire what Python imports. If your environment was set up with a regular `pip install spyglass-neurodata` (or a non-editable `pip install .`), there's a *copy* of the old Spyglass sitting in `site-packages/`, and that copy is what `import spyglass.spikesorting.v1.foo` resolves to. The new `NewlyAddedThing` exists in your checkout but not in the installed copy, so the import legitimately can't find it.

This is the single most common cause. Below is how to confirm it and the few less-common variants to rule out.

## Step 1 — find out which `spyglass` Python is actually importing

In the same environment where the import fails:

```bash
python -c "import spyglass, os; print(spyglass.__file__); print(os.path.realpath(spyglass.__file__))"
```

Then compare against your checkout:

```bash
realpath ~/spyglass/src/spyglass/__init__.py
```

Three possible outcomes:

1. **Path points into `site-packages/`** (e.g. `/.../envs/spyglass/lib/python3.X/site-packages/spyglass/__init__.py`) — this is the editable-install-missing case. Your `git pull` updated `~/spyglass/`, but the import is reading the unrelated installed copy. Fix in Step 2.
2. **Path points into `~/spyglass/src/spyglass/__init__.py`** — Python *is* reading your checkout, so something else is going on. Skip to Step 3.
3. **`ModuleNotFoundError` on the `import spyglass` line itself** — Spyglass isn't installed in this env at all; you've been running it from a different env. Activate the right env (`conda activate spyglass` or whichever you normally use) and retry.

## Step 2 — reinstall as editable so `git pull` is enough

If Step 1 showed a `site-packages/` path, do an editable install pointing at your checkout:

```bash
# activate the env you normally use Spyglass in, then:
pip uninstall spyglass-neurodata        # remove the non-editable copy
cd ~/spyglass
pip install -e .                        # editable install
```

After this, `python -c "import spyglass; print(spyglass.__file__)"` should print a path under `~/spyglass/src/spyglass/...`, and any future `git pull` will be picked up immediately with no reinstall.

Verify the new symbol is now visible:

```bash
python -c "from spyglass.spikesorting.v1.foo import NewlyAddedThing; print(NewlyAddedThing)"
```

Note: if the new commit also added a dependency in `pyproject.toml` / `setup.cfg`, `pip install -e .` will pull that in. A bare `git pull` cannot do that — that's another reason editable installs aren't a complete substitute for periodic reinstalls when dependencies move.

## Step 3 — if the path *does* point at your checkout but import still fails

Less common, but worth ruling out in this order:

1. **Stale `__pycache__`** for that subpackage. Unlikely to cause an `ImportError` on a brand-new symbol (Python re-reads `.py` when its mtime is newer than the `.pyc`), but harmless to clear:
   ```bash
   find ~/spyglass -name __pycache__ -type d -exec rm -rf {} +
   ```
2. **You're inside an already-running interpreter / Jupyter kernel.** Python caches modules in `sys.modules` for the life of the process. A `git pull` that happened *after* the kernel started won't be visible until you restart the kernel (or `importlib.reload`, but reload is fragile across submodules — restart is cleaner).
3. **`foo.py` imports something at module top level that itself fails.** Python reports this as `ImportError`, and the message can look like the symbol is missing when really the whole module failed to load. Read the *full* traceback, not just the last line — look for an inner `ImportError` / `ModuleNotFoundError` from a transitive import (a new dependency the commit added, a renamed sibling module, etc.). If a new dep was added, `pip install -e .` from Step 2 fixes it; otherwise install whatever the inner error names.
4. **`NewlyAddedThing` is defined inside an `if TYPE_CHECKING:` block, behind a feature flag, or only conditionally exported.** Open `~/spyglass/src/spyglass/spikesorting/v1/foo.py` and confirm it's a top-level `class NewlyAddedThing:` — not nested inside a function, an `if`, or a `try`/`except ImportError` fallback that's silently being taken.
5. **Two checkouts, wrong one on `sys.path`.** If you have more than one Spyglass clone (e.g. `~/spyglass/` and `~/code/spyglass/`), `python -c "import spyglass; print(spyglass.__file__)"` tells you definitively which one wins. Adjust the editable install to point at the checkout you actually pulled into.
6. **The new commit isn't actually in your working tree.** `git pull` can be a no-op (already up to date on a different branch, detached HEAD, merge conflict left unresolved, etc.). Confirm:
   ```bash
   cd ~/spyglass
   git log -1 --oneline -- src/spyglass/spikesorting/v1/foo.py
   grep -n "class NewlyAddedThing" src/spyglass/spikesorting/v1/foo.py
   ```

## Why this happens so often

`pip install spyglass-neurodata` (or a plain `pip install .` from a clone) **copies** the package into `site-packages/`. Your git checkout becomes a development source that has nothing to do with what gets imported. People conflate "I have the source" with "Python uses the source", and the two only become equivalent after `pip install -e .`. From that point on, the checkout *is* the installed package — edits and `git pull`s are visible immediately (modulo the caveats in Step 3).

Run the Step 1 diagnostic; in the overwhelming majority of cases the fix is the `pip install -e .` in Step 2.
