You can fetch that row directly with DataJoint's restriction syntax and `fetch1()`:

```python
from spyglass.common import Session

row = (Session & {'nwb_file_name': 'j1620210710_.nwb'}).fetch1()
```

`fetch1()` will return the row as a dict and will raise if the restriction matches anything other than exactly one row. If you'd rather get a `pandas.DataFrame` row, you can do `(Session & {'nwb_file_name': 'j1620210710_.nwb'}).fetch1(format='frame')`.
