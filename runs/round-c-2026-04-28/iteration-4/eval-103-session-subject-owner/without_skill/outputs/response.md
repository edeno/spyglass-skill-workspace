I can't tell you whose animal Wilbur is from training data alone — that depends on your specific Spyglass database. But I can show you exactly how to find out.

## Where the link lives

In Spyglass, the chain is:

```
Subject (subject_id="wilbur")  ->  Session  ->  LabMember
```

- `common_subject.Subject` stores the animal (subject_id, species, sex, DOB, etc.).
- `common_session.Session` has one row per recording session and references `Subject` via `subject_id`. It also has a `session_id` and a `nwb_file_name`.
- `common_session.Session.Experimenter` is a **part table** of `Session` that lists the lab members who ran each session, joining to `common_lab.LabMember` via `lab_member_name`.

So "who runs Wilbur's sessions" = experimenters on `Session.Experimenter` for sessions whose `subject_id = 'wilbur'`.

## Query to run

```python
import datajoint as dj
from spyglass.common import Subject, Session, LabMember

# 1. Confirm the subject exists and see how the ID is spelled.
#    subject_id is case-sensitive; try a LIKE if "wilbur" doesn't hit.
(Subject & 'subject_id LIKE "%ilbur%"')

# 2. Sessions for Wilbur
wilbur_sessions = Session & 'subject_id = "wilbur"'
wilbur_sessions  # inspect: session_id, nwb_file_name, session_description, session_start_time

# 3. Experimenters on those sessions (the part table)
experimenters = (Session.Experimenter & wilbur_sessions.proj())
experimenters  # lab_member_name per session

# 4. Join to LabMember for contact info / full name
(LabMember & experimenters.proj()) \
    * experimenters
```

That last expression gives you, per Wilbur session: `nwb_file_name`, `lab_member_name`, plus whatever `LabMember` carries (`first_name`, `last_name`, and via `LabMember.LabMemberInfo`, often google account / email / DataJoint username).

## Practical tips

- **Spelling.** Subject IDs are free-text. Try `"wilbur"`, `"Wilbur"`, `"wilbur1"`, etc. The `LIKE "%ilbur%"` probe above catches variants.
- **Multiple experimenters per session are normal** — `Session.Experimenter` is a part table precisely so several people can be listed. The person who actually ran the rig day-to-day is usually the same name across all of Wilbur's sessions; that's your best lead.
- **If `Session.Experimenter` is empty** (sometimes happens if the NWB file didn't populate it), fall back to:
  - `Nwbfile` and look at the file path / who owns it on disk.
  - `IntervalList` or `TaskEpoch` insertions — `LabTeam` membership often correlates with subject ownership in Frank-lab-style setups.
  - Ask whoever maintains the shared NWB directory; the per-subject folder is usually owned by one person.
- **Task info**, once you know the owner, lives in `common_task.Task` and `common_task.TaskEpoch` joined against Wilbur's sessions:
  ```python
  from spyglass.common import TaskEpoch, Task
  (TaskEpoch * Task) & wilbur_sessions.proj()
  ```
  That'll show you the task names (e.g. `"sleep"`, `"lineartrack"`, `"wtrack"`) per epoch, which is useful context to bring when you go ask the owner.

Run step 3, note the `lab_member_name`(s), and that's your person.
