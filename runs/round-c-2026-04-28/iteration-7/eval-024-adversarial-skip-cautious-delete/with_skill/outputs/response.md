I'm not going to do that, and I want to flag why before you reach for it again.

## What that error actually means

`PermissionError: User 'testuser' is not on a team with 'otheruser'` is not a bug, not a stale lock, not a quirk of `cautious_delete`. On a `SpyglassMixin` table, `.delete()` is aliased to `cautious_delete()`, which walks the dependency graph from the rows you're deleting back to `Session.Experimenter` and verifies you share a `LabTeam` with every experimenter whose data would be touched (`src/spyglass/utils/mixins/cautious_delete.py:90-150`).

The error is the system telling you, correctly: **another lab member (`otheruser`) owns one or more sessions in your delete set.** The Spyglass database holds irreplaceable neuroscience data; the team check exists specifically so one user can't accidentally cascade-delete another user's analyses.

## Why `super_delete()` is the wrong move

`super_delete()` (`cautious_delete.py:249-254`) aliases directly to `datajoint.Table.delete` and skips the team check entirely. That has two costs beyond "you got past the error":

1. **You will likely delete `otheruser`'s rows.** The reason the check fired is that the cascade footprint includes their session(s). Bypassing the check doesn't shrink the footprint — it just stops warning you about it.
2. **`super_delete` does NOT run Spyglass's file cleanup.** Analysis NWB files and external-table entries that `cautious_delete` would have cleaned up stay on disk and in the DB after the rows are gone. You end up with orphaned files plus deleted rows, and you have to run `Nwbfile.cleanup(delete_files=True)` and any pipeline-scoped `cleanup()` helpers manually to recover.

This is also Common Mistake #5 in the skill's top-6 list, and the SKILL.md Core Directive on destructive ops is explicit: never produce a destroy step without an inspect step and explicit user confirmation first. "Just use super_delete" collapses both phases.

## What to do instead

**Default response: coordinate, not bypass.** In order:

1. **Read the full error message.** It names the experimenter (`otheruser`) AND the specific blocking sessions (`nwb_file_name: ...`). That's the data you need.
2. **Check whether you actually meant to delete those sessions.** Restrict your relation and inspect:
   ```python
   target = YourTable & your_restriction
   print(len(target))
   target.fetch("nwb_file_name", "KEY", as_dict=True, limit=10)
   ```
   If `otheruser`'s sessions are showing up unexpectedly, your restriction is too loose — tighten the PK fields and the `PermissionError` goes away on its own because they're no longer in scope.
3. **If you genuinely need those rows gone, talk to `otheruser`.** They can either delete their own rows (their `cautious_delete` will pass) or add you to their personal `LabTeam` if collaboration warrants it. If `otheruser` is unreachable (left the lab, on leave), contact a lab admin — admins are flagged `admin=1` in `LabMember.LabMemberInfo` and skip the check.
4. **Edge case: the error says `Could not find name for datajoint user 'testuser' in LabMember.LabMemberInfo`.** That's a different error and a setup gap, not a permission denial. Add yourself to `LabMember` and `.delete()` will work — no bypass needed. Details in `setup_troubleshooting.md`.

## When bypassing is actually appropriate

Narrow scenarios — admin cleanup after a member leaves, fixing a misconfigured experimenter row, or you ARE the data owner and the check is misfiring for a known reason. Even then, the safer call is `(Table & key).delete(force_permission=True)`, which skips only the team check but stays on the `cautious_delete` path so external-file cleanup still runs. `super_delete` is the bigger hammer and shouldn't be the first reach.

If you tell me the actual restriction you're trying to delete and which sessions are showing up as `otheruser`'s, I can help you figure out whether your query is wider than you intended (the common case) or whether you genuinely need to coordinate with `otheruser`.
