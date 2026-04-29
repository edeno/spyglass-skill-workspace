# Almost certainly editable-install drift, not a broken pull

The import path `from spyglass.decoding.v1.sorted_spikes import SortedSpikesDecodingV1` is the canonical, current location for that class — your `git pull` did not delete it. What's most likely happening is that `python` is loading a **pip-installed** Spyglass from `site-packages` and ignoring your freshly pulled checkout. After a pull that moves or renames symbols, the installed package and the source tree go out of sync and you get exactly this `ImportError: cannot import name`.

## Confirm it in 30 seconds

```python
import spyglass
print(spyglass.__file__)
```

- If that path is under `.../site-packages/spyglass/...` instead of your source checkout (e.g. `~/spyglass/src/spyglass/...`), the running interpreter is **not** using your pulled code. That's the bug.
- Cross-check the source checkout is at the commit you expect:

  ```bash
  cd <your spyglass source>
  git log -1 --oneline
  ```

You can also run the skill's bundled diagnostic, which checks editable-install / version-pin drift along with config and DB connection in one shot:

```bash
python skills/spyglass/scripts/verify_spyglass_env.py
```

## Fix — re-establish the editable install

```bash
conda activate spyglass                    # whichever env you use
cd <your spyglass source>
git pull                                   # already done in your case
pip install -e .                           # <-- the step that's missing
```

Then **restart the Jupyter kernel / Python process** so the old import cache clears. Re-running the import in the same kernel will keep failing because Python caches `spyglass` in `sys.modules`.

## One extra wrinkle if you originally `pip install`'d the published package

If at some point you ran `pip install spyglass-neuro` (the PyPI build), that takes precedence over an editable install in the same env. Uninstall it first, then redo the editable install:

```bash
pip uninstall spyglass-neuro
pip install -e .
```

## Why I'm confident this isn't "the pull broke something"

- `SortedSpikesDecodingV1` is the canonical class for sorted-spikes decoding and lives in `spyglass.decoding.v1.sorted_spikes`; the skill's decoding reference and the `from spyglass.decoding.v1.clusterless import ClusterlessDecodingV1` symmetry both point to that exact import path being current.
- "`ImportError: cannot import name` immediately after `git pull`" is the textbook signature of editable-install drift: the source moved (a new module, a renamed re-export, a moved symbol), but `site-packages` still has the previous layout, and `python` resolves the import against `site-packages`.
- A genuine repo breakage from a `git pull` would also break other Spyglass users on the same commit; the much more common cause is the local install state, not the pull.

## Less likely, but worth ruling out if `pip install -e .` doesn't fix it

1. **Wrong env active.** `which python` and `conda env list` — make sure the env you `pip install -e .`'d into is the one running the failing import.
2. **A name collision.** A local file or directory called `spyglass.py` / `spyglass/` on `sys.path` (e.g. in your CWD) would shadow the package. `python -c "import spyglass; print(spyglass.__file__)"` will show this immediately.
3. **DataJoint version drift.** Spyglass occasionally starts using a new DataJoint feature without bumping the floor; if the traceback names a missing *DataJoint* symbol rather than a Spyglass one, run `pip install -U datajoint` (target ≥ 0.14.6 as of late 2025).
4. **Schema column drift.** This shows up as `KeyError: '<column>' is not in the table heading` after a pull, **not** as `ImportError`. So it's not your symptom — but if it appears after the install fix, that's a separate `Table().alter()` problem that needs an admin and the version's `CHANGELOG.md`.

So: you didn't break anything with the pull. Re-run `pip install -e .` from your source checkout, restart the kernel, and the import should resolve.
