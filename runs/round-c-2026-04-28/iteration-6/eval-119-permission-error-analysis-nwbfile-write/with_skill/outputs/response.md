# `PermissionError` writing `j1620210710_<hash>.nwb` — filesystem layer, not Spyglass code

## Diagnosis: this is a filesystem / group-permission problem

The path `/stelmo/nwb/analysis/j1620210710_/...` is the resolved `analysis_dir` derived from `SPYGLASS_BASE_DIR` (`SpyglassConfig.analysis_dir`, `src/spyglass/settings.py:563-565`; resolution chain: `dj.config['custom']['spyglass_dirs']` → `SPYGLASS_*_DIR` env vars → `<base>/analysis`, `settings.py:133, 178`). At `populate()` time, `LFPV1.make()` writes a new `AnalysisNwbfile` into a per-session subdirectory under that tree. The kernel returned `Errno 13` because **your Linux user can't write to `/stelmo/nwb/analysis/j1620210710_/`** — Spyglass surfaced it, but every byte of the failure is below the Python layer.

The fact that other lab members can `populate` fine is the strongest single clue: the database, `SPYGLASS_BASE_DIR`, the schema, and `LFPV1` itself all work. They are in the lab's shared Unix group; you are not, or your shell's `umask` differs from theirs. Don't reach for `chmod -R 777 /stelmo/nwb/analysis` — that removes the permission gate entirely (any user / any process can clobber arbitrary analysis NWBs), and a lab admin will revert it the next time they audit.

## Diagnose three layers, in order

### (1) Group membership

Lab installs typically own `analysis/` under a shared Unix group (commonly `spyglass`, `franklab`, or similar). Confirm which group, and confirm your account is in it:

```bash
id                                       # what groups am I in?
ls -ld /stelmo/nwb/analysis              # owner:group on the analysis tree
ls -ld /stelmo/nwb/analysis/j1620210710_ # and on the per-session dir that's failing
```

If the group listed by `ls -ld` is missing from `id`'s output, that's the answer — ask the admin / sysadmin to add you (`sudo usermod -aG <group> <you>`), then **log out and log back in** for the new group to apply to your shell. Other lab members can `populate` because they were added to that group when their account was created; you weren't.

### (2) Group-write bit + setgid on the directory

Even if you're in the group, the directory must (a) have group-write (`g+w`) and (b) have the **setgid bit** (`g+s`, shown as `s` in the group-execute slot of `ls -ld`, e.g. `drwxrws---`) so newly-created files inherit the directory's group rather than your primary group. Without setgid, the *first* file you create will be owned by your primary group and unreadable by others.

```bash
ls -ld /stelmo/nwb/analysis/j1620210710_   # want drwxrws--- (or drwxrwsr-x), group=<lab group>
```

If the dir is `drwxr-x---` or the group is wrong, the admin fix is targeted, not blanket:

```bash
# admin runs:
sudo chown :spyglass /stelmo/nwb/analysis/j1620210710_   # or your lab's group
sudo chmod 2775     /stelmo/nwb/analysis/j1620210710_    # 2 = setgid; 775 = rwxrwxr-x
```

(Use `2770` / `drwxrws---` if the lab restricts read access to group members.) Many labs running Spyglass on a shared filesystem operate a cron or admin-run script that periodically re-asserts setgid + group-write on the whole `analysis/` tree as new per-session subdirs are created — if yours does, escalate to that script's owner rather than chmod-ing piecemeal.

### (3) Your shell's `umask`

Files Spyglass writes inherit your shell's `umask`. Most lab convention is `umask 002` so newly-created files come out group-writable (`-rw-rw-r--`). If a personal dotfile sets `umask 022`, your files will be `-rw-r--r--` — readable but **not writable** by other lab members. Then the next person to `populate` into a directory you created hits the same `Errno 13` you're hitting now (possibly the originating cause: someone else with `umask 022` created `j1620210710_/` before you).

```bash
umask                          # in the shell where you launch Python / Jupyter
# expect 0002; if you see 0022, fix it:
echo "umask 002" >> ~/.bashrc  # or ~/.zshrc, matching your shell
```

Re-source the rc file (or restart the shell) and confirm `umask` reports `0002` before re-running `populate()`.

## Quick triage script

Run this in the failing shell and compare to a working colleague's output:

```bash
id
umask
ls -ld /stelmo/nwb/analysis
ls -ld /stelmo/nwb/analysis/j1620210710_
python -c "import os; print('writable:', os.access('/stelmo/nwb/analysis/j1620210710_', os.W_OK))"
```

The diff between your output and theirs almost always points to exactly one of layers (1)–(3).

## Don't

- **`chmod -R 777 /stelmo/nwb/analysis`** — removes the group-permission gate that was protecting the lab's analysis files. Any user (including unrelated processes on the host) can rewrite or delete arbitrary analysis NWBs. A lab admin will revert this.
- **Don't bypass with `super_delete()` / `force_permission=True` / `chmod`-ing only the one failing file.** This isn't `cautious_delete`'s team-permission check (Common Mistake #5 in SKILL.md) — it's the filesystem refusing the write. The Spyglass-side overrides won't change what the kernel does.
- **Don't edit `src/spyglass/settings.py` to point `analysis_dir` somewhere else** as a workaround. The path is correct; the permissions on the path aren't.

## What to ask the admin (if (1) or (2) is the cause)

> "I'm getting `PermissionError: [Errno 13]` writing into `/stelmo/nwb/analysis/j1620210710_/`. `id` shows I'm not in `<group from ls -ld>`. Can you (a) add me to the group and (b) confirm the per-session directories under `/stelmo/nwb/analysis/` have setgid + group-write (`chmod 2775`) so new files inherit the right group?"

That's the targeted fix; the umask change is something you can make yourself in your `.bashrc` / `.zshrc`.

---

References used: SKILL.md routing (runtime debugging vs setup-troubleshooting; this is a `populate()` failure but the root cause is config / filesystem layer), [setup_troubleshooting.md § `AccessError` / `PermissionError` on a shared installation](../../../skills/spyglass/references/setup_troubleshooting.md), [setup_config.md § Setting the Base Directory](../../../skills/spyglass/references/setup_config.md). Source verified in `src/spyglass/settings.py:133, 178, 563-565`.
