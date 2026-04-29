# `SpyglassMixin.get_pk()` — does it exist?

Short answer: I can't confirm that `SpyglassMixin` has a `.get_pk()` method, and I'm not going to invent a signature for one. I don't have a Spyglass reference loaded in this session, so anything I'd write down (parameter list, return type, docstring) would be a guess. Please verify before relying on it.

## The standard DataJoint idiom does what you want

For "give me the primary-key dict for every row in my current restriction," DataJoint already provides two well-established patterns, and `SpyglassMixin` inherits from `dj.Manual` / `dj.Computed` / etc., so these work on every Spyglass table:

```python
restricted = MyTable & restriction

# Option 1: the canonical shortcut — returns a list of PK dicts
pk_dicts = restricted.fetch('KEY')

# Option 2: project to PK columns, then fetch as dicts
pk_dicts = restricted.proj().fetch(as_dict=True)
```

`fetch('KEY')` is the idiomatic one and is what most Spyglass / DataJoint code uses when it wants to iterate over keys (e.g. to feed `populate(key)` or `(OtherTable & key).fetch1(...)`). It returns a `list[dict]`, one dict per row, containing only the primary-key attributes.

Both forms also accept the usual fetch kwargs (`order_by=`, `limit=`, etc.).

## How to verify whether `get_pk` actually exists

Before writing code that depends on it, check directly — don't trust my recollection or yours:

```python
from spyglass.utils import SpyglassMixin
'get_pk' in dir(SpyglassMixin)            # quick membership check
[m for m in dir(SpyglassMixin) if 'pk' in m.lower()]  # fuzzy
help(SpyglassMixin.get_pk)                # will raise AttributeError if absent
```

Or grep the source of the mixin module itself (typically `src/spyglass/utils/dj_mixin.py` in the Spyglass repo):

```bash
grep -n "def get_pk" src/spyglass/utils/dj_mixin.py
grep -rn "def get_pk" src/spyglass/
```

If those come back empty, the method doesn't exist and your memory is conflating it with something else (possibly DataJoint's `.primary_key` *attribute*, which is a list of PK *column names*, not a list of PK dicts — different thing).

## What I'm explicitly *not* doing

- Not writing out `def get_pk(self, ...) -> list[dict]: ...` or a fake docstring.
- Not guessing whether it takes a restriction argument, an `as_dict` flag, or returns a numpy recarray vs. a list.
- Not claiming it was added in some particular Spyglass version.

If `dir(SpyglassMixin)` does turn up a `get_pk`, paste `inspect.signature(SpyglassMixin.get_pk)` and `SpyglassMixin.get_pk.__doc__` and I can comment on it then. Until then, `(Table & restriction).fetch('KEY')` is the safe, documented path.
