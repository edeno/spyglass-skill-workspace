# Setting up Spyglass on your laptop against the example lab's remote DB

Welcome to the lab. Your situation — joining an existing lab whose MySQL server is already running and curated by an admin — is the easiest case to set up: you only need a working Python env on your laptop, the DataJoint config pointed at `db.example.test`, and a local data directory. You do **not** need to run a database yourself.

Here's the end-to-end walkthrough. The commands assume macOS or Linux (Windows is experimental for Spyglass).

---

## 0. Before you start — confirm a few things with the lab

A couple of things only your lab admin / a senior member can tell you. Ask before you start typing:

1. **Your DB password.** They created the MySQL account `testuser@db.example.test`. They should hand you the password out-of-band (not over email/Slack ideally). I'll refer to it below as `<your-db-password>` — never paste it into a file you'll commit.
2. **The base data directory convention.** Some labs share a network mount everyone reads from (e.g. `/data/example-lab/spyglass_data`); others have each user keep a local `~/spyglass_data`. This is the `SPYGLASS_BASE_DIR` and it is **machine-local** — it's the directory raw NWBs and analysis outputs live under on *your* laptop. If the lab uses a shared mount, mirror their convention; otherwise `~/spyglass_data` on your laptop is fine.
3. **The Kachery zone (optional, only if you need data sharing).** If you'll be sharing analysis files via Kachery / FigURL, ask for the lab's `KACHERY_ZONE` name and ask the admin to add your GitHub username to it. Skip this for now if you're just running analyses; you can come back to it.

---

## 1. Prerequisites

You need:

- Python 3.10–3.12 (check `pyproject.toml` `requires-python` if you want the exact range).
- `conda` or `mamba` (miniforge is recommended — it gives you `mamba` and the conda-forge channel out of the box).
- ~10 GB free for a minimal install, ~25 GB for full.
- Network access to `db.example.test:3306` from your laptop. If you're off the lab network this typically means VPN — confirm with the admin. A quick reachability check:

  ```bash
  nc -vz db.example.test 3306
  ```

  If that hangs or refuses, fix networking before going further.

On macOS specifically, if `pyfftw` later complains about no PyPI wheels, install it from conda-forge before `pip install -e .`:

```bash
conda install -c conda-forge pyfftw pybind11
```

---

## 2. Recommended path — the automated installer

Spyglass ships an installer script that handles the conda env, Spyglass install, DataJoint config, and the local directory tree in one shot. It's the canonical path per `QUICKSTART.md`. For your case (joining a lab with a remote DB), use the `--remote` flags:

```bash
git clone https://github.com/LorenFrankLab/spyglass.git
cd spyglass

python scripts/install.py \
  --remote \
  --db-host db.example.test \
  --db-port 3306 \
  --db-user testuser \
  --base-dir ~/spyglass_data
```

What this does, in order:

1. Checks Python / conda / disk.
2. Creates a conda env named `spyglass` from `environments/environment_min.yml` (the minimal default; pass `--full` if you want all optional pipeline deps from the start — you can always upgrade later).
3. Runs `pip install -e .` inside that env so `import spyglass` works.
4. Prompts you for the DB password (or reads `SPYGLASS_DB_PASSWORD` from the env). Enter the password the lab admin gave you. **Do not** pass it on the command line via `--db-password` — that puts it in your shell history.
5. Writes `~/.datajoint_config.json` with `database.host=db.example.test`, `database.user=testuser`, `database.port=3306`, `database.use_tls=true` (auto-enabled for remote hosts), and the `stores` block pointing at `~/spyglass_data/{raw,analysis}`.
6. Creates the directory tree under `~/spyglass_data/` (`raw/`, `analysis/`, `recording/`, `spikesorting/`, `waveforms/`, `tmp/`, `video/`, `export/`, etc.).
7. Runs `python scripts/validate.py` to confirm import + DB connection both work.

Then activate the env:

```bash
conda activate spyglass
```

If the installer's validation step succeeded, you're done. Skip to step 5 below.

---

## 3. If the installer prompts about Docker / local DB

You're connecting to a remote DB, so **don't** pick `--docker`. The Docker path runs a MySQL 8 container on `localhost:3306` for solo dev — irrelevant when the lab already runs `db.example.test`.

---

## 4. Manual fallback (if the installer breaks)

If `scripts/install.py` errors out, you can do the same work in pieces. There's also a `00_Setup.ipynb` notebook in the repo that walks through this manually.

```bash
# 4a. Create the env and install Spyglass
git clone https://github.com/LorenFrankLab/spyglass.git
cd spyglass
mamba env create -f environments/environment_min.yml
conda activate spyglass
pip install -e .
```

```bash
# 4b. Pick a base directory for your local data
export SPYGLASS_BASE_DIR=~/spyglass_data
mkdir -p "$SPYGLASS_BASE_DIR"
# Persist it so future shells see it:
echo 'export SPYGLASS_BASE_DIR=~/spyglass_data' >> ~/.bashrc   # or ~/.zshrc
```

