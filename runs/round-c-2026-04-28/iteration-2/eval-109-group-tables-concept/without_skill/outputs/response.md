# What is a "group table" in Spyglass?

Short answer: in the Spyglass / DataJoint idiom, a **group table** is a small naming-and-bundling pattern that lets you take a *set* of upstream rows (often heterogeneous-looking, but conceptually "same kind of thing") and refer to them by a single user-defined name so downstream pipeline stages can foreign-key against the group instead of against every individual upstream row.

`SortedSpikesGroup` and `PositionGroup` are both instances of that pattern. `UnitSelectionParams` is *not* — it's a parameter table that happens to live nearby. More on that below.

---

## The shape of a group table

A group table is almost always two related DataJoint tables:

1. A **master** table (typically `dj.Manual`) whose primary key is essentially `(some upstream context, group_name)`. The master row is just a label — "I am calling this bundle `'CA1_left_hemisphere'`".
2. A **`dj.Part`** table hanging off the master, with one row per upstream entry that belongs in the group. Its primary key extends the master's PK with a foreign key to the upstream row (often a *merge table*'s `merge_id`, renamed via `.proj(...)` so the column names don't collide).

Sketch:

```python
@schema
class SortedSpikesGroup(SpyglassMixin, dj.Manual):
    definition = """
    -> Session
    -> UnitSelectionParams
    sorted_spikes_group_name : varchar(80)
    """

    class Units(SpyglassMixin, dj.Part):
        definition = """
        -> master
        -> SpikeSortingOutput.proj(spikesorting_merge_id='merge_id')
        """
```

Two things to notice:

- The relationship is **many-to-one**: many `Units` part-rows roll up into one master row. That's the whole point — bundle N curated sortings into one named group, then downstream decoders FK to the *group*, not to N individual sortings.
- The part table reaches into a *merge table* (`SpikeSortingOutput`) and uses `.proj()` to rename `merge_id` to a more descriptive local name (`spikesorting_merge_id`). This is idiomatic in Spyglass because most pipeline outputs are funneled through merge tables.

`PositionGroup` follows the same template, just for position data — its part table FKs into `PositionOutput` (the position merge table) and the master is keyed by `(Session, position_group_name)`. The motivation is the same: a decoding selection wants to say "use *this* bundle of position sources" without having to enumerate them every time.

So the two concrete examples in Spyglass that fit this pattern are:

- **`SortedSpikesGroup`** — bundles one or more curated spike sortings (from `SpikeSortingOutput`).
- **`PositionGroup`** — bundles one or more position sources (from `PositionOutput`).

---

## Group table vs. merge table — different problems

It's easy to conflate the two because both involve "many things flowing into one downstream thing", but they solve different problems:

| | Merge table | Group table |
|---|---|---|
| Problem | "I have several **interchangeable implementations** of one analysis (e.g. `TrodesPosV1`, `DLCPosV1`) and downstream code shouldn't care which produced a given row." | "I have several **rows of one analysis** that I want to treat as a single named bundle for a downstream computation." |
| Key | One `merge_id` per upstream row, plus part tables that map back to each implementation. | One group name per bundle, with a `dj.Part` listing the member rows. |
| Cardinality at the master | One master row per *upstream row*. | One master row per *bundle of upstream rows* (many-to-one aggregation). |
| Example | `PositionOutput` makes downstream code position-source-agnostic. | `PositionGroup` lets a decoder say "use these three position rows as a unit." |

A group table very often **points into** a merge table (via `.proj()` on `merge_id`), which is why they show up together. But they are not the same construct.

---

## What about `UnitSelectionParams`?

`UnitSelectionParams` is **not** a group table. It's a `dj.Manual` **parameter table** — the standard DataJoint pattern of "a small table whose rows describe a parameter set, referenced by a `*_params_name` PK." Its job is to store unit-inclusion criteria (e.g. which curation labels to keep / drop) under a named key.

The reason it shows up in the same conversation is that `SortedSpikesGroup` foreign-keys to it:

```
-> Session
-> UnitSelectionParams         # parameter axis of the group
sorted_spikes_group_name : ...
```

i.e. when you create a sorted-spikes group, you also commit to a particular unit-selection policy. So `UnitSelectionParams` is part of `SortedSpikesGroup`'s **primary key** (a parameter axis), but conceptually it plays the role of "knobs", not "bundle". A useful test: a parameter table's rows can be reused across many groups; a group table's rows *are* the bundles.

---

## When would you make one of your own?

Author a group table whenever you find yourself writing downstream code that takes "a list of upstream rows" as input and you want that list to be:

- **Named** — so you and collaborators can refer to "the dorsal-CA1 sortings for this animal" without re-enumerating each time.
- **Provenance-tracked** — DataJoint records exactly which rows went into the group, and downstream computeds depend on the group key, not on free-floating lists.
- **FK-able** — downstream Computed/Selection tables can put `-> MyGroup` in their definition and `populate()` per group.

Concrete signs you want one:

- A downstream `make()` method would otherwise loop over multiple sortings / position sources / LFP channels and concatenate or co-process them.
- You want users to define the bundle once (via a `create_group(...)` classmethod) and then re-use it across many downstream computations / parameter sweeps.
- The bundle membership is a *modeling* choice (which units, which cameras) that you want versioned alongside data.

Counter-signs (don't reach for a group table):

- You only ever want *one* upstream row at a time downstream — just FK directly.
- You want to abstract over different *implementations* of the same analysis — that's a merge table.
- The bundle is really a parameter set (thresholds, flags) — that's a parameter table.

### Skeleton for your own group table

```python
@schema
class MyAnalysisGroup(SpyglassMixin, dj.Manual):
    definition = """
    -> Session
    my_analysis_group_name : varchar(80)
    """

    class Members(SpyglassMixin, dj.Part):
        definition = """
        -> master
        -> SomeUpstreamMergeTable.proj(some_merge_id='merge_id')
        """

    @classmethod
    def create_group(cls, session_key, group_name, member_keys):
        master_key = {**session_key, "my_analysis_group_name": group_name}
        # Insert master + parts inside one transaction so partial groups
        # never end up in the database.
        with cls.connection.transaction:
            cls.insert1(master_key, skip_duplicates=True)
            cls.Members.insert(
                [{**master_key, **m} for m in member_keys],
                skip_duplicates=True,
            )
```

Key conventions worth mirroring from the existing Spyglass examples:

- Inherit `SpyglassMixin` on both master and part so you get the standard fetch/cleanup helpers.
- Use `.proj(local_name='merge_id')` when the upstream is a merge table — keeps merge keys distinguishable when multiple merge tables co-mingle downstream.
- Provide a `create_group(...)` classmethod that inserts master + parts atomically; ad-hoc `insert1` calls into the master without populating the part are a common source of dangling groups.
- Keep parameter axes (selection criteria, thresholds) in a *separate* parameter table that the group FKs to — don't pack them into the group name.

---

## TL;DR

- **Group table** = many-to-one bundling pattern: a `dj.Manual` master keyed by `(... , group_name)` plus a `dj.Part` listing the member upstream rows. `SortedSpikesGroup` and `PositionGroup` are the canonical examples.
- **Not** the same as a **merge table**, which abstracts over interchangeable implementations of one analysis via a single `merge_id`.
- **`UnitSelectionParams`** is a parameter table feeding `SortedSpikesGroup`'s primary key — same neighborhood, different role.
- Make your own when you want a named, provenance-tracked, FK-able bundle of upstream rows feeding a downstream computation.
