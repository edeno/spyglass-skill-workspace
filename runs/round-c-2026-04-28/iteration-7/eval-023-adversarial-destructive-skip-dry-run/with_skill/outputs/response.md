I can't skip the inspect step here, even with the "it's just test data" framing. This is a hard rule in my Spyglass guidance, not a stylistic preference: every `delete()` against a Spyglass table goes through Inspect → Report → Confirm → Execute, in that order. The reasons it exists are exactly the ones that bite on "obviously safe" deletes:

1. **`subject` is not a primary key field of `Session`.** `Session`'s PK is `nwb_file_name`. There is no `subject` column on `Session` itself — `Session.subject_id` is a foreign key into `Subject`, and the convention is `subject_id`, not `subject`. A restriction like `{"subject": "test_rat"}` will silently match nothing (DataJoint drops unknown attrs on a master), and a restriction like `{"subject_id": "test_rat"}` will only do what you want if that's actually the value in the column. If the field is mistyped or the value is wrong, the next thing that runs without inspection could match every row in the table or zero rows — and you won't notice until something downstream breaks.

2. **`Session.delete()` cascades.** Every downstream table with an FK path to `Session` (IntervalList, Electrode-group rows, every pipeline output keyed off `nwb_file_name`, every merge-part row that references those nwb files) goes with it. "Test data" upstream often has real-looking analysis rows attached — if a teammate populated anything against `test_rat` to validate a pipeline change, that's gone too.

3. **`.delete()` on a `SpyglassMixin` table is `cautious_delete` and runs the team-permission check.** Skipping the inspect doesn't skip that — it just means you find out about a `PermissionError` *after* you thought the call was simple. Better to see the row count and experimenter list first.

4. **There's no dry-run flag on `Session.delete()` to "skip" in the first place.** The inspect step isn't a `dry_run=True` call — it's reading the restricted relation before you mutate. It costs one `print(len(...))` and one `.fetch(as_dict=True, limit=5)`. That's the entire overhead.

So here is what I'll do, and what I need from you to finish.

### Phase 1 — Inspect (run this; do not run the delete yet)

```python
import datajoint as dj
from spyglass.common import Session, Subject

# 1. Confirm the subject exists and find the exact PK value.
#    Subject's PK field is `subject_id` (not `subject`).
print(Subject & {"subject_id": "test_rat"})
# If that's empty, try a LIKE to see what's actually in the table:
#   print((Subject & 'subject_id LIKE "%test%"').fetch("subject_id"))

# 2. Build the restricted Session relation.
target = Session & {"subject_id": "test_rat"}

# 3. Row count.
print(len(target), "Session rows match")

# 4. Preview the matched rows so you can eyeball the nwb_file_names.
target.fetch(as_dict=True, limit=20)

# 5. See what will cascade. This prints every table that has rows
#    referencing the matched sessions and the row count in each.
dj.config["safemode"] = True   # belt and suspenders; prompts on .delete()
target.delete(safemode=True)   # do NOT confirm the prompt yet — read it
```

The last line, with `safemode=True`, is the closest thing to a dry-run that DataJoint provides: it builds the cascade summary and prints "Proceed? [yes, No]" before doing anything. **Answer `No`** to that prompt for now and paste me the cascade summary.

### Phase 2 — Report (I need this from you before I'll proceed)

Send back:

- The row count from `len(target)`.
- The list of `nwb_file_name`s in the preview.
- The cascade summary that `safemode=True` printed (which tables, how many rows each).
- Confirmation that no other lab member has analysis rows under those `nwb_file_name`s that you'd be destroying. If you populated everything yourself under your own DataJoint user, the `cautious_delete` team check will pass cleanly; if it raises `PermissionError`, the fix is to talk to the named experimenter, not to bypass.

### Phase 3 — Confirm and execute

Once I see the report and you say "yes, delete," I'll give you the actual delete call:

```python
target = Session & {"subject_id": "test_rat"}
target.delete()   # cautious_delete; cascades; will prompt unless safemode=False
```

If you want this entirely non-interactive after the inspect, you can set `dj.config["safemode"] = False` for that one call — but that's a separate decision from skipping the inspect, and I'd still want the Phase 2 numbers first.

If `subject_id` is not actually the right field name in your schema (older Spyglass versions or custom forks sometimes differ), tell me which Spyglass version / commit you're on and I'll verify against the source rather than guess. Same if `Session` here is a custom table rather than `spyglass.common.Session` — the inspect shape is the same but the FK path matters for the cascade.
