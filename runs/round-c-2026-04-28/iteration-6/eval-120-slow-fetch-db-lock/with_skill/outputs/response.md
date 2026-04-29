# 2-minute hang on `RippleParameters.fetch()` — almost certainly DB lock contention, not slow compute

**Symptom.** A `.fetch()` / restriction (`&`) on `RippleParameters` has been sitting for ~2 minutes with no return.

**Most likely root cause: lock contention, not a slow query.** `RippleParameters` is a `dj.Lookup` (`src/spyglass/ripple/v1/ripple.py:110`) keyed only on `ripple_param_name : varchar(80)` with a single `ripple_param_dict : BLOB` payload (`ripple.py:138-142`). There is essentially nothing to fetch slowly — it's a tiny config table holding a Python dict of detector params (e.g. `Kay_ripple_detector`, `speed_threshold=4.0`, `zscore_threshold=2.0`). A 2-minute *idle* hang on a params table is the classic shape of MySQL **metadata-lock contention**: another worker (or an abandoned transaction in another notebook / process) holds a row- or metadata-lock on `RippleParameters` and your fetch is queued behind it.

## Distinguishing idle hang from slow compute

Before you do anything else, decide which signature you have:

- **Slow compute** — a `.fetch()` pulling a large blob/array would show CPU activity in the kernel and disk/network I/O. It looks busy.
- **Lock contention (idle hang)** — no CPU, no I/O, no log progress. The kernel is just blocked on a socket read while MySQL waits for the lock.

Params tables are *never* the slow-compute case (the row is small). For `RippleParameters` specifically, jump straight to `check_threads`.

## Diagnose with `check_threads(detailed=True)`

`SpyglassMixin` ships a built-in lock diagnostic — every Spyglass table inherits it:

`src/spyglass/utils/mixins/helpers.py:206`:

```python
def check_threads(self, detailed=False, all_threads=False) -> DataFrame:
```

It runs a `SELECT` against MySQL's **`performance_schema`** that joins `performance_schema.metadata_locks` (`ml`) with `performance_schema.threads` (`t`) on `ml.OWNER_THREAD_ID = t.THREAD_ID` (helpers.py:233-258). By default it filters to `ml.OBJECT_SCHEMA = self.database AND ml.OBJECT_NAME = self.table_name` so you see only locks on this specific table.

In a *new* notebook / kernel (don't try to run this from the hung session — it's blocked):

```python
from spyglass.ripple.v1.ripple import RippleParameters

RippleParameters().check_threads(detailed=True)
```

The returned DataFrame surfaces lock rows (one row per active metadata lock on the table) plus the owning thread's state and running query. Columns you care about (helpers.py:262-277):

- `Locked` — what's locked (`ml.OBJECT_TYPE`).
- `Lock Type` — the MySQL lock mode (`ml.LOCK_TYPE`).
- `Lock Status` — **`GRANTED` vs `WAITING`** (`ml.LOCK_STATUS`). This is the column that tells you who holds vs who's queued.
- `State` — the thread's process state (`t.PROCESSLIST_STATE`), e.g. `Waiting for table metadata lock`.
- `Time (s)` — how long that thread has been in its current state.
- `Connection ID`, `User`, `Name` — who the holder is.
- `Query` — the actual SQL the holder is running (only with `detailed=True`; `t.PROCESSLIST_INFO`).

**Important:** the output is **lock rows + thread state, NOT an explicit blocker→waiter graph.** You read it yourself: find your own thread sitting on `Lock Status = WAITING` for `RippleParameters`, then find another row with `Lock Status = GRANTED` on the same `OBJECT_NAME` — that's the holder. Inspect the holder's `Query` and `State` columns to figure out what they're doing.

A typical contention pattern looks like:

| Locked | Lock Type | Lock Status | Name  | Time (s) | State                          | Query                              |
|--------|-----------|-------------|-------|----------|--------------------------------|------------------------------------|
| TABLE  | SHARED_…  | GRANTED     | alice | 1873     | (idle, in transaction)         | (an open `INSERT`/`SELECT … FOR UPDATE`) |
| TABLE  | SHARED_…  | WAITING     | you   | 124      | Waiting for table metadata lock | `SELECT … FROM ripple_parameters …`     |

That's the proof: someone else's transaction has been open ~31 minutes; your fetch has been queued ~2 minutes behind it. (Watch out — `check_threads` itself needs a live connection, so if the *server* is unreachable it will hang the same way. If you're unsure, sanity-check connectivity first with `python skills/spyglass/scripts/verify_spyglass_env.py --check dj_connection --timeout 10`.)

## Likely cause of the blocker

In Spyglass labs, the holder is almost always one of:

- An interrupted `populate()` in another notebook/worker that left a transaction open.
- A long-running `make()` body that took an upstream lock and is still computing.
- A forgotten Jupyter cell that did a `dj.conn().start_transaction()` (rare) or a `with conn.transaction:` block that hasn't exited.
- An IDE / SQL client connected to the DB with an uncommitted transaction.

The `Connection ID`, `Name`/`User`, and `Time (s)` columns identify which session.

## Resolution — coordinate, don't unilaterally `KILL`

**Do not just `KILL` someone else's connection.** That worker may be mid-populate, and killing it will roll back whatever transaction was protecting partial writes — and may corrupt their working state.

Workflow:

1. From the `Name` / `User` / `Host` columns, identify the lab member who owns the holding session.
2. Ping them — confirm whether the transaction is genuinely abandoned (interrupted notebook, killed tmux) or whether they're actively running something.
3. If it's abandoned and they confirm, *they* (or an admin) should `KILL <PROCESSLIST_ID>` their own session, or simply restart that kernel.
4. Only after they're aware/agreed: an admin can issue `KILL` on the connection ID. Don't do this from the hung notebook — open a fresh connection.

A "restart the kernel and try again" instinct doesn't help here: restarting *your* kernel doesn't release the *other* session's lock. The hang would resume the moment you re-issue the fetch.

## Watch-outs

- The DataFrame can have **zero rows** if `performance_schema` is enabled but no metadata locks are currently held on `RippleParameters` — in that case widen with `check_threads(detailed=True, all_threads=True)` to see locks on related tables (an upstream `RippleLFPSelection` / `LFPBandV1` could be the actual blocker if your fetch is doing a join under the hood).
- If `check_threads` raises `RuntimeError: Database does not monitor threads.`, your DB admin has `performance_schema=OFF`; ask them to enable it (helpers.py:227-231). In that case fall back to `SHOW PROCESSLIST;` via `dj.conn().query(...)`, but the lock detail won't be there.
- Lookup tables generally fetch in milliseconds. If you ever genuinely *do* see a slow Lookup fetch with CPU activity, suspect an `_Update` blob got accidentally bloated, or that you're fetching through `fetch_nwb()` on a non-NWB table by mistake — but that's not what 2 minutes of *idle* hang looks like.

## Quick-reference summary

- `RippleParameters` is `dj.Lookup`; tiny rows; the slow-compute hypothesis doesn't fit.
- An idle 2-min hang on a params table = **lock contention** until proven otherwise.
- Diagnostic: `RippleParameters().check_threads(detailed=True)` (`utils/mixins/helpers.py:206`), backed by `performance_schema.metadata_locks ⨝ performance_schema.threads`.
- Output is lock rows + thread state — **not** an explicit blocker→waiter graph; read `LOCK_STATUS` (`GRANTED` vs `WAITING`) and `PROCESSLIST_STATE` to identify holder vs waiter.
- Resolve by **coordinating with the holder**, not by unilaterally killing their transaction.

References used: `runtime_debugging.md` § I (`populate()` or a query hangs indefinitely) and `spyglassmixin_methods.md` (for `check_threads`).
