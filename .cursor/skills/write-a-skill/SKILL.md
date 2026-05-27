---
name: write-a-skill
description: Creates new agent skills with a consistent folder structure, progressive disclosure, and bundled resources. Use when a user asks to create/write/build a new skill, or when adding reusable agent capabilities.
---

## Write a Skill

### Quick start

- Create a new folder at `skills/<skill-name>/`
- Add `SKILL.md` with the required frontmatter (`name`, `description`)
- Keep `SKILL.md` short; move long content to `REFERENCE.md` / `EXAMPLES.md`

### Workflow

#### 1) Gather requirements

Ask (and record answers in the skill itself):

- **Domain/task**: What does the skill do?
- **Use cases**: What are the top 3–5 things it must handle?
- **Assets**: Instructions only, or scripts/templates too?
- **References**: Any docs/examples to bundle?

#### 2) Draft the skill

Create:

- **`SKILL.md`**: concise instructions and the most common path
- **Optional `REFERENCE.md`**: deeper details, edge cases, checklists
- **Optional `EXAMPLES.md`**: copy/paste examples
- **Optional `scripts/`**: deterministic helpers (formatting, validation, scaffolding)

#### 3) Review

Share the draft and confirm:

- Does it cover the required use cases?
- Anything missing/unclear?
- Any section too detailed or not detailed enough?

### Skill structure

```
skills/<skill-name>/
  SKILL.md
  REFERENCE.md        # optional
  EXAMPLES.md         # optional
  scripts/            # optional
```

### Quality bar

- **Description**: third-person; 2 sentences; sentence 2 starts with “Use when …”; <= 1024 chars
- **Progressive disclosure**: common path in `SKILL.md`, deep details in `REFERENCE.md`
- **Splitting**: if `SKILL.md` would exceed ~100 lines, split

