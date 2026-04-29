Short answer: almost certainly no — `Session` in Spyglass is a session-metadata table (subject, experimenter, institution, session start/description, NWB file pointer, etc.), not the place where per-acquisition signal properties like the raw-ephys sampling rate live. So a `fetch1('sampling_rate')` against `Session` will almost certainly raise a DataJoint error of the form:

```
DataJointError: Attribute `sampling_rate` not found.
```

(i.e. "unknown attribute" — the column simply isn't on that table).

I don't want to invent a number or a return shape for you, so let me give you the two things that actually matter: how to verify, and where the value really lives.

## 1. Verify the schema yourself (this is the right reflex on any DataJoint table)

Don't trust me — ask the table. Any of these will tell you exactly which columns `Session` has:

```python
from spyglass.common import Session

Session.heading                # full heading: primary key + secondary attrs + types
Session.heading.names          # just the column names, as a list
Session.describe()             # printable schema definition (DJ DDL)
```

You should see things like `nwb_file_name` (PK), `subject_id`, `institution_name`, `lab_name`, `experiment_description`, `session_description`, `session_id`, `timestamps_reference_time`, etc. — but **not** `sampling_rate`. Confirming this with `.heading` takes one second and is a much better habit than guessing column names from intuition; do it before every `fetch1` you're unsure about.

If you'd rather check at the SQL level, `Session.describe()` prints the DataJoint definition in the same DSL the table was declared in.

## 2. Where the raw-ephys sampling rate actually lives

In `spyglass.common.common_ephys`, the table that represents the ingested raw electrical-series object from the NWB file is `Raw`. It is keyed by `nwb_file_name` (so it joins cleanly to `Session`) and carries sampling rate as a direct secondary attribute. The definition is roughly:

```python
@schema
class Raw(SpyglassMixin, dj.Imported):
    definition = """
    -> Session
    ---
    raw_object_id: varchar(40)        # object_id of the ElectricalSeries in the NWB file
    sampling_rate: float              # Hz
    interval_list_name: varchar(200)  # valid-times interval list for this raw recording
    comments: varchar(2000)
    description: varchar(2000)
    """
```

So the call you actually want is:

```python
from spyglass.common.common_ephys import Raw

rate_hz = (Raw & {'nwb_file_name': 'j1620210710_.nwb'}).fetch1('sampling_rate')
# -> a Python float, in Hz
```

That returns the scalar sampling rate as a `float` (Hz). Two practical notes:

- **Confirm there's exactly one row first.** `fetch1` will raise if the restriction doesn't return exactly one tuple. A quick `len(Raw & {'nwb_file_name': 'j1620210710_.nwb'})` (or just printing the restricted table) is a cheap sanity check — `Raw` is normally one row per session, but it's worth confirming for your file rather than assuming.
- **If `Raw` hasn't been populated yet** for that NWB file, the restricted table will be empty and `fetch1` will raise `DataJointError: fetch1 should only return one tuple. ... 0 tuples found`. In that case you need to populate the ingestion step that produces `Raw` for this session, or read the rate directly from the underlying NWB `ElectricalSeries` via the `fetch_nwb`-style accessor (e.g. `(Raw & key).fetch_nwb()[0]['raw'].rate`) — that goes back to the NWB object on disk rather than the cached scalar in the DataJoint row.

## 3. The general lesson

`Session` ≈ "what session is this?" (metadata, identifiers).
`Raw` ≈ "what are the properties of the raw acquisition for that session?" (object id, sampling rate, valid-times interval, description).

Anytime you're tempted to grab a signal-level property (sampling rate, channel count, gain, reference) off `Session`, that's a hint to look one table downstream. And before the first `fetch1` of the day on a table you haven't touched in a while, run `.heading` — it's the cheapest bug-prevention tool DataJoint gives you.

Caveat on my own confidence: I'm answering from general knowledge of the Spyglass / DataJoint conventions rather than from a live schema dump of your deployment. The structural claim ("`sampling_rate` is not on `Session`; it's a secondary attribute of `Raw`, keyed by `nwb_file_name`") is very robust across Spyglass versions, but the exact set of secondary columns on `Raw` can drift slightly between releases. So: trust `Raw.heading` over my recollection of the column list, and trust `Session.heading` over my assertion that `sampling_rate` isn't there. Both checks are one line.
