# Diagnosis: conda/pip OpenCV collision

You almost certainly have **two OpenCV installations stacked on top of each other** in the same environment — one from conda (`opencv` or `py-opencv`, conda-forge) and one from pip (`opencv-python`). When pip installed `opencv-python` on top of the conda build, the two packages dropped files into the same `cv2/` directory, and now `import cv2` is loading a Frankenstein mix where some submodules (here, `cv2.gapi`) are missing or stale. That's why `import spyglass.common`, which transitively imports `cv2` (via `dlc` / `deeplabcut` / `sleap` style deps), blows up with `AttributeError: module 'cv2' has no attribute 'gapi'`.

This is the single most common way OpenCV breaks in a conda env, and it matches your timeline exactly: it worked yesterday, then you `pip install opencv-python`'d, then it broke.

## What's happening, concretely

- conda installs OpenCV as `libopencv` + `py-opencv` (or `opencv`), with its own compiled `.so` files and a curated set of submodules.
- `pip install opencv-python` installs a wheel built by the OpenCV team that ships **its own** copy of those `.so` files into the same `site-packages/cv2/` directory.
- pip doesn't know about the conda metadata, so it overwrites some files, leaves others, and the resulting `cv2/__init__.py` ends up trying to load a binary that doesn't expose `gapi` (or, conversely, `__init__.py` from one version expects symbols the other build didn't compile in).
- Sometimes only `cv2.gapi`, `cv2.dnn`, or `cv2.aruco` go missing; sometimes the import dies outright. Yours is the "partial" failure mode.

There may also be an `opencv-python-headless` or `opencv-contrib-python` in the mix — they all install into the same `cv2/` namespace and **must not coexist**.

## Fix: pick one, remove the others

The reliable recipe is "remove every OpenCV in this env, then install exactly one." Do this **inside the conda env you use for Spyglass** — not base.

```bash
# 1) Activate the right env
conda activate <your-spyglass-env>

# 2) See what you actually have
pip list 2>/dev/null | grep -i opencv
conda list 2>/dev/null | grep -i opencv
python -c "import cv2; print(cv2.__file__); print(cv2.__version__)"
```

You will probably see something like:

```
opencv-python            4.10.x.x   (pip)
opencv                   4.x.x      (conda-forge)
```

Now remove **all** of them:

```bash
# 3) Uninstall every pip-installed OpenCV variant (run each, ignore "not installed")
pip uninstall -y opencv-python opencv-contrib-python opencv-python-headless opencv-contrib-python-headless

# 4) Remove conda's OpenCV too, so we start clean
conda remove -y opencv py-opencv libopencv  # any that exist; ignore "not installed"
```

Then verify the `cv2` directory is actually gone (pip sometimes leaves orphan files):

```bash
python -c "import cv2" 2>&1 | head -1   # should now be ModuleNotFoundError
# If a stale dir remains:
python -c "import sys, site; print(site.getsitepackages())"
# then `rm -rf <that path>/cv2` if it still exists.
```

### Then install exactly one OpenCV — preferably from conda-forge

Since your env is conda-managed and Spyglass + DLC have other compiled deps that play nicest with conda-forge:

```bash
conda install -c conda-forge opencv
```

If conda-forge "didn't seem to have what you wanted" yesterday, the cause is almost always that you didn't have `conda-forge` as a channel, or you were resolving against `defaults` which has a much older OpenCV. Add the channel explicitly:

```bash
conda config --env --add channels conda-forge
conda config --env --set channel_priority strict
conda install opencv
```

If you genuinely need a feature only in `opencv-python` (rare for Spyglass — DLC/SLEAP only need core + imgproc + videoio), then go the other direction: keep the env conda-managed for everything else, but make OpenCV pip-only:

```bash
conda remove -y opencv py-opencv libopencv
pip install opencv-python      # OR opencv-contrib-python — pick exactly ONE
```

Either path works. **The rule is: one OpenCV per env, from one package manager.**

## Verify the fix

```bash
python -c "import cv2; print(cv2.__version__); print(cv2.gapi)"
python -c "import spyglass.common; print('ok')"
```

Both should succeed without the `AttributeError`.

## Prevent this from recurring

A few habits that save a lot of pain in conda envs that mix scientific Python + DLC/SLEAP/Spyglass:

1. **Prefer conda-forge for anything with compiled C/C++ deps**: OpenCV, HDF5, FFmpeg, ffmpeg-python, GDAL, PyTorch (sometimes), Qt. Use pip for pure-Python packages and for things conda-forge genuinely doesn't ship.
2. **Never `pip install` something that's already conda-installed.** If `conda list` shows it, uninstall the conda version first, or install a different version through conda.
3. **Don't install into base.** You already know this from the project's CLAUDE rules, but it's especially relevant here — base + opencv variants is how envs become unrecoverable.
4. **When channel resolution surprises you**, check `conda config --show channels` and `channel_priority`. With `strict` + `conda-forge` first, you almost always get the modern build.
5. For ephemeral checks of "does package X work here," prefer `uvx --with X ...` or a throwaway `uv run --with X ...` so you don't dirty the working env.

## If it still fails after the fix

If `import cv2` works but `import spyglass.common` still throws on `cv2.gapi`, the import is most likely coming from `deeplabcut` / `dlc-live` / a related dep that pinned a specific OpenCV API. Check:

```bash
python -c "import cv2, sys; print(cv2.__version__, cv2.__file__)"
pip show deeplabcut 2>/dev/null | grep -i version
```

`cv2.gapi` exists in OpenCV 4.2+. If you somehow ended up on a 3.x build (some old conda channels still ship 3.4), upgrade:

```bash
conda install -c conda-forge 'opencv>=4.5'
```

That's the full picture — the `AttributeError` is a stacked-install symptom, and the fix is to clean both managers' OpenCVs out and install exactly one.
