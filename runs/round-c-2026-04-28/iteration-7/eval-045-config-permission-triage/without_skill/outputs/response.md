# `AccessError: Command create not allowed` when populating `LFPV1`

This error is **not** Spyglass code — it's coming from the underlying MySQL server, surfaced through DataJoint. The DataJoint client tried to issue a `CREATE` statement (CREATE TABLE, CREATE DATABASE, or sometimes CREATE TEMPORARY TABLE) and the MySQL user you're connecting as doesn't have that privilege on the target schema. The `populate()` call is just where it first becomes visible, because populating is the first time the pipeline tries to *write* on a fresh session.

Here's the triage path from most-likely to least-likely.

---

## 1. Confirm what user you're actually connected as

Spyglass / DataJoint reads credentials from (in order of precedence) `dj.config`, `~/.datajoint_config.json`, and `./dj_local_conf.json`. It's very common to have a stale or wrong one shadowing the one you think you're using.

In a Python shell:

```python
import datajoint as dj
print(dj.config["database.host"])
print(dj.config["database.user"])
# don't print the password
```

Then on the MySQL side, confirm the *server* sees the same identity and what it is allowed to do:

```python
dj.conn().query("SELECT CURRENT_USER(), USER();").fetchall()
dj.conn().query("SHOW GRANTS FOR CURRENT_USER();").fetchall()
```

`CURRENT_USER()` is the account MySQL matched you against (this is what `GRANT` checks). `USER()` is what you sent. If they differ, MySQL fell back to a more restrictive account (often the anonymous `''@'%'` or a read-only role).

What you want to see in `SHOW GRANTS` is something like:

```
GRANT ALL PRIVILEGES ON `lfp%`.* TO ...
GRANT ALL PRIVILEGES ON `common%`.* TO ...
GRANT CREATE, INSERT, SELECT, ... ON `<your_user>_%`.* TO ...
```

If you only see `SELECT` (or only `SELECT, INSERT, UPDATE, DELETE` without `CREATE`), that's your bug. **You don't have permission to create the LFP schema/tables for this session, which is what `populate()` triggers the first time a downstream table is touched.**

## 2. Figure out *which* schema is being created

`LFPV1` lives in the `lfp_v1` schema (module `spyglass.lfp.v1.lfp`). But populating `LFPV1` in a fresh environment can also touch:

- `common_*` schemas (Session, Nwbfile, IntervalList, ElectrodeGroup, …) — these usually already exist and you only need INSERT/SELECT, not CREATE.
- `lfp_v1` itself — first-time populate on a brand-new database needs CREATE on this schema.
- `lfp_merge` — the LFP merge table.
- A user-prefixed schema (`<username>_…`) if you're on a shared lab server and the admin convention is per-user write schemas.

To see which one tripped, re-run with the full traceback and look at the SQL just before the `AccessError`. Or temporarily turn on query logging:

```python
dj.config["loglevel"] = "DEBUG"
```

The offending line will be a `CREATE TABLE \`schema_name\`.\`...\`` — the schema name is the privilege you're missing.

## 3. The most common concrete causes

In rough order of how often I see them:

1. **Shared lab server, you're a new user.** The admin gave you `SELECT, INSERT, UPDATE, DELETE` on existing schemas but not `CREATE`. You need the admin to either (a) grant you `ALL` on `lfp_v1.*` and `lfp_merge.*`, or (b) pre-create those schemas for you. Send them: `GRANT ALL PRIVILEGES ON \`lfp_v1\`.* TO '<user>'@'%';` (and the same for `lfp_merge`, `lfp_band_v1` if you'll go further down the pipeline) followed by `FLUSH PRIVILEGES;`.
2. **`database.user` in your config is the read-only "guest" account.** Many labs ship a public-readable account for tutorials/demos; populating with it always fails. Switch to your real account.
3. **Schema-prefix policy.** Some Spyglass deployments require all writeable schemas to be prefixed with your username (e.g. `edeno_lfp_v1`). If you set `prepopulate=False` and the schema name in code is the unprefixed `lfp_v1`, the server refuses. Check `dj.config["custom"]` for a `prepend_schema_name` or similar.
4. **You're pointed at a production DB but should be on a dev/sandbox DB.** Look at `database.host`. If it's the lab production server, you genuinely don't have CREATE there.
5. **MySQL user host mismatch.** Your account is `you@labworkstation` but you're VPN'd in and the server sees you as `you@%`. The `%` account has fewer privileges. `CURRENT_USER()` from step 1 will reveal this.

## 4. What to do, depending on what step 1 shows

- **You see no CREATE grants on the relevant schema** → message your DB admin with the output of `SHOW GRANTS` and the schema name from step 2. They run `GRANT` + `FLUSH PRIVILEGES`. This is the fix 90% of the time.
- **`CURRENT_USER()` is anonymous or wrong** → fix `database.user` / `database.password` in `dj_local_conf.json` (or `~/.datajoint_config.json`). Make sure no stale env vars (`DJ_USER`, `DJ_PASS`, `DJ_HOST`) are overriding.
- **You're the admin / running locally in Docker** → connect as `root` and grant yourself, or use the Spyglass docker-compose's `mysql` service which already has full privileges. If you're using the official Spyglass tutorial container and still see this, double-check the container is healthy and you're not accidentally hitting a remote host.

## 5. Things this is *not*

- Not a missing `SPYGLASS_BASE_DIR` or filesystem permission. Those produce different errors (`FileNotFoundError`, `PermissionError` on a path, or `KeyError` on the config dict).
- Not a `make()` logic bug. `populate()` hadn't gotten far enough to run `make()` — it failed during table declaration.
- Not an NWB ingestion problem. The session being "new" matters only because it's the first one to force the LFP schema into existence.

## TL;DR

1. `dj.conn().query("SHOW GRANTS FOR CURRENT_USER();").fetchall()` — if no `CREATE` on `lfp_v1` (or `lfp_merge`), that's it.
2. Check `dj.config["database.user"]` is the account you think it is.
3. Ask your DB admin to grant `ALL PRIVILEGES ON \`lfp_v1\`.*` (and `lfp_merge.*`) to your user, then `FLUSH PRIVILEGES`.
4. Re-run `LFPV1.populate()`.

If after step 1 you can paste the `SHOW GRANTS` output (with the username masked) and the full traceback, I can point at the exact missing grant.
