# Fetch `session_description` and `session_start_time` for one session

`Session` (`spyglass.common.common_session`) has `nwb_file_name` as its sole
primary key, with `session_description: varchar(2000)` and
`session_start_time: datetime` as secondary attributes
(`src/spyglass/common/common_session.py:19,30-31`). Restricting on the full PK
yields exactly one row, so `fetch1` is the right call (and the cardinality
pre-check carveout in the skill's Core Directives applies — full-PK
restrictions are unique by construction).

Pass both attribute names as positional args to `fetch1` so it returns a
plain `(description, start_time)` tuple rather than a dict or a list of rows.

```python
from spyglass.common import Session

description, start_time = (
    Session & {"nwb_file_name": "j1620210710_.nwb"}
).fetch1("session_description", "session_start_time")
```

Equivalently as a one-liner:

```python
(Session & {"nwb_file_name": "j1620210710_.nwb"}).fetch1(
    "session_description", "session_start_time"
)
```

Notes:

- Use `fetch1`, not `fetch` — `fetch` returns a list/array even for a single
  row, which would force you to index `[0]` and unpack.
- No loop is needed; the restriction `& {"nwb_file_name": ...}` already
  selects the single matching row.
- `session_start_time` comes back as a `datetime.datetime`.
- If you ever see a `DataJointError: fetch1 should only be called on
  one-element relations`, it means the `.nwb` filename didn't match — verify
  with `len(Session & {"nwb_file_name": "j1620210710_.nwb"})` or
  `Session.fetch("nwb_file_name", limit=10)` to find the exact spelling.
