# `PermissionError [Errno 13]` writing an analysis NWB file

This is almost certainly **not a Spyglass / Python bug**. The traceback is the
kernel telling you the OS refused the `open(..., 'w')` system call when
`LFPV1.populate()` tried to create a new analysis NWB file. The fact that
*other lab members can populate fine* on the same table, same data, same code
is the giveaway — the only thing different is **you** (your user account, your
groups, your shell). The fix lives at the **filesystem permission layer**, not
in the populate code.

A few orienting facts about the path:

- `/stelmo/nwb/analysis/...` is a shared lab filesystem. In a typical Frank-lab
  Spyglass install this is the directory Spyglass writes new
  `AnalysisNwbfile`s into.
- The path is derived from Spyglass's config — specifically the `analysis_dir`
  that hangs off `SPYGLASS_BASE_DIR` (see `SpyglassConfig` in
  `src/spyglass/settings.py`). Spyglass picks the path; the kernel decides
  whether you're allowed to write there. So changing your code or
  `SPYGLASS_BASE_DIR` won't help unless the underlying directory actually
  permits writes from your account.
- The per-session subdirectory (`j1620210710_/`) was created earlier — likely
  by another user when *they* ingested that session. That's the directory you
  now can't write into.

Diagnose in three layers, in this order, before changing anything. Resist the
urge to "just chmod it" — see the warning at the bottom.

---

## Layer 1: Group membership

Almost every shared-filesystem lab install has `analysis/` owned by a shared
unix group (commonly `spyglass`, `franklab`, `lab`, etc.) and relies on group
permissions, not world permissions, to let the lab write into it. If you're
not in that group, you're locked out.

```bash
id                                       # what unix groups am I in?
ls -ld /stelmo/nwb/analysis              # owner:group on the top-level dir
ls -ld /stelmo/nwb/analysis/j1620210710_ # owner:group on the offending subdir
```

You're looking for the group printed by `ls -ld` to also appear in the output
of `id`. If it doesn't — for example `ls -ld` shows `drwxrws--- root spyglass`
but `id` doesn't list `spyglass` — that's the bug. Ask the sysadmin to add
your user to the group:

```bash
sudo usermod -a -G spyglass <yourname>   # or whatever the group is
# you must log out and back in (or `newgrp spyglass`) for it to take effect
```

This is the single most common cause and it perfectly fits the symptom: every
existing lab member is already in the group; you're a new account that wasn't
added. Check this layer first.

---

## Layer 2: Group-write bit + setgid on the directory

Even if you *are* in the group, the directory itself has to grant the group
write permission, and ideally have the **setgid** bit set so newly-created
files inherit the group of the directory rather than your primary group
(otherwise a file *you* create ends up owned by your primary group, and the
*next* lab member can't overwrite it — the same bug, just shifted by one
person).

```bash
ls -ld /stelmo/nwb/analysis/j1620210710_
# what you want to see, roughly:
# drwxrws---  2 someuser spyglass  4096 ... j1620210710_
#    ^^^^^^
#    g+w (the second 'w') AND g+s (the 's' instead of 'x' in the group block)
```

Decoding the mode bits in the group field:

- `rwx` — group can read/write/execute, no setgid. New files inherit *your*
  primary group. Bad in a shared lab dir.
- `rws` — group can read/write/execute **and** setgid is on. New files
  inherit the directory's group. This is what you want.
- `r-x` — group can read but not write. This will produce exactly the Errno
  13 you saw.
- `r-s` — setgid on but no group-write. Also produces Errno 13.

If the bits are wrong, the admin (or whoever owns the directory) fixes it
with:

```bash
# fix group ownership and turn on setgid + group-write
sudo chgrp -R spyglass /stelmo/nwb/analysis
sudo chmod -R g+rwX     /stelmo/nwb/analysis      # g+w on dirs and files; X = +x only on dirs
sudo find /stelmo/nwb/analysis -type d -exec chmod g+s {} \;   # setgid on every dir

# numeric equivalent for a single dir:
sudo chmod 2775 /stelmo/nwb/analysis/j1620210710_   # leading 2 = setgid; 775 = rwxrwxr-x
```

Why `2775` and not `2777`: the trailing `5` (`r-x` for "other") keeps random
non-lab accounts from poking around — only the `spyglass` group can write.
Don't drop that bit (see warning).

---

## Layer 3: Your shell's `umask`

Files Spyglass writes inherit the **umask** of the shell / process that ran
`populate()`. The default umask on most Linux distros is `022`, which makes
new files `rw-r--r--` — i.e. **not group-writable**. That bites you the
*second* time around: your file lands in the shared dir with the right group
(thanks to setgid from layer 2) but with no group-write bit, so the next
person who tries to overwrite or delete it gets the same Errno 13.

It probably isn't what's failing on the very first call (the directory itself
is the gate there), but it's why labs standardize on `umask 002`:

```bash
umask                                # show current value (often 0022)
umask 002                            # for this shell only — yields rw-rw-r-- on new files
```

If your lab convention is `002`, add it to your `~/.bashrc` (or `~/.zshrc`):

```bash
# in ~/.bashrc
umask 002
```

Then `source ~/.bashrc` (or open a new shell) before re-running `populate()`.
Note: some labs put `umask 002` in a system-wide profile (`/etc/profile.d/`)
specifically so users don't have to remember; if that's the case, your
personal dotfile may be overriding it back to `022`.

---

## Order of operations

1. Run `id` and `ls -ld /stelmo/nwb/analysis /stelmo/nwb/analysis/j1620210710_`
   and read out exactly what they say. Don't paraphrase to the admin —
   *paste* the output.
2. If the group on `analysis/` isn't in your `id` output → **layer 1**, ask
   the admin to add you to the group. Stop here; this likely fixes it.
3. If you're in the group but the subdirectory's mode is missing `g+w` or the
   setgid bit → **layer 2**, ask the admin to `chmod 2775` (and maybe
   `chgrp`) the offending subdir, ideally recursively across `analysis/`.
4. Once writes work, set `umask 002` in your shell rc → **layer 3**, so the
   files *you* create are also writable by the rest of the lab and you don't
   create the same bug for the next person.

---

## Don't do this

```bash
# DO NOT run this
sudo chmod -R 777 /stelmo/nwb/analysis
```

It will make your error go away, and it will also:

- let any user on the host (not just lab members) overwrite or delete every
  analysis NWB file in the lab,
- silently break the group-based access model the rest of the lab depends on,
- get reverted by the sysadmin the next time they audit, putting you right
  back where you started,
- not actually address the underlying issue (you not being in the group, or
  setgid not being set), so the *next* new directory created will have the
  same problem.

The targeted **group + setgid (`chmod 2775`) + `umask 002`** combination above
is the right fix and is what shared scientific filesystems are designed
around.

---

## What to send the admin

If the diagnosis points at layer 1 or 2, this is enough for the admin to act
on without a back-and-forth:

> Hi — my user `<name>` can't write into `/stelmo/nwb/analysis/...` when
> running Spyglass `populate()`; getting `PermissionError [Errno 13]`. Output
> of `id`: `<paste>`. Output of `ls -ld /stelmo/nwb/analysis
> /stelmo/nwb/analysis/j1620210710_`: `<paste>`. Looks like I'm not in group
> `<group>` / the dir is missing setgid + group-write. Could you `usermod -a
> -G <group> <name>` and/or `chmod 2775` the subdir? Other lab members write
> here fine.

That should resolve it without anyone needing to touch the Spyglass code or
your `SPYGLASS_BASE_DIR`.
