# Why `fetch_nwb()` works on workstation but raises `FileNotFoundError: Inaccessible local directory` on the HPC

Short answer: this is **cross-machine mount drift in `dj.config['stores']`**, not a filesystem problem. Even though both machines mount the same lab filesystem, they almost certainly mount it at **different absolute paths**, and the persisted DataJoint config baked in the workstation's path. DataJoint's "Inaccessible local directory" comes from the *stores* block, which holds an absolute path that has to resolve on the *current* machine.

## What's actually happening

`dj.config['stores']` looks roughly like this:

```json
{
  "stores": {
    "raw":      {"protocol": "file", "location": "/data/spyglass/raw",      "stage": "/data/spyglass/raw"},
    "analysis": {"protocol": "file", "location": "/data/spyglass/analysis", "stage": "/data/spyglass/analysis"}
  }
}
```

That `location` is an **absolute path on the local machine** — it is not a logical name the DB resolves per host. If your workstation mounts the share at `/data/spyglass/...` but the HPC login node mounts the same share at `/mnt/lab/spyglass/...` (or `/cluster/...`, `/n/holyscratch/...`, etc.), the persisted config still says `/data/spyglass/...` on the HPC, and DataJoint can't open the file. `fetch_nwb()` is the first thing that hits a stored path, so that's where you see the failure.

Spyglass *does* refresh `dj.config['stores']` from local env vars, but only when `SpyglassConfig.load_config()` runs (`_set_dj_config_stores()` in `src/spyglass/settings.py:268, 316`). The precedence it uses (`settings.py:133`) is:

1. explicit `SpyglassConfig(base_dir=...)`
2. `dj.config['custom']['spyglass_dirs']`
3. env vars (`SPYGLASS_*_DIR`)
4. resolved `<base>/<X>`

The catch: **the persisted config file (`~/.datajoint_config.json` or `dj_local_conf.json`) does NOT auto-regenerate when env vars change.** If on the HPC you didn't import `spyglass.settings` before the failing call, or you have no `SPYGLASS_BASE_DIR` set, the in-memory `stores` block is whatever the persisted config says — i.e., the workstation's paths.

This is the canonical "fresh-machine setup gap": `dj.config['stores']` is the one piece of state that doesn't travel with `git pull` / `pip install`, because it is filesystem-path-shaped.

## Diagnose it

On the HPC login node, before doing any populate/fetch:

```python
import os, datajoint as dj
from spyglass.settings import SpyglassConfig  # forces env_defaults + stores refresh

assert 'stores' in dj.config, 'dj.config has no stores block'
raw_loc = dj.config['stores']['raw']['location']
print('stores.raw.location =', raw_loc)
print('SPYGLASS_BASE_DIR   =', os.environ.get('SPYGLASS_BASE_DIR'))
print('exists?             =', os.path.isdir(raw_loc))
```

If `raw_loc` doesn't start with the HPC's mount path (or doesn't exist), you've confirmed it.

You can also run the bundled checker, which walks the precedence ladder and tells you which tier won:

```bash
python skills/spyglass/scripts/verify_spyglass_env.py --check base_dir_resolved
```

And to inspect the persisted config without leaking the password:

```bash
python skills/spyglass/scripts/scrub_dj_config.py
```

(don't `cat` / `Read` `~/.datajoint_config.json` directly — it can hold a plaintext password and the stores block is what you want to see anyway).

## Fix

Write a per-machine config on the HPC that points at the HPC's mount paths. Either:

```bash
# Easiest: re-run the installer in config-only mode on the HPC
python scripts/install.py --config-only --base-dir /mnt/lab/spyglass    # whatever the HPC path actually is
```

or programmatically:

```python
from spyglass.settings import SpyglassConfig

SpyglassConfig(base_dir="/mnt/lab/spyglass").save_dj_config(
    save_method="global",                  # writes ~/.datajoint_config.json
    base_dir="/mnt/lab/spyglass",
    database_user="<your-db-user>",
)
```

Use `save_method="local"` instead if you want a project-scoped `dj_local_conf.json` in the cwd.

If individual subdirectories live in different places on the HPC (common — e.g. raw on a slow archive, analysis on scratch), override per-directory:

```bash
export SPYGLASS_BASE_DIR=/mnt/lab/spyglass
export SPYGLASS_RAW_DIR=/cluster/archive/spyglass/raw
export SPYGLASS_ANALYSIS_DIR=/scratch/$USER/spyglass/analysis
```

…then save the config so the stores block on disk matches.

## Two related gotchas worth flagging

- **Import order.** Make sure `spyglass.settings` (or any `spyglass.*` module) is imported *before* the first `fetch_nwb()` / `fetch1_dataframe()` call on the HPC. `_set_dj_config_stores()` only runs on Spyglass import; if you started with bare `datajoint`, the in-memory stores never got refreshed from env vars.
- **VSCode-over-SSH on the HPC.** Remote VSCode kernels frequently drop env vars set in `~/.bashrc`. If your `SPYGLASS_BASE_DIR` is set in bashrc but the kernel doesn't see it, you'll keep hitting this even after "fixing" it. Prefer storing the paths in `dj.config['custom']['spyglass_dirs']` + `dj.config.save_global()` so all shells / kernels see the same source of truth.

## TL;DR

`dj.config['stores']` is **machine-local absolute paths**. Both machines mount the share, but at different mount points. The persisted config carries the workstation's paths; on the HPC, either set `SPYGLASS_BASE_DIR` (and any per-dir overrides) and re-save the global config, or run `python scripts/install.py --config-only --base-dir <hpc-path>`. Verify with the assertion snippet above before running `fetch_nwb()` again.
