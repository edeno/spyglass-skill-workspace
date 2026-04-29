Welcome to the lab. Here's a step-by-step walkthrough to get Spyglass running on your laptop and pointed at the lab's MySQL DB.

## 1. Prerequisites

You'll need:
- **Conda or mamba** (miniforge is fine). Pip-only installs work but conda makes the binary deps easier.
- **Git**.
- **Network access to `db.example.test:3306`**. If the lab DB isn't on the public internet, ask whoever runs IT whether you need a VPN or SSH tunnel.
- **The MySQL password for `testuser`** — get this from the lab admin out-of-band (Slack DM, password manager, etc.). Never paste it into a shared channel or commit it.

Quick connectivity sanity check before you install anything:
```bash
nc -vz db.example.test 3306
# or: telnet db.example.test 3306
```
If that hangs or refuses, no amount of Python setup will help — fix the network path first (VPN, firewall exception).

## 2. Create an isolated environment

Don't install Spyglass into base Python. Make a dedicated env:

```bash
# clone the source so you have it for reference & editable installs later
git clone https://github.com/LorenFrankLab/spyglass.git
cd spyglass

# create env from the repo's environment file (preferred — pins compatible deps)
mamba env create -f environment.yml   # or: conda env create -f environment.yml
mamba activate spyglass

# editable install of the spyglass package itself
pip install -e .
```

If `environment.yml` is missing or you want a leaner start, you can do:
```bash
mamba create -n spyglass python=3.10
mamba activate spyglass
pip install spyglass-neuro
```
but the env file is the supported path because Spyglass pulls in `datajoint`, `pynwb`, `spikeinterface`, `ghostipy`, `position_tools`, etc., several of which prefer conda-forge wheels.

## 3. Pick a base directory for analysis files

Spyglass stores raw NWB files, analysis NWB files, sorting outputs, video, etc. on disk — the DB only stores metadata + paths. Pick somewhere with lots of space (an external SSD is common):

```bash
mkdir -p ~/spyglass_data/{raw,analysis,recording,sorting,waveforms,spikesorting,tmp,video,deeplabcut}
```

You'll point Spyglass at `~/spyglass_data` via `SPYGLASS_BASE_DIR`. Ask the lab whether they expect you to mount a shared filesystem instead — many labs keep a single canonical `raw/` so everyone reads the same NWB files rather than duplicating them locally.

## 4. Configure DataJoint

Spyglass uses DataJoint to talk to MySQL. Create `~/.datajoint_config.json` (global) or `dj_local_conf.json` in your working directory (per-project, takes precedence):

```json
{
  "database.host": "db.example.test",
  "database.port": 3306,
  "database.user": "testuser",
  "database.password": "REPLACE_ME",
  "database.reconnect": true,
  "database.use_tls": true,
  "loglevel": "INFO",
  "safemode": true,
  "custom": {
    "spyglass_dirs": {
      "base": "/Users/testuser/spyglass_data"
    },
    "kachery_dirs": {
      "cloud": "/Users/testuser/spyglass_data/kachery_storage"
    }
  }
}
```

Notes:
- **Don't commit this file.** Add `dj_local_conf.json` and `.datajoint_config.json` to `.gitignore`. The password is plaintext.
- `database.use_tls` should match what the server requires; if connection fails with TLS errors, ask the admin whether the server has a cert configured.
- `safemode: true` means destructive ops (`.delete()`, `.drop()`) will prompt before executing — keep this on while you're learning.
- If you'd rather not store the password on disk, omit `database.password` and DataJoint will prompt interactively, or set `DJ_PASS` in your environment.

You can also configure programmatically once, then save:
```python
import datajoint as dj
dj.config["database.host"] = "db.example.test"
dj.config["database.port"] = 3306
dj.config["database.user"] = "testuser"
dj.config["database.password"] = "..."   # or use dj.set_password()
dj.config.save_global()    # writes ~/.datajoint_config.json
```

## 5. Verify the DB connection

Before touching Spyglass, confirm DataJoint alone can connect:
```python
import datajoint as dj
dj.conn()         # should print: Connected testuser@db.example.test:3306
dj.list_schemas() # should return a list of existing schemas
```

