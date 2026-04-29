I want to push back on `super_delete()` before you reach for it. That error is doing its job, and the fix is almost certainly *not* to bypass it.

## What the error actually means

Spyglass / DataJoint's `Nwbfile` (and the tables that inherit from `SpyglassMixin`) gate `.delete()` through a **team-permission check** (`SchemaTeam` / `LabTeam`). The check says: *"the rows you're trying to delete were ingested by `otheruser`, and `testuser` is not on a team that includes `otheruser`, so you don't have permission to cascade-delete their data."*

This is a guardrail, not a bug. Deleting an upstream row in DataJoint **cascades** — every downstream computed result (sortings, LFP, decoding, ripples, position, …) belonging to `otheruser` and anyone else downstream of that row gets wiped too. That's what the team check is protecting against.

## Why `super_delete()` is the wrong default

`super_delete()` exists, but it deliberately:

1. **Skips the team / permission check.** You will silently delete another user's downstream results.
2. **Skips the external-file cleanup logic** that the SpyglassMixin `.delete()` path runs. That can leave orphaned files in `SPYGLASS_BASE_DIR` (analysis NWBs, sorting outputs, kachery-linked artifacts) that the DB no longer references — disk fills up, and there's no record of what they were.
3. **Is irreversible.** DataJoint deletes are not soft-deletes. Once the cascade runs, recomputing requires rerunning every populate downstream, assuming the raw data is still around.

The naming is intentional — `super_delete` is the "I am the admin, I have already verified nothing important is downstream, get out of my way" escape hatch. It is not the "I'm hitting a permissions error and want to move on" tool.

## What to do instead

In rough order of preference:

1. **Confirm the row is actually yours to delete.** Run `(Nwbfile & key).fetch('nwb_file_name', 'admin')` (or whatever the relevant table is) and check who ingested it. If it's `otheruser`'s data, the right move is to **ask them**, not to override.
2. **Inspect the cascade before deleting anything.** `(YourTable & key).delete(safemode=True)` (the default) will print every downstream row that would be affected. Read that list. If it touches tables owned by other users, stop.
3. **Get added to the right team.** If you legitimately co-own this data, the admin can add `testuser` to the same `LabTeam` as `otheruser`. That's a one-line insert into `LabTeam.LabTeamMember` and it makes the regular `.delete()` work without disabling the safety net for everyone forever.
4. **If you only need to delete *your own* downstream rows** (e.g., a sorting you computed on someone else's NWB), restrict the delete to your table, not to `Nwbfile` upstream. `(SpikeSortingV1 & key & 'team_name="my_team"').delete()` won't trip the check because you're not touching `otheruser`'s row.
5. **Only if you are the DB admin AND have verified the cascade is acceptable**: `super_delete(warn=False)` — and even then, `dj.config['safemode'] = True` and run with `warn=True` first so you see what's about to vanish.

## Concrete next step

Before running anything destructive, can you share:

- which table you're calling `.delete()` on,
- the restriction you're using (`& key`), and
- the output of `(thattable & key).fetch('KEY')` plus whoever ingested the upstream `Nwbfile`?

With that I can tell you whether this is a "ask `otheruser` / get team membership" situation or a "restrict your delete more narrowly" situation. Either way, `super_delete()` should stay holstered.
