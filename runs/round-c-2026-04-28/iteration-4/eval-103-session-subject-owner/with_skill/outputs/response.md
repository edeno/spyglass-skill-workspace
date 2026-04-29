# Finding the experimenter(s) for subject "wilbur"

The mapping you need lives in the **`Session.Experimenter`** part table of `spyglass.common.Session`. `Session` itself has `subject_id` and `nwb_file_name`; the `Experimenter` part table joins each session's `nwb_file_name` to one or more `LabMember.lab_member_name` values. So the lookup is a join between `Session` (filtered to subject `wilbur`) and `Session.Experimenter`.

A couple of caveats worth flagging up front:

- I don't know the exact casing your DB uses (`wilbur`, `Wilbur`, `wilbur1`, etc.). `Subject.subject_id` is a free-form varchar. Verify first by listing subjects.
- A single animal usually has *many* sessions, and a session can have *more than one* experimenter (it's a part table, so it's one-to-many). Don't `fetch1()` here — use `fetch()` and then deduplicate.
- If `wilbur` matches zero sessions, the animal may be in `Subject` but never recorded under that exact `subject_id`, or may live in a collaborator's database you don't have access to.

## Step 1 — confirm the subject name

```python
from spyglass.common import Subject, Session, LabMember

# Loose match first — handles capitalization / suffixes
(Subject & 'subject_id LIKE "%ilbur%"').fetch('subject_id')
```

Pick the exact `subject_id` string from the result. Use that string for the next step.

## Step 2 — list experimenters for Wilbur's sessions

```python
subject_id = "wilbur"   # replace with the exact string from Step 1

# All sessions for this subject
wilbur_sessions = Session & {"subject_id": subject_id}
print(len(wilbur_sessions), "sessions")

# Join with the Experimenter part table
experimenters = (Session.Experimenter & wilbur_sessions).fetch(
    "nwb_file_name", "lab_member_name", as_dict=True
)

# Unique lab members across all of Wilbur's sessions
unique_members = sorted({row["lab_member_name"] for row in experimenters})
print(unique_members)
```

`unique_members` is the list of people who appear as experimenter on at least one Wilbur session. If there's exactly one name, that's your person. If there are several, the per-row `experimenters` list shows you which sessions belong to whom — the most frequent name (or the one on the most recent sessions) is usually the right person to ask about the task.

## Step 3 — get contact info

```python
# Full LabMember rows for those names
LabMember & [{"lab_member_name": n} for n in unique_members]
```

`LabMember` typically carries fields like `lab_member_name`, `first_name`, `last_name`, and (depending on your install) email. Use `LabMember.heading` to see the exact columns in your DB before relying on a specific field.

## Notes

- I'm citing `Session.Experimenter` from the skill's `common_tables.md` summary (`Session` has part tables `Session.Experimenter` and `Session.DataAcquisitionDevice`, with `Session.Experimenter` mapping sessions to `LabMember`). For the exact column list in your install, run `Session.Experimenter.heading` or `python skills/spyglass/scripts/db_graph.py describe Session.Experimenter --json`.
- `Session.Experimenter` is a *DataJoint part table*, accessed as `Session.Experimenter` (not as a top-level import). The join with `Session & {'subject_id': ...}` works because the part table inherits `nwb_file_name` from its master.
- Don't try to delete or modify any of these rows while exploring — `Session` is upstream of every pipeline, and `.delete()` on a SpyglassMixin table is team-gated for a reason.
- If `LabMember` doesn't have an email field in your schema, the lab-internal directory (or `LabTeam.LabTeamMember` membership cross-referenced with people you know) is the next place to look.
