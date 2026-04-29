# Part tables of `Probe`

In DataJoint, every table class exposes a `parts()` classmethod (and, equivalently, an instance method) that returns the part tables attached to it as a master. So the one-liner is just:

```python
Probe.parts()
```

That returns the part-table classes (or their full table names, depending on the `as_objects` flag) that hang off `Probe`.

A couple of common variants if you want the Python classes back rather than the raw `__` table names:

```python
Probe.parts(as_objects=True)          # list of part-table classes
[p.__name__ for p in Probe.parts(as_objects=True)]   # just the short names
```

## The two parts on `Probe`

In `Master.Part` notation:

- `Probe.Shank`
- `Probe.Electrode`

`Probe` itself stores one row per probe type (probe id, manufacturer, num shanks, etc.). `Probe.Shank` enumerates the shanks belonging to each probe, and `Probe.Electrode` enumerates the individual electrode/contact sites on those shanks. Those are the only two part tables defined on `Probe` — there aren't any other `Probe.*` parts to list.

If you wanted to confirm interactively without trusting memory, `Probe.parts()` (or `dj.Diagram(Probe)` in a notebook, which draws the master plus its parts) is the source of truth.
