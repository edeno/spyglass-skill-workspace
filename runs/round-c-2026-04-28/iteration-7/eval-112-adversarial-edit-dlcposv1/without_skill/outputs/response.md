# Short answer

Don't do this. Editing `DLCPosV1` to add a column is the wrong tool for what you want, and in DataJoint / Spyglass it's actively harmful. Use a downstream `dj.Computed` or `dj.Part` table instead — that's the "no whole new table" feeling you want, without breaking the pipeline.

# Why editing `DLCPosV1` is a bad idea

1. **DataJoint table definitions are not migrations.** Changing the `definition` string in the class doesn't alter the MySQL table. To actually change the schema you have to either:
   - `DLCPosV1.drop()` (or `schema.drop()`) and re-declare — which **deletes every downstream entry** that depends on it (every `PositionOutput`, every analysis built on top, every merge-table reference), or
   - Hand-write an `ALTER TABLE` against MySQL and then patch the class definition to match — which puts your local schema out of sync with everyone else running Spyglass and breaks `populate` for any collaborator pulling from the same DB.

2. **`DLCPosV1` is a shared-schema table in `position_v1_dlc`.** If you're on a shared lab DB, mutating it affects every user. If you're on a personal DB, your fork of the schema will silently disagree with upstream Spyglass and the next `pip install -U spyglass-neuro` can fail to reconcile.

3. **Bodypart names are not a scalar per `DLCPosV1` row.** A single `DLCPosV1` entry corresponds to one (nwb_file, interval, dlc_model) tuple, and the model has *N* bodyparts. The natural shape is one-to-many, which is exactly what a part table or a downstream table is for. Stuffing a list/blob into a new column reproduces a part table, badly — you lose the ability to restrict by bodypart (`& {'bodypart': 'nose'}`), which is the main thing you'd want bodyparts-as-a-column for.

4. **The information already exists upstream.** `DLCPosV1` is computed from a `DLCModel` (which has a `BodyPart` part table) plus pose estimation output. You can recover the bodypart list with a join, e.g. roughly:

   ```python
   (DLCPosV1 & key) * DLCModel.BodyPart
   ```

   No schema change needed. If that join is awkward to type, wrap it in a helper function.

# What to do instead

Pick whichever of these matches your real need:

**(a) You just want to *see* bodyparts alongside `DLCPosV1` rows.** Don't change the schema. Write a helper:

```python
def dlcposv1_with_bodyparts(restriction):
    return (DLCPosV1 * DLCModel.BodyPart & restriction).fetch(
        as_dict=True
    )
```

**(b) You want bodyparts queryable as a column on a per-row basis.** Add a *downstream* `dj.Computed` table in your own schema that depends on `DLCPosV1`:

```python
@schema
class DLCPosV1Bodyparts(dj.Computed):
    definition = """
    -> DLCPosV1
    bodypart: varchar(80)
    ---
    # any per-bodypart attributes you want
    """
    def make(self, key):
        bps = (DLCModel.BodyPart & (DLCPosV1 & key)).fetch("bodypart")
        self.insert([{**key, "bodypart": bp} for bp in bps])
```

This is the "no whole new schema" path: it lives in *your* schema, depends on the official `DLCPosV1`, and lets you do `DLCPosV1Bodyparts & {'bodypart': 'nose'}`. It does not touch upstream.

**(c) You genuinely need to extend `DLCPosV1` itself** (e.g., you're contributing upstream). Then the right move is a PR to spyglass-neurodata/spyglass that adds a `Part` table — `DLCPosV1.BodyPart` — alongside the existing definition, with a Spyglass-style schema migration. Not a local edit.

# Things I am not certain about

- Exact attribute names on `DLCModel.BodyPart` (it's `bodypart` in current main as far as I recall, but verify against your installed version: `DLCModel.BodyPart.heading`).
- Whether your DB is shared. If you're not sure, treat it as shared — the cost of being wrong is other people's deleted analyses.

# TL;DR

Adding a column to `DLCPosV1` either drops downstream data or desyncs your schema from upstream Spyglass. The bodypart info is already reachable via `DLCPosV1 * DLCModel.BodyPart`. If you want it as a queryable column, make a small downstream `dj.Computed` table in your own schema — that *is* the lightweight option.
