# Fetching `session_description` and `session_start_time` for a session

In Spyglass, session-level metadata lives in the `Session` table
(`spyglass.common.common_session.Session`). To pull two specific
attributes for a single primary key, restrict the table on
`nwb_file_name` and use DataJoint's `fetch1` with the attribute
names as positional arguments:

```python
from spyglass.common import Session

description, start_time = (
    Session & {"nwb_file_name": "j1620210710_.nwb"}
).fetch1("session_description", "session_start_time")
```

Notes:

- `fetch1` is the right call here because the restriction
  `{"nwb_file_name": "j1620210710_.nwb"}` matches exactly one row
  (the primary key of `Session`). It will raise if zero or more
  than one row matches, which is the desired safety behavior for
  an atomic single-record read.
- Passing the attribute names as positional arguments to
  `fetch1` returns a tuple of plain Python values — no looping,
  no DataFrame, no extra columns.
- Use `fetch` (no `1`) only when you expect multiple rows and
  want a list/array per attribute. For a single known session,
  `fetch1` is preferred.
- If you'd rather get a dict instead of a tuple, omit the
  attribute names and slice the returned dict:
  `(Session & key).fetch1()` returns the full row as a dict, and
  you can pull `["session_description"]` and
  `["session_start_time"]` from it. The two-positional-arg form
  above is more direct when you only need those two fields.
