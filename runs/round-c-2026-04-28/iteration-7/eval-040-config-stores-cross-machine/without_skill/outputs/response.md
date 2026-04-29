The error message `FileNotFoundError: Inaccessible local directory` is a DataJoint error, not a Spyglass one specifically — and it's almost always about **how the path is registered with DataJoint's external store on each machine**, not about whether the filesystem is actually mounted.

## The short answer

Spyglass uses **DataJoint external stores** (specifically the `raw` and `analysis` stores, plus a few others like `kachery`) to track NWB files. Each store is configured with a **local filesystem path** in your DataJoint config (`dj.config["stores"]`). When `fetch_nwb()` runs, DataJoint:

1. Looks up the store name attached to the file blob in the database (e.g. `raw` or `analysis`).
2. Resolves the file's relative path against `dj.config["stores"]["raw"]["location"]` (or `["stage"]`) **on the current machine**.
3. Verifies that directory exists and is readable. If not, you get `Inaccessible local directory`.

So the database row is the same on both machines, but the **path string** in your config has to point at wherever your HPC mounts the lab filesystem — which is almost never the same path as on the workstation.

## What's typically different between the two machines

Likely culprits, roughly in order:

1. **Different mount point.** Workstation mounts the lab share at e.g. `/mnt/lab` or `/data`, the HPC mounts the same NFS/Lustre/GPFS volume at e.g. `/n/groups/labname/` or `/scratch/labname/`. Your DataJoint config has the workstation path baked in.
2. **Login node has restricted filesystem visibility.** On many HPCs, the **login node** does not mount the same scratch/project filesystems as compute nodes (or mounts them lazily / read-only / via a different path). Your code may actually work inside a Slurm job but fail on the login node. Worth testing with `srun` / `sbatch` before assuming the path is wrong.
3. **`dj_local_conf.json` is per-machine, not synced.** The config file is read from the current working directory or `~/.datajoint_config.json`. If you only updated it on the workstation, the HPC has stale or default values.
4. **`SPYGLASS_BASE_DIR` env var differs.** Spyglass derives default store paths from `SPYGLASS_BASE_DIR` (and friends like `SPYGLASS_RAW_DIR`, `SPYGLASS_ANALYSIS_DIR`). If that env var is unset on the HPC or points somewhere that doesn't exist on the login node, the stores resolve to a bad path.
5. **Symlink / automount differences.** `/mnt/lab` on the workstation might be a symlink chain that resolves fine; the HPC might require the canonical path. DataJoint calls `os.path.isdir` on the configured location, which follows symlinks but won't auto-trigger an automounter that hasn't fired yet.
6. **Permissions on the login node.** The directory exists but your HPC user account isn't in the right group, or the share is exported only to compute nodes. `Inaccessible` covers "exists but unreadable" too.

## How to diagnose

On the HPC login node, in the same Python session you'd run `fetch_nwb()`:

```python
import datajoint as dj
import os, pprint

pprint.pprint(dj.config["stores"])
print("SPYGLASS_BASE_DIR =", os.environ.get("SPYGLASS_BASE_DIR"))
print("SPYGLASS_RAW_DIR =", os.environ.get("SPYGLASS_RAW_DIR"))
print("SPYGLASS_ANALYSIS_DIR =", os.environ.get("SPYGLASS_ANALYSIS_DIR"))

for name, store in dj.config["stores"].items():
    loc = store.get("location") or store.get("stage")
    print(name, loc, "exists:", os.path.isdir(loc) if loc else None,
          "readable:", os.access(loc, os.R_OK) if loc else None)
```

The store whose `location` fails `isdir` / `access` is the one raising. Compare those paths to what `mount | grep lab` (or `df -h`) shows actually mounted on the login node.

Also run on **both** machines and diff:

```bash
stat -L /path/from/store/location
realpath /path/from/store/location
```

to confirm they resolve to the same underlying volume.

## How to fix

Pick the option that matches your setup:

- **Per-machine config (simplest).** Keep a separate `dj_local_conf.json` on the HPC with the HPC mount paths. Don't try to share one config file across machines.
- **Drive everything from env vars.** Set `SPYGLASS_BASE_DIR` (and `SPYGLASS_RAW_DIR` / `SPYGLASS_ANALYSIS_DIR` if your raw and analysis directories aren't co-located under base) in your HPC shell rc file, and let Spyglass populate `dj.config["stores"]` from there at import time. This is the recommended pattern — your code stays identical across machines.
- **Symlink the HPC path to match the workstation path** (e.g. `ln -s /n/groups/labname /mnt/lab`). Works only if you have write access to `/` or `/mnt`, which you usually don't on an HPC.
- **Run on a compute node, not the login node.** If the login node genuinely can't see `/scratch` or `/n/groups`, an interactive `srun --pty bash` session will. Many HPCs explicitly document that login nodes don't mount project storage.

## One thing to rule out first

Before changing any config, just check whether the directory is visible at all:

```bash
ls -ld "$(python -c 'import datajoint as dj; print(dj.config[\"stores\"][\"raw\"][\"location\"])')"
```

If that fails with "No such file or directory" or "Permission denied" at the shell level, it's a mount/permissions issue on the login node, not a Spyglass config issue. If it succeeds at the shell but DataJoint still complains, it's the config path string that's wrong (or there are multiple stores and a *different* one — `analysis`, `kachery`, `temp` — is the offender).