If this fails:
- `Access denied` → wrong password or your user doesn't exist on that server. Ask the admin.
- `Can't connect to MySQL server` → network / VPN / port issue, not a Python issue.
- TLS errors → flip `database.use_tls` and retry.

## 6. Set Spyglass environment variables

Spyglass reads `SPYGLASS_BASE_DIR` (and optionally `KACHERY_*` vars for the file-sharing layer). Add to your shell rc (`~/.zshrc` since you're on macOS-ish based on the working dir):

```bash
export SPYGLASS_BASE_DIR="$HOME/spyglass_data"
export DJ_SUPPORT_FILEPATH_MANAGEMENT=TRUE
```

Then `source ~/.zshrc` (or open a new shell) and `echo $SPYGLASS_BASE_DIR` to confirm.

## 7. Smoke-test Spyglass itself

```python
import spyglass
import spyglass.common as sgc

# This will trigger schema creation/connection. On a fresh user, you'll see
# DataJoint declare the schemas on the server (or, more likely, just connect
# to ones that already exist because someone else in the lab set them up).
sgc.Session()      # should print an empty or populated table listing
```

If `sgc.Session()` returns a table preview without erroring, you're connected and Spyglass is happy.

## 8. Ask the lab a few questions before you go further

A few things that vary lab-to-lab and you should not guess at:

1. **Do they share raw NWB files via a mounted filesystem, S3, or Kachery?** This determines whether you point `SPYGLASS_BASE_DIR/raw` at a shared mount or download per-session.
2. **What's the convention for `lab_member_name`?** When you insert yourself into `LabMember`, they'll have a naming pattern (`First Last` vs `flast`).
3. **Which schemas already exist?** Run `dj.list_schemas()` and compare with what `spyglass.common` etc. expect. If schemas are pre-populated you should *not* re-run any populate that mutates shared state.
4. **Is there a shared Kachery zone / cloud dir?** If the lab uses Kachery for figurl visualizations, they'll have `KACHERY_ZONE`, `KACHERY_CLOUD_DIR` to share.
5. **Write permissions.** Most labs give new users read-only on shared schemas at first. If `populate()` errors with "command denied to user", that's expected — you probably need a personal schema (`username_*`) for your own work.

## 9. First analysis sanity run

Once connected, work through the **`notebooks/`** directory in the spyglass repo you cloned — start with `0_intro.ipynb` and `01_Insert_Data.ipynb`. They walk through inserting a session, running a small pipeline, and fetching results, against either tutorial data or your lab's data. Don't try to populate a real session as your first action; use a tutorial NWB file.

## 10. Security hygiene

- Your DataJoint config file holds a DB password in plaintext. `chmod 600 ~/.datajoint_config.json`.
- Never paste the contents of that file into a chat, issue, or screenshot — scrub the password first.
- If you ever need to share your config for debugging, redact `database.password` (replace with `"***"`) before sending.

## TL;DR command sequence

```bash
# 1. clone & env
git clone https://github.com/LorenFrankLab/spyglass.git
cd spyglass
mamba env create -f environment.yml
mamba activate spyglass
pip install -e .

# 2. data dirs
mkdir -p ~/spyglass_data/{raw,analysis,recording,sorting,waveforms,spikesorting,tmp,video,deeplabcut}

# 3. dj config (edit JSON or via python+dj.config.save_global())
#    host=db.example.test, port=3306, user=testuser, password=<from admin>

# 4. shell env
echo 'export SPYGLASS_BASE_DIR="$HOME/spyglass_data"' >> ~/.zshrc
echo 'export DJ_SUPPORT_FILEPATH_MANAGEMENT=TRUE' >> ~/.zshrc
source ~/.zshrc

# 5. verify
python -c "import datajoint as dj; dj.conn(); print(dj.list_schemas())"
python -c "import spyglass.common as sgc; print(sgc.Session())"
```

If step 5 prints schemas and an empty/populated `Session` table, you're set up. From there, work through the tutorial notebooks and ask the lab admin which schemas you should *not* be writing to.
