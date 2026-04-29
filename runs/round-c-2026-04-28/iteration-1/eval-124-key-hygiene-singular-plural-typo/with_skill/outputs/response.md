# Singular/plural typo on the PK field — DataJoint silently dropped the restriction

## Diagnosis

The PK field is **`trodes_pos_params_name`** (plural `params`), not `trodes_pos_param_name` (singular `param`). Your restriction key uses the singular form, so DataJoint doesn't recognize it as a heading attribute on `TrodesPosParams` and **silently drops it** — no error, no warning. The `&` then reduces to no restriction at all, and `fetch1()` sees every row in the table, raising:

```
DataJointError: fetch1 expected one tuple, found N
```

That error message is misleading here: nothing actually matched too many rows in the way you intended — your intended restriction was never applied. The `N` is the full row count of `TrodesPosParams`.

This is the exact silent-drop footgun called out in the skill's common-mistakes guidance: DataJoint ignores unknown restriction keys instead of raising, so a typo in a field name turns into a "matches everything" no-op rather than a "matches nothing" error.

## Verifying the field name (don't trust memory)

Two ways, both authoritative:

**From the skill's bundled source-graph script (no DB needed):**

```bash
python skills/spyglass/scripts/code_graph.py describe TrodesPosParams --json
```

The `pk_fields` list is the ground truth.

**From your live Python session (runtime heading):**

```python
from spyglass.position.v1 import TrodesPosParams
TrodesPosParams.heading.primary_key
# -> ('trodes_pos_params_name',)
```

Source confirmation: `src/spyglass/position/v1/position_trodes_position.py:55` declares the column as

```
trodes_pos_params_name: varchar(80) # name for this set of parameters
```

and the table's own `default_pk` property at line 63 uses the same plural spelling: `{"trodes_pos_params_name": "default"}`.

## Fix

Use the plural form:

```python
(TrodesPosParams & {"trodes_pos_params_name": "default"}).fetch1()
```

Or, equivalently, reuse the table's own helper so you don't have to spell the field at all:

```python
TrodesPosParams & TrodesPosParams().default_pk        # same restriction
TrodesPosParams.get_default()                         # returns the default params dict directly
```

## Why this matters as a habit

The "silent drop on unknown attribute" rule is the same mechanism behind several Spyglass footguns — most notably `(MergeMaster & {"nwb_file_name": f})` returning the whole master table because `nwb_file_name` lives on the part tables, not the master's heading. Whenever a `&` restriction "doesn't seem to do anything," the first check is **does every key in the restriction dict appear in `Table.heading.primary_key` or `Table.heading.secondary_attributes`?** If not, that key is being silently ignored.

For any param table, the safe pattern is:

```python
pk = SomeParamsTable.heading.primary_key   # discover the real PK field name
SomeParamsTable.fetch(*pk)                 # see what values already exist
```

There is no universal `params_name` field — each parameter table has its own (`trodes_pos_params_name`, `decoding_param_name`, `dlc_si_params_name`, `model_params_name`, etc.), and the singular-vs-plural choice varies table-to-table. Always read the heading; don't infer from a sibling table.
