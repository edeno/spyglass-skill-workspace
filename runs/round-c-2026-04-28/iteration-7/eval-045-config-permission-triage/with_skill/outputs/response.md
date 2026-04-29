# `AccessError: Command create not allowed` populating `LFPV1`

Quick read: this isn't a Spyglass bug, isn't a filesystem problem, and isn't `cautious_delete`'s `LabMember` check. The wording **"Command create not allowed"** is MySQL's grant system telling you your DB user lacks `CREATE` privilege on the schema that `LFPV1.populate()` needs to write into.

`populate()` for `LFPV1` writes into:

- `lfp_v1` (master + part tables for the computed LFP rows)
- `lfp_merge` (the merge master, on first insert into the lab's deployment)
- possibly an `analysis` schema entry for the analysis-NWB filename

On a brand-new session, `populate()` may also be the first call that ever materializes a per-session table or extends an existing one in a way DataJoint treats as a `CREATE`. If your MySQL user doesn't have `CREATE` on whichever schema is being touched, you get this exact error.

There are three permission failures that all surface as "permission denied" during populate, and they have different fixes — guessing wrong wastes time. Triage them in this order.

## Step 1 — confirm it's a MySQL grant problem

```python
import datajoint as dj
dj.conn().query('SHOW GRANTS FOR CURRENT_USER();').fetchall()
```

Look for an entry that covers the schema named in the error message (read the full traceback — DataJoint's `AccessError` includes the schema and SQL command it tried). On shared installations, grants are issued **per schema prefix**, e.g. `GRANT ALL ON \`lfp_v1%\`.* TO 'you'@'%'`. If there's no row covering `lfp_v1` (or whichever prefix the error names), that's your culprit.

Two common patterns:

- The lab admin granted you on `common_*`, `spikesorting_v1_*`, etc. but never extended grants to `lfp_v1` / `lfp_merge` / `lfp_band_v1` because nobody had populated LFP on this deployment before.
- A site that hardened its DB after an incident **revoked** `CREATE` on shared prefixes; users now have to declare under their own prefix. See [setup_troubleshooting.md § "Access denied for CREATE command" on shared-prefix schemas](../../../../skills/spyglass/references/setup_troubleshooting.md#access-denied-for-create-command-on-shared-prefix-schemas) — but that path applies to *custom* tables, not core `LFPV1`. For core LFP, the right fix is asking the admin for the grant.

**Fix:** ask the DB admin for an explicit `GRANT` on the missing prefix(es). Don't try to work around it locally.

## Step 2 — rule out filesystem permissions

If `SHOW GRANTS` looks fine for the affected schemas, check the analysis directory `LFPV1.make()` will write into:

```bash
ls -ld "${SPYGLASS_BASE_DIR}/analysis/<nwb_file_basename>/"
python -c "import os; print(os.access('<that path>', os.W_OK))"
```

On shared lab filesystems, per-session subdirs under `analysis/` are created by whoever first populated the session, and later writers hit `EACCES` unless the dir is group-writable. The error wording is different (it says `Permission denied` on a path, not "Command create"), but it's worth a 10-second check while you're here. Filesystem fixes go through your lab's shared-permissions process (`chmod -R g+w`, an admin-run script, or a cron that re-asserts group-write) — not piecemeal chmods.

## Step 3 — rule out the `LabMember` precondition

This one only matters if you ever try to `.delete()`, but it's the third "permission denied" people confuse with the others. Symptom is distinct:

```
ValueError: Could not find exactly 1 datajoint user <name> in
common.LabMember.LabMemberInfo. Please add one: []
```

Different error class, different wording. If your message is verbatim `AccessError: Command create not allowed`, this is **not** your problem — but flagging it so you don't go down that path next time you see "permission" in a Spyglass traceback. Full pattern: [setup_troubleshooting.md § AccessError / PermissionError on a shared installation](../../../../skills/spyglass/references/setup_troubleshooting.md#accesserror--permissionerror-on-a-shared-installation).

## What I'd actually do, in order

1. Run the `verify_spyglass_env.py` diagnostic first — it'll catch any base-dir / connection / config issues before you go deeper:

   ```bash
   python skills/spyglass/scripts/verify_spyglass_env.py
   ```

2. Capture the **full traceback** of the populate failure (not just the one-line summary). The `AccessError` will name the schema and the SQL statement it failed on — that tells you whether it's `lfp_v1`, `lfp_merge`, the analysis schema, or something else.

3. Run `SHOW GRANTS FOR CURRENT_USER()` and compare against the schema named in the traceback.

4. If grants are missing for that schema/prefix, contact your DB admin with: your DataJoint user, the schema prefix, the exact `AccessError` line, and a request for `INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES` on that prefix (the standard Spyglass-user grant set).

5. **Don't** try to fix this by editing the installed Spyglass package, by running `super_delete()`, by adding `force_permission=True` anywhere, or by switching to a different DataJoint user — those either don't apply or paper over a real ACL issue you'll hit again next session.

If your traceback names a schema that *isn't* `lfp_v1` / `lfp_merge` / one of the analysis schemas, paste it back and I can narrow further — the schema name in the traceback is the load-bearing piece of evidence here.
