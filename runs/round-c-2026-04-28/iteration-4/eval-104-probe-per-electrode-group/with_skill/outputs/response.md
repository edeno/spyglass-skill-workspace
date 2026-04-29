# Probe model per electrode group for `j1620210710_.nwb`

## Status: I cannot answer this from static analysis alone — it is a runtime/DB question

The probe model assigned to each electrode group is data stored in the connected DataJoint database for this session. There is no way to know the per-group probe assignment from the skill or from `$SPYGLASS_SRC` source — only from a live DB query (or from inspecting the source NWB file directly).

In this environment I do not have shell access to run `db_graph.py` against your DB, so per the skill's evidence rule I am not going to invent or guess probe-model strings. Below is the exact query to run in your live Python session; it returns one row per electrode group with its probe model and the upstream `ProbeType` metadata.

## Schema path you're walking

`Session(nwb_file_name)` 1:many `ElectrodeGroup(nwb_file_name, electrode_group_name)`, which carries an FK `probe_id` to `Probe`, which in turn has an FK `probe_type` to `ProbeType` (manufacturer, shank count, etc.). `ProbeType.probe_type` is the canonical "model name" string (e.g. `"tetrode_12.5"`, `"npx1.0"`).

See `references/common_tables.md` (Hardware and Devices, Electrophysiology sections) for the table summary; verify exact field names with `ElectrodeGroup.heading` / `Probe.heading` / `ProbeType.heading` in your session before relying on a column name.

## Query — runs in your notebook against the configured DB

```python
from spyglass.common import ElectrodeGroup, Probe, ProbeType

f = "j1620210710_.nwb"   # already in the copy-form Spyglass uses (trailing "_")

# 1. Confirm the session is ingested and has electrode groups
print("session present:", len(ElectrodeGroup & {"nwb_file_name": f}) > 0)
print("n_groups:", len(ElectrodeGroup & {"nwb_file_name": f}))

# 2. Per-group probe assignment.
#    ElectrodeGroup -> Probe (via probe_id) -> ProbeType (via probe_type)
groups = (
    (ElectrodeGroup & {"nwb_file_name": f})
    * Probe
    * ProbeType
).fetch(
    "electrode_group_name",
    "probe_id",
    "probe_type",
    "probe_description",   # optional, drop if heading doesn't have it
    "manufacturer",        # optional, drop if heading doesn't have it
    "num_shanks",          # optional, drop if heading doesn't have it
    as_dict=True,
)

for g in sorted(groups, key=lambda r: r["electrode_group_name"]):
    print(g)
```

If you want only the model string per group (no metadata join):

```python
((ElectrodeGroup & {"nwb_file_name": f}) * Probe).fetch(
    "electrode_group_name", "probe_id", "probe_type", as_dict=True
)
```

## Things to verify before trusting the output

1. **`ElectrodeGroup` actually has `probe_id`.** Older / custom installs sometimes carry the probe FK on a sibling table; confirm with `print(ElectrodeGroup.heading)`. If `probe_id` is not on the heading, the `* Probe` join above will silently produce a cross-product. Skill rule (SKILL.md "Do not invent identifiers" + Common Mistake #6).
2. **Cardinality.** The join is `ElectrodeGroup * Probe * ProbeType` — for one session you should get exactly `len(ElectrodeGroup & {"nwb_file_name": f})` rows back. If you get more, the join multiplied somewhere (most often because a needed PK field is missing from the join) — debug with `len(...)` at each `*` step before fetching.
3. **Some groups can have no probe.** If `probe_id` is nullable in your install and a group has it null, the inner join above will *drop* that group. To see those, run `(ElectrodeGroup & {"nwb_file_name": f}).fetch("electrode_group_name", "probe_id", as_dict=True)` first and look for null `probe_id`.
4. **NWB-file fallback.** If the session is not yet ingested but you have the raw NWB file, the same information lives in the file's `electrode_groups` and `devices` (the `Probe` device class from `ndx-franklab-novela`). That is a different code path — use the `nwb` skill, not Spyglass.

## What I'd give you if I had DB access

`db_graph.py` from this skill is the right tool to answer this without typing a query — for example:

```bash
python skills/spyglass/scripts/db_graph.py find-instance \
    --class spyglass.common.ElectrodeGroup \
    --restrict '{"nwb_file_name": "j1620210710_.nwb"}' \
    --join spyglass.common.Probe spyglass.common.ProbeType \
    --fields electrode_group_name probe_id probe_type \
    --json
```

(Exact flag names: confirm with `db_graph.py find-instance --help` — the script's CLI is the source of truth.) If you run either form and paste the output back, I can interpret the per-group probe models, flag any null `probe_id`s, and compare against the NWB file's intended layout.
