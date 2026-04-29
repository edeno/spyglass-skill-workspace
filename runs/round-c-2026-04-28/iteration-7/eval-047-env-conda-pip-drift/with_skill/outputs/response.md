# Yes — your `pip install opencv-python` is the cause

This is a known Spyglass env-drift failure mode. `pip install <onepkg>` into an existing Spyglass conda env silently upgrades transitive dependencies (numpy, setuptools, pydot, networkx, opencv, …) and breaks the otherwise-working install. `AttributeError: module 'cv2' has no attribute 'gapi'` is one of the canonical symptoms of this — others in the same family include:

- `"ndx-franklab-novela is not a namespace"`
- `dj.Diagram(...)._repr_svg_` → `"Node names and attributes should not contain ':'"`
- `pkg_resources` errors after `setuptools>=82`
- `RuntimeError: Undefined plan with nthreads` from `pyfftw 0.13.0`

The "worked yesterday" + "I pip installed something last night" pairing is the giveaway.

## Don't do this

- Don't `pip install opencv-python==<some-older-version>` to "pin around" it.
- Don't `pip install opencv-contrib-python` or `opencv-python-headless` on top of what's there.
- Don't keep adding pip packages on top trying to satisfy the resolver.

Each of those just digs the env deeper into a state that doesn't match any environment Spyglass was tested against. The right move is to put the env back to the shape Spyglass expects.

## Fix — recreate the env from the current environment file

From your Spyglass source checkout:

```bash
# Update in place, pruning packages that aren't in the env file:
mamba env update --file environments/environment_min.yml --prune

# OR — for a clean rebuild (more reliable if --prune leaves cruft):
mamba env remove -n spyglass
mamba env create -f environments/environment_min.yml
conda activate spyglass
pip install -e .   # if you have a source checkout
```

(Substitute `conda` for `mamba` if you don't have mamba; mamba is just faster.)

`environment_min.yml` is the recommended default per Spyglass's `00_Setup` notebook. Use `environments/environment.yml` instead if you were previously on the full env, or `environment_dlc.yml` if you're using DeepLabCut (note that creates a different env name, `spyglass-dlc`).

After it finishes, restart your Python / Jupyter kernel and `import spyglass.common` should work again.

## Going forward

Don't `pip install <pkg>` piecemeal into a working Spyglass env — the next pip install will almost certainly overwrite a pinned version Spyglass relies on. If you genuinely need an extra package alongside Spyglass:

1. Check what pip *plans* to change first:
   ```bash
   pip install --dry-run opencv-python
   ```
   Look at the "Would install" lines — if pip wants to move `numpy`, `setuptools`, `networkx`, `opencv`, etc., that's the breakage you just hit.
2. Prefer adding the package to a *separate* conda env for the other project, not the Spyglass env.
3. If it has to coexist, prefer installing via `conda install -c conda-forge <pkg>` so the conda solver respects the existing pins, rather than letting pip steamroll them.

For "I just want opencv to read a video file" use cases, the opencv that ships with the Spyglass env (pulled in transitively by DLC / position deps) is already there — you usually don't need to install anything yourself.
