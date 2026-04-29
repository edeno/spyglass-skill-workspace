```python
from spyglass.common import Session

(Session & {"nwb_file_name": "j1620210710_.nwb"}).fetch1()
```

`nwb_file_name` is `Session`'s full primary key (`-> Nwbfile`), so the restriction is unique by construction — `fetch1()` is safe with no cardinality check.