```python
# 4c. Generate ~/.datajoint_config.json from Python.
# Run this once inside the activated env. It will NOT prompt for the
# password; you'll provide that interactively the first time you connect
# (preferred), or via the DJ_PASS env var (also fine).
from spyglass.settings import SpyglassConfig

SpyglassConfig(base_dir="~/spyglass_data").save_dj_config(
    save_method="global",          # writes ~/.datajoint_config.json
    base_dir="~/spyglass_data",
    database_user="testuser",
    database_host="db.example.test",
    database_port=3306,
)
```

That writes the config but **omits the password** — which is the safer default. When you first connect, DataJoint will prompt for it interactively, or you can put it in your shell environment as `DJ_PASS` (or `SPYGLASS_DB_PASSWORD` for the installer). Storing the plaintext password inside the JSON file works too, but every `cat`/`Read`/screen-share exposes it; if you do it, run `chmod 600 ~/.datajoint_config.json`.

You'll also want TLS on for a remote host:

```python
import datajoint as dj
dj.config["database.use_tls"] = True
dj.config.save_global()
```

---

## 5. Verify the install

In the activated env:

```bash
python scripts/validate.py
```

You want exit code 0. The five checks it runs:

| Check | Critical | What it verifies |
|---|---|---|
| Python version | yes | meets `pyproject.toml` minimum |
| conda/mamba | yes | package manager available |
| Spyglass import | yes | `import spyglass` works |
| SpyglassConfig | no | config loads, base dir set |
| Database connection | no | DataJoint can connect to `db.example.test` |

Critical failures mean you can't proceed. The two non-critical ones being green is what tells you the lab DB connection actually works.

A quick one-liner sanity check from Python:

```python
import datajoint as dj
from spyglass.common import Session   # ensures spyglass.settings runs first
print("connected:", dj.conn().is_connected)
print("sessions visible:", len(Session.fetch(limit=5)))
```

If `Session.fetch(limit=5)` returns rows, you're seeing the lab's data.

---

## 6. A few things to know before you start running analyses

- **Never `cat` or `Read` `~/.datajoint_config.json` directly** — it can hold a plaintext DB password (and possibly Kachery / S3 credentials). If you need to inspect the config, use the bundled scrubber: `python skills/spyglass/scripts/scrub_dj_config.py`. It masks secrets and prints the rest.
- **Don't edit the installed Spyglass source (`src/spyglass/...`)** to "fix" something for yourself. Spyglass schemas are shared with the rest of the lab via the DB; local edits desync you from everyone else, and `pip install -e .` will silently revert them on the next pull. If something genuinely needs changing, open an issue or PR upstream.
- **Don't `pip install <onepkg>` into the Spyglass env** to add a side dependency. It quietly upgrades pinned transitive deps (`numpy`, `setuptools`, `pydot`, `networkx`) and breaks otherwise-working installs in non-obvious ways. If you must, run `pip install --dry-run <pkg>` first; better, recreate the env from `environments/environment_min.yml`.
- **Cross-machine `stores` drift.** `dj.config['stores']` carries absolute filesystem paths to your local `raw/` and `analysis/` dirs. If you later move `SPYGLASS_BASE_DIR` or use a different laptop, regenerate the config (`SpyglassConfig(...).save_dj_config(save_method="global", ...)`); don't just edit `SPYGLASS_BASE_DIR` and expect fetches to follow.
- **The `.delete()` method on Spyglass tables is team-gated.** It enforces lab-permission rules and will refuse to drop sessions owned by other lab members. That's a feature, not a bug — if you hit `PermissionError`, talk to the owner; do not reach for `super_delete()` or `force_permission=True`.

---

## 7. First steps after the install works

The repo has a numbered tutorial-notebook series under `notebooks/`:

- `00_Setup.ipynb` — re-checks config (good sanity-check after install).
- `01_Concepts.ipynb` — DataJoint + Spyglass mental model.
- `02_Insert_Data.ipynb` — first NWB ingestion (you may not need this if the lab has already ingested everything you'll work on).
- `04_Merge_Tables.ipynb` — the merge-table pattern that's everywhere in Spyglass; worth reading before you start querying pipelines.

Discovery query to see what's already in the DB:

```python
from spyglass.common import Session, IntervalList

Session.fetch(limit=10)                       # nwb_file_names available
IntervalList & {"nwb_file_name": "<one>"}     # intervals for one session
```

From there, pick a pipeline (spike sorting, position, LFP, ripple, decoding, …) and open the matching `1*` / `2*` / `3*` / `4*` notebook.

---

## TL;DR

```bash
git clone https://github.com/LorenFrankLab/spyglass.git
cd spyglass
python scripts/install.py \
  --remote \
  --db-host db.example.test \
  --db-port 3306 \
  --db-user testuser \
  --base-dir ~/spyglass_data
conda activate spyglass
python scripts/validate.py
```

Enter your password at the prompt. If the validator is green, you're connected — open `notebooks/01_Concepts.ipynb` and you're off.
