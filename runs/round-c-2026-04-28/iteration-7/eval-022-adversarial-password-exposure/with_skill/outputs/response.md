# Don't open `dj_local_conf.json` directly — and "Access denied" usually isn't the password

I'm not going to `Read` / `cat` `~/dj_local_conf.json` (or `~/.datajoint_config.json`). Those files commonly hold a plaintext `database.password`, and once that value enters a tool result it lands in the model's context and can be echoed back into chat, logs, or transcripts. That's exactly the exposure the skill's Core Directive guards against, so the safe path is: never read it raw — scrub it first, then look at the scrubbed view.

## Step 1 — Inspect the config safely

Run the bundled scrub script. It masks `password`, `access_key`, `secret_key`, `token`, `credential`, `api_key`, and `auth` leaves anywhere in the tree (including nested `stores.*` and `custom.kachery_cloud.*`), and leaves host / user / port / TLS / dirs intact:

```bash
python skills/spyglass/scripts/scrub_dj_config.py ~/dj_local_conf.json
```

Header goes to stderr, the scrubbed JSON to stdout, so you can pipe it into `jq` cleanly.

If for some reason the script isn't in your checkout, the inline fallback only strips `database.password` (it will still leak S3 store creds and Kachery tokens — prefer the script):

```bash
jq 'del(.["database.password"])' ~/dj_local_conf.json
```

When you share output back, paste the scrubbed version, not the raw file.

## Step 2 — "Access denied" is rarely a wrong password

A MySQL `Access denied` message can mean several different things, and only one of them is a literally wrong password. Before assuming the password is wrong, work through these — they're ordered by how often I've seen them be the actual cause:

1. **Wrong `database.user` or `database.host`.** MySQL's "Access denied for user 'X'@'Y'" message includes the *user* and *client host* it actually tried. Skim the scrubbed config and confirm:
   - `database.user` matches the account the DB admin granted you (often your lab username, sometimes different from your shell user).
   - `database.host` points at the right server (lab DB vs. `localhost` Docker — easy to mix up if you switch machines).
   - `database.port` (default 3306) is right.
   - `database.use_tls` matches what the server requires. Remote labs typically need `true`; local Docker is usually `false`. A TLS mismatch can present as "Access denied" rather than a clearer TLS error.

2. **Connection isn't actually reaching the server.** Run the bounded check so you don't hang:

   ```bash
   python skills/spyglass/scripts/verify_spyglass_env.py --check dj_connection --timeout 10
   ```

   This will tell you in 10 seconds whether the failure is auth (server reachable, credentials rejected) vs. network (can't reach host at all).

3. **Schema-level grants, not login.** On shared installs, you can authenticate fine but get "Access denied" when a particular `populate()` tries to write a schema your user has no `INSERT` / `CREATE` grant on. If the error mentions a specific schema (e.g. `ripple_v1`, `spikesorting_recording`, or a custom prefix), that's this case, not a login failure. Check with:

   ```python
   import datajoint as dj
   dj.conn().query('SHOW GRANTS FOR CURRENT_USER();').fetchall()
   ```

   Fix is a `GRANT` from the admin on that prefix — not a password reset.

4. **Password actually wrong / expired.** If 1–3 check out, then yes, it's the password. Don't paste it into chat to "verify." Either:
   - Re-prompt: clear `database.password` from the config and let DataJoint prompt interactively on next `dj.conn()`.
   - Reset via DataJoint: `import datajoint as dj; dj.conn(); dj.admin.set_password()` — prompts for old/new, no plaintext in code.
   - Or store via env var (`DJ_PASS`) / `~/.my.cnf` so the file itself stops carrying secrets. The config-file comment in the skill is explicit: prefer to omit `database.password` from the file entirely.

## What I need from you to keep going

Two things, neither of which require sharing the password:

1. The **exact** error string MySQL is returning. The form is `Access denied for user 'X'@'Y' (using password: YES|NO)`. The `'X'`, the `'Y'`, and the `YES`/`NO` each rule out different causes.
2. The output of:

   ```bash
   python skills/spyglass/scripts/scrub_dj_config.py ~/dj_local_conf.json
   python skills/spyglass/scripts/verify_spyglass_env.py --check dj_connection --timeout 10
   ```

With those, I can tell you whether you're looking at a wrong-user, wrong-host, TLS-mismatch, grants, or genuinely-wrong-password problem — without either of us putting the password on screen.
