# Slow `fetch()` on RippleParameters — what's happening

A 2-minute hang fetching a *parameters* table is almost never about data volume. `RippleParameters` is a tiny lookup table (a few rows, each with a small parameter dict). There's no realistic way fetching it should take more than a fraction of a second once the connection is alive. So if it's been 2 minutes and still hasn't returned, the fetch isn't slow — it's **blocked**.

The likely culprits, roughly in order:

## 1. Database lock contention (most likely)

DataJoint sits on top of MySQL/MariaDB, and MySQL uses row-level / metadata locks on InnoDB tables. The classic scenario:

- Another worker (another notebook, another user, a script someone forgot about, a crashed `populate()`) opened a transaction that touched `RippleParameters` (or a parent table involved in the restriction) and **never committed or rolled back**.
- Your `fetch()` is waiting on `innodb_lock_wait_timeout` (default 50s, but in many lab configs it's set higher, or the wait is on a metadata lock with no short timeout).
- From Python, this looks identical to a slow query: the call just sits there with no CPU, no network traffic, no progress bar.

**Diagnosis** — distinguish lock-wait from slow compute:

- Open `htop` / Activity Monitor. Is the Python process burning CPU? If **no CPU**, it's not computing — it's waiting on the server.
- On the database side, you (or whoever has admin) can query MySQL's lock state directly. The relevant tables are in `performance_schema`:

  ```sql
  SELECT * FROM performance_schema.metadata_locks
   WHERE OBJECT_SCHEMA LIKE '%ripple%';

  SELECT * FROM performance_schema.data_locks;       -- InnoDB row locks
  SELECT * FROM performance_schema.data_lock_waits;  -- waiter -> blocker edges

  SHOW PROCESSLIST;     -- or:
  SELECT * FROM information_schema.PROCESSLIST;
  ```

  Joining `performance_schema.metadata_locks` against `performance_schema.threads` (and optionally `events_statements_current`) gives you, for each lock: the object being locked, the `LOCK_TYPE`, the `LOCK_STATUS` (`GRANTED` vs `PENDING`), the owning thread's `PROCESSLIST_ID` and `PROCESSLIST_STATE`, and the SQL it's running. That's the data you need to identify which session holds the lock your fetch is waiting on. You read `LOCK_STATUS` and `PROCESSLIST_STATE` together — a row with `LOCK_STATUS = PENDING` on the same `OBJECT_NAME` as another row with `LOCK_STATUS = GRANTED` is the waiter/holder pair, even though the view doesn't draw an explicit blocker→waiter graph.

  Lab Spyglass deployments often wrap this in a helper — check whether your codebase has something like a `check_threads(...)` / `kill_threads(...)` utility on the table mixin or in `spyglass.utils`; that's typically the "see who's holding locks on this table" entry point and it usually queries exactly the `performance_schema` views above. Run that against `RippleParameters` first — it'll return the live lock rows + thread state + running query without you having to write SQL.

- From Python, you can also peek at the connection: `dj.conn().query("SHOW PROCESSLIST").fetchall()` will show every active session and its state. Look for sessions in state `Waiting for table metadata lock`, `Waiting for row lock`, or with a long `Time` value sitting on `RippleParameters` or a parent.

If you see another session holding a lock on `RippleParameters` (or one of its parents in the dependency chain), that's your answer. **Don't unilaterally `KILL` it** — it might be a teammate's running populate that's almost done, and killing mid-transaction means whatever rollback work was queued has to unwind. Ping the lab / Slack first; coordinate before terminating someone else's transaction.

## 2. Stale / dead connection

Sometimes the TCP connection to the DB has died (VPN dropped, server restarted, laptop slept), and DataJoint's `fetch` is sitting in a socket read with a long timeout instead of failing fast.

- Check: try a trivial round-trip in another cell — `dj.conn().query("SELECT 1").fetchone()`. If *that* hangs too, it's the connection, not the lock.
- Fix: `dj.conn().connect()` (or restart the kernel as a last resort). But do the diagnostic first — if it's actually a lock, restarting your kernel won't fix anything because the lock is on the *server*.

## 3. Network / VPN

If you're tunneling to the DB over a VPN and the link has degraded, every query gets slow. Less likely to look like a 2-minute hang on one fetch and snappy elsewhere — it's usually broadly slow — but worth a sanity check (`ping <db host>`).

## 4. Genuinely slow query (least likely here)

`fetch()` on a large blob table or a complex restriction joining many tables can be slow. But `RippleParameters` doesn't fit that profile — it's a small `dj.Lookup` keyed on a parameter name with a small dict blob. There's nothing to be slow about. So I'd rule this out unless your restriction is doing something unexpected (e.g., `&` against a huge upstream table that's forcing a join).

---

## Recommended order of operations

1. **Don't restart the kernel yet.** It throws away diagnostic state.
2. In a fresh cell (or another notebook), run `dj.conn().query("SELECT 1").fetchone()` — confirms the connection is alive.
3. Run `dj.conn().query("SHOW PROCESSLIST").fetchall()` and look for long-running sessions, especially ones in `Waiting for ... lock` states. If your lab has a `check_threads(detailed=True)`-style helper on the table, use that — it'll combine the `performance_schema.metadata_locks` + `threads` views and give you the running query for each holder.
4. Query `performance_schema.metadata_locks` and `performance_schema.data_locks` (joined with `threads`) for rows touching `RippleParameters` or its parents. The `LOCK_STATUS` column tells you `GRANTED` vs `PENDING`; `PROCESSLIST_STATE` tells you what the holding thread is doing.
5. If you find a holder: identify whose session it is and coordinate with the lab before killing.
6. Only after you've ruled out lock contention and a dead connection, consider that the query itself is slow — and even then, `RippleParameters` is the wrong place to suspect that.

The short version: the fetch isn't slow, it's waiting. Find what it's waiting on before you kill anything.
