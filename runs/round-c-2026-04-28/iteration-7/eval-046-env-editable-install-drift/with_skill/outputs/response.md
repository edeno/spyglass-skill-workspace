# Why the import fails after `git pull` — almost certainly editable-install drift

The class is in your source tree, but Python isn't loading Spyglass *from* your source tree. It's loading a different copy from the active environment's `site-packages` — and that copy doesn't have `NewlyAddedThing` yet.

This is the most common cause of "I see the symbol on disk but `ImportError`" right after a `git pull` on a Spyglass checkout.

## Step 1 — confirm where Python is loading Spyglass from

```python
import spyglass
print(spyglass.__file__)
```

What you want to see: a path under your checkout, e.g. `/Users/<you>/spyglass/src/spyglass/__init__.py`.

What you'll likely see if this is the bug: a path under `site-packages`, e.g. `.../envs/spyglass/lib/python3.11/site-packages/spyglass/__init__.py`. That's a non-editable copy, frozen at whatever commit was installed.

Cross-check the source you pulled:

```bash
cd ~/spyglass
git log -1 --oneline   # is the commit that added NewlyAddedThing actually here?
grep -n "class NewlyAddedThing" src/spyglass/spikesorting/v1/foo.py
```

## Step 2 — most likely root causes

In rough order of frequency:

1. **You never ran `pip install -e .`** on this checkout — `pip install spyglass-neuro` (or a plain `pip install .`) put a static copy into `site-packages`, and `git pull` updates source files Python isn't reading.
2. **You're in the wrong conda/venv environment.** The editable install was registered in environment A, but your current shell / Jupyter kernel is in environment B, where Spyglass is either missing or installed non-editably. Check with `which python` and `conda info --envs`.
3. **You have *both* a PyPI install and an editable install**, and the PyPI one is winning on `sys.path`. This happens when `pip install spyglass-neuro` ran first and `pip install -e .` was added later without uninstalling the PyPI build (or the editable install silently failed and left the PyPI one in place).
4. **Stale Python process / Jupyter kernel.** Source on disk is current, the editable install is correct, but the running interpreter has the old `spyglass.spikesorting.v1.foo` module cached from before the pull. Less likely to give a clean `ImportError` for a brand-new name (more often `AttributeError`), but worth ruling out.

## Step 3 — fix

Standard editable-install recipe:

```bash
conda activate spyglass            # or whichever env you use
cd ~/spyglass
git pull                           # already done, but harmless
pip uninstall spyglass-neuro       # ONLY if you ever installed from PyPI
pip install -e .                   # registers your checkout as the importable package
```

Then **restart the Python process or Jupyter kernel** — `importlib.reload` is not enough when a class is brand new in a submodule, because the parent package's import cache and `from ... import` bindings need to be rebuilt cleanly.

Verify:

```python
import spyglass
print(spyglass.__file__)                                 # under ~/spyglass/src/...
from spyglass.spikesorting.v1.foo import NewlyAddedThing # should now succeed
```

## Things to *not* do

- Don't edit the installed `site-packages/spyglass/...` files to "patch in" the class. `pip install -e .` will silently overwrite those edits, and on a shared install you'd desync your DB schema from what other lab members run. (Per the skill's directive: never edit the installed Spyglass package.)
- Don't `sys.path.insert(0, "~/spyglass/src")` as a workaround — it papers over the editable-install bug and you'll re-hit it on the next pull.
- Don't conclude the commit is broken until `print(spyglass.__file__)` confirms Python is actually reading from your checkout.

## If `print(spyglass.__file__)` *does* point at your checkout

Then editable-install drift isn't the cause and the diagnosis branches:

- **Stale `__pycache__`** in `src/spyglass/spikesorting/v1/`: `find ~/spyglass -name __pycache__ -exec rm -rf {} +` and retry.
- **The class is defined under an `if TYPE_CHECKING:` guard or behind a feature flag** — open `src/spyglass/spikesorting/v1/foo.py` and check it's at module top level, not inside a conditional.
- **The new commit has a syntax error or a circular import earlier in `foo.py`** that aborts module load before reaching the class. The traceback (full text, not just the last line) will name the real failure; share it if step 1 confirms you're loading from source.
- **Spyglass version pin drift** — the new commit may use a DataJoint or pynwb feature your env doesn't have, and the import error is downstream of *that* failure. The full traceback will name the missing symbol.

But step 1 (`print(spyglass.__file__)`) is the single command that decides which branch you're on — run it before anything else.
