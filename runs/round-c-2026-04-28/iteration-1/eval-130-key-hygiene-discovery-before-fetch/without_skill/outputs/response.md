# Fetching LFP for a session in Spyglass

Here's a basic snippet to fetch LFP data for an NWB session:

```python
import datajoint as dj
from spyglass.lfp.v1 import LFPV1

nwb_file_name = "my_session_.nwb"  # replace with your session

# Restrict and fetch
lfp_df = (LFPV1 & {"nwb_file_name": nwb_file_name}).fetch1_dataframe()
print(lfp_df.head())
```

That returns a `pandas.DataFrame` indexed by time, with one column per LFP channel.

If you want the data through the merge table (the canonical downstream entry point), use `LFPOutput`:

```python
from spyglass.lfp import LFPOutput

merge_key = (LFPOutput & {"nwb_file_name": nwb_file_name}).fetch1("KEY")
lfp_df = (LFPOutput & merge_key).fetch1_dataframe()
```

Common follow-ups:

- To plot a slice:

  ```python
  import matplotlib.pyplot as plt
  lfp_df.iloc[:10000, :4].plot(subplots=True, figsize=(10, 6))
  plt.show()
  ```

- To get the underlying NWB Electrical Series object instead of a dataframe, use `.fetch_nwb()` instead of `.fetch1_dataframe()`.

- If you also want the electrode metadata (region, hemisphere, etc.), join against `LFPElectrodeGroup` / `Electrode`:

  ```python
  from spyglass.lfp.v1 import LFPElectrodeGroup
  electrodes = (LFPElectrodeGroup & {"nwb_file_name": nwb_file_name}).fetch(as_dict=True)
  ```

Make sure the LFP table has been populated for your session first (i.e. `LFPSelection.insert1(...)` and `LFPV1.populate(...)` have already run), otherwise the restriction will be empty.
