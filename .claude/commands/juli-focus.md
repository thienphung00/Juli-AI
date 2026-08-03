---
description: Run the Focus router in this session and emit a Context Plan without entering any pipeline.
argument-hint: [task description]
---

Run the `focus` skill for: **$ARGUMENTS**

Do this in the main session — do not dispatch a subagent, and do not enter the Review,
Executor, or Validate pipelines. This is the ad-hoc path: Focus only.

Produce the Context Plan with all four sections explicit:

- **Load** — docs, rules, skills, MCPs to load now
- **If needed** — load only on a specific trigger
- **DO NOT load** — including anything from the parent epic's `doNotLoad`
- **Agent phase** — which phase this task belongs to, and the next command

Name the executor domain if the task is implementation work, but stop there — assigning it
is Meta's job.
