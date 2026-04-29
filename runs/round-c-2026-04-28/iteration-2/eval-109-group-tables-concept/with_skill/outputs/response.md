## Group tables: a many-to-one aggregation pattern

A **group table** in Spyglass is a `dj.Manual` master with a user-supplied group-name in its primary key, paired with a `dj.Part` table whose rows reference the upstream entries the group includes. The master row says "I am a named bundle"; the part rows enumerate which upstream rows are in the bundle. Downstream Computed/Selection tables then foreign-key the *group* (one row, one name) instead of FK-ing each individual upstream row, which keeps the downstream selection PK from exploding to one-row-per-member.

Two of the three names you listed are group tables. One is not — it's a *parameter* table that happens to live next to one.

## The two real group tables in source

**`SortedSpikesGroup`** — `src/spyglass/spikesorting/analysis/v1/group.py:63-74`

```python
@schema
class SortedSpikesGroup(SpyglassMixin, dj.Manual):
    definition = """
    -> Session
    -> UnitSelectionParams
    sorted_spikes_group_name: varchar(80)
    """

    class Units(SpyglassMixinPart):
        definition = """
        -> master
        -> SpikeSortingOutput.proj(spikesorting_merge_id='merge_id')
        """
```

Master PK = `(nwb_file_name, unit_filter_params_name, sorted_spikes_group_name)`. The `Units` part FKs `SpikeSortingOutput` (a merge master) with `merge_id` projected to `spikesorting_merge_id` — one part row per curated sorting in the group. Use case: bundle several tetrode sortings into one named group like `"ca1_pyramidals_for_decoding"` so a downstream `SortedSpikesDecodingSelection` can FK the group as a single key.

**`PositionGroup`** — `src/spyglass/decoding/v1/core.py:130-143`

```python
@schema
class PositionGroup(SpyglassMixin, dj.Manual):
    definition = """
    -> Session
    position_group_name: varchar(80)
    ----
    position_variables = NULL: longblob
    upsample_rate = NULL: float
    """

    class Position(SpyglassMixinPart):
        definition = """
        -> PositionGroup
        -> PositionOutput.proj(pos_merge_id='merge_id')
        """
```

Master PK = `(nwb_file_name, position_group_name)`. The `Position` part FKs `PositionOutput` with `merge_id` projected to `pos_merge_id` — one part row per position stream included in the group. Use case: bundle multiple position sources (head, body, nose) into one named group consumed by `SortedSpikesDecodingSelection` and `ClusterlessDecodingSelection`.

Notice the shared shape:

- master = `-> Session` + a user-named varchar in the PK,
- part = `-> master` + `-> SomeUpstream.proj(<name>='merge_id')`,
- a `create_group(...)` instance method that inserts master + parts atomically.

The `.proj(...)` rename matters because the upstream is a merge master whose only PK column is `merge_id`; if you didn't rename it, two such FKs in the same downstream relation would collide. Inside the group, `merge_id` becomes `spikesorting_merge_id` / `pos_merge_id`.

## `UnitSelectionParams` is *not* a group table

`UnitSelectionParams` (`src/spyglass/spikesorting/analysis/v1/group.py:18-54`) is a `dj.Manual` **parameter table**:

```python
definition = """
unit_filter_params_name: varchar(32)
---
include_labels = Null: longblob
exclude_labels = Null: longblob
"""
```

It has no part table. It just stores label-filter rows like `"all_units"` (include nothing, exclude nothing) and `"exclude_noise"` (exclude `["noise", "mua"]`). It's listed alongside `SortedSpikesGroup` in the source because `SortedSpikesGroup` FKs it as part of its PK (`-> UnitSelectionParams` on line 66) — the parameter axis tells the group *how to filter the units it grouped*. So it co-travels with the group, but its role is "parameters", not "many-to-one aggregation". Different kind of object.

(The reverse-form check: there's no `UnitSelectionParams.<Part>` class — and a parameter table never has one. That's the structural tell.)

## Group tables are not merge tables

These two patterns share the master + `dj.Part` shape, but solve different problems:

| | Merge table (`*Output`) | Group table (`*Group`) |
|---|---|---|
| Aggregates over | *Versions* of one analysis (e.g. `TrodesPosV1` vs `DLCPosV1`, both fed into `PositionOutput`) | *Many rows* of one analysis bundled into one set |
| Master PK | `merge_id` only (opaque UUID) | User-supplied name + Session (semantic) |
| Part table | One part *per source table* (e.g. `PositionOutput.TrodesPosV1`, `PositionOutput.DLCPosV1`) | One part holding the membership rows |
| Downstream FK target | `merge_id` (caller doesn't care which source) | The group name (caller picks the bundle by name) |
| Helpers | `merge_get_part`, `merge_restrict`, `merge_delete` | `create_group(...)` instance method |

Merge = "I don't care which version produced this row, give me the data behind this `merge_id`." Group = "I want this specific named bundle of N rows treated as one downstream input." `PositionOutput` is a merge master; `PositionGroup` consumes its rows and bundles several into a named group. They sit at adjacent layers, not in a synonym relation.

## When to write your own

You want a group table when:

1. A downstream computation conceptually takes *one* input that is actually *N* upstream rows (set of units, set of position streams, set of LFP channels...).
2. You want the bundle to be named, reusable, and FK-able from multiple downstream tables.
3. Without grouping, the downstream selection's PK would have to balloon to one row per member, and every fetch would have to re-aggregate.

The shape to reach for:

```python
@schema
class FooGroup(SpyglassMixin, dj.Manual):
    definition = """
    -> Session
    foo_group_name: varchar(80)
    ---
    # optional payload (variable lists, scalars; never the membership)
    """

    class Member(SpyglassMixinPart):
        definition = """
        -> master
        -> SomeUpstream.proj(foo_member_id='merge_id')   # rename if upstream is a merge master
        """

    def create_group(self, nwb_file_name, group_name, keys, ...):
        group_key = {"nwb_file_name": nwb_file_name, "foo_group_name": group_name}
        if self & group_key:
            raise ValueError(...)            # or log + return, like PositionGroup
        self.insert1(group_key)
        self.Member.insert([{**k, **group_key} for k in keys])
```

Three things worth pinning down before you ship one:

- **Insert master + parts atomically** in a single classmethod (the `SortedSpikesGroup.create_group` / `PositionGroup.create_group` pattern). Don't make callers remember to populate the part table separately.
- **Decide the existing-name policy.** `SortedSpikesGroup` raises on duplicates; `PositionGroup` logs an error and returns (easier for tests). Pick one and document it.
- **If your upstream is a merge master, rename `merge_id`** in the part FK with `.proj(...)`. Otherwise two such FKs (e.g. unit merge + position merge in the same downstream relation) would collide on the column name.

If you'd like the worked end-to-end example (creating a `SortedSpikesGroup` and FK-ing it from a decoding selection), that's in `skills/spyglass/references/group_tables.md` — happy to walk through it.
