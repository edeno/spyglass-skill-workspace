Restrict `IntervalList` to the session, then project `interval_list_name` with `.fetch()` (multi-row — `.fetch1()` would raise because a session has many intervals):

```python
from spyglass.common import IntervalList

names = (IntervalList & {"nwb_file_name": "j1620210710_.nwb"}).fetch("interval_list_name")
```

Notes:

- `nwb_file_name` ends in `.nwb` — that's the on-disk filename used as the PK across `Session`, `IntervalList`, etc. (`spyglass/common/common_interval.py:24-28`; PK is `(nwb_file_name, interval_list_name)`).
- Use `.fetch("interval_list_name")` (not `.fetch1`) — a session typically has many intervals (e.g. `"raw data valid times"`, `"01_s1"`, `"02_r1"`, `"pos 0 valid times"`, ...). `.fetch1` only works when the restriction selects exactly one row.
- The restriction goes first, then the projection — `(IntervalList & {...}).fetch("interval_list_name")` returns a 1-D NumPy array of names. If you want them as Python strings, wrap in `list(...)`.
- If you also want the `valid_times` array per interval, swap to `.fetch("interval_list_name", "valid_times")` (returns two parallel arrays) or `.fetch(as_dict=True)` for one dict per row.
