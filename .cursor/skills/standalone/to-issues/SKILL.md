---
name: to-issues
description: Breaks a plan, spec, or PRD into independently-grabbable GitHub issues using tracer-bullet vertical slices. Use when the user wants implementation tickets created from a plan, wants a spec decomposed into reviewable issues, or wants integration bugs split into one-test-per-behavior slices with TDD-style acceptance criteria.
---

## To Issues

Break a plan into independently-grabbable GitHub issues using vertical slices (tracer bullets).

### Process

#### 1) Gather context

- Work from whatever is already in the conversation context.
- If the user passes a GitHub issue number or URL, fetch it with `gh issue view <number>` (include comments).

#### 2) Explore the codebase (optional)

If you have not already explored the codebase, explore it enough to understand the current state.

#### 3) Draft vertical slices

Break the plan into tracer-bullet issues.

- Each issue is a **thin vertical slice** that cuts through all integration layers end-to-end (not a horizontal slice of one layer).
- A completed slice is **demoable or verifiable** on its own.
- Prefer **many thin** slices over **few thick** ones.

Each slice must be marked:

- **AFK**: can be implemented and merged without human interaction.
- **HITL**: requires human interaction (e.g., architecture decision, product/design review).

Prefer **AFK** over **HITL** where possible.

**Integration / API behavior (TDD-aligned slices)**

When the backlog is webhook handling, TikTok API edge cases, or shop-scoped data bugs, shape slices so each issue is **one behavior**, not a mega-fix:

- **Finding issues**: turn each failure mode into **one failing test** with a **minimal fixture** (sample webhook payload, mocked TikTok JSON, or DB seed) and a **single expectation** on the public interface (`create_app`, repo method, or API response).
- **Naming**: test and issue titles should name the scenario (e.g. duplicate `order_status_change`, expired refresh token, empty inventory page) so CI output is actionable.
- **Implementing**: **RED** → **GREEN** → **REFACTOR** per slice. Match existing test layout: `tests/unit/` for Python, `apps/demo/src/__tests__/`, `apps/dashboard/src/__tests__/`, and `ios/Tests/` for clients.

Repository pattern: follow `tests/unit/test_scoring.py` and webhook/API tests — one behavior per test class or `describe` block; do not introduce a second fixture convention.

#### 4) Quiz the user

Present the proposed breakdown as a numbered list. For each slice, show:

- **Title**: short descriptive name
- **Type**: HITL / AFK
- **Blocked by**: which other slices (if any) must complete first
- **User stories covered**: which user stories this addresses (if the source material has them)

Ask the user:

- Does the granularity feel right? (too coarse / too fine)
- Are the dependency relationships correct?
- Should any slices be merged or split further?
- Are the correct slices marked as HITL and AFK?

Iterate until the user approves the breakdown.

#### 5) Create the GitHub issues

For each approved slice, create a GitHub issue using `gh issue create`.

- Create issues in **dependency order** (blockers first) so you can reference real issue numbers in the "Blocked by" field.
- Do **not** close or modify any parent issue.

Use this body template.

### Issue body template

## Parent
#<parent-issue-number>
<!-- If the source was a GitHub issue, otherwise omit this section.
     The number on its own line, `#` optional, NOTHING else on that line.
     `ensure_workflow_cache.py::PARENT_LINE_RE` parses this, and
     `meta_prepare_executor.py` — the mandatory Meta gate — halts with
     "Cannot resolve parent" when it cannot. A prose label such as
     `PRD #1228` is tolerated only for the enumerated set
     PRD|Epic|Issue|Parent; anything else (`See #5`, `Blocked by #12`)
     is rejected by design, so write the bare reference.
     All 17 W4/W5 issues shipped with `PRD #<n>` and halted the gate. -->

## What to build
<!-- Describe end-to-end behavior, not layer-by-layer implementation -->

## Acceptance criteria
- Criterion 1
- Criterion 2
- Criterion 3
<!-- Integration slice example: one new pytest with minimal webhook/API fixture; single public-behavior assertion; no unrelated module churn. -->

## Blocked by
<!-- "None - can start immediately" OR "Blocked by #123" -->


---

## Acceptance criteria — worked examples

An AC is met when a **behavior is observable**, not when a function exists. Both
examples below are real, from this repo.

### Bad — unit-shaped. This shipped.

Issue #721 carried a criterion of roughly this shape:

```
- Compute suggested reorder quantity from sales velocity
```

The executor wrote `compute_reorder_quantity`, unit-tested it, and never called
it from any product code path. **The criterion was satisfied exactly as written**
and the seller saw nothing. Review caught it; the AC could not, because nothing
in it required the behavior to be reachable.

The tell: the criterion names a *computation*. You can satisfy it without the
product changing.

### Good — same intent, observable

```
- GIVEN a shop with a SKU forecast to stock out within the lead-time window
  WHEN the seller opens the `replenish_inventory` action card
  THEN `GET /v1/action-cards/{key}/inputs` returns a `reorder_quantity` derived
  from that SKU's velocity, plus a `basis` that explains the number
  Observable at: api/routes/action_cards.py::get_action_card_inputs
  Verified by:   tests/unit/test_action_card_inputs_contract.py::test_ac1_returns_computed_reorder_quantity_for_highest_urgency_item
```

**`Observable at:` is the load-bearing line.** It names where the behavior
surfaces, so "built but never wired" cannot satisfy the criterion. `Verified by:`
names the test — write it in the issue even though the test does not exist yet;
that name is what the executor creates and what the gates probe.

Keep the GIVEN/WHEN/THEN prose natural. The grammar is not the point — a
criterion that reads `GIVEN the system WHEN the code runs THEN it works`
satisfies the shape and means nothing. The two named lines are what make it
checkable.

### Writing the paired test

Each AC gets one test, and the test must **fail before the change exists**. A
test that passes against unmodified source proves nothing about the work.

**Bad — pins a value that already holds:**

```python
def test_reorder_basis_uses_three_day_lead_time():
    assert basis["lead_time_days"] == 3      # passes before the fix too
```

This is the `assert True` family. It is green on day one, so it never went red,
and it will not notice the defect it was written for.

**Good — pins the coupling, from `test_action_card_inputs_contract.py`:**

```python
# A lead time that is deliberately NOT the default, so a hardcoded 3 shows up.
with patch("juli_backend.api.routes.action_cards.REORDER_LEAD_TIME_DAYS", 7):
    response = await auth_client.get("/v1/action-cards/replenish_inventory_1/inputs")

basis = response.json()["data"]["basis"]
assert basis["lead_time_days"] == 7
expected = math.ceil(basis["daily_velocity"] * (basis["lead_time_days"] + basis["safety_stock_days"]))
assert response.json()["data"]["reorder_quantity"] == expected
```

The route previously re-typed `lead_time_days=3` beside a call that used the
function's own defaults. Pinning `3` would not have caught it — the values agreed
by coincidence. Moving the policy and asserting **both halves follow** is what
catches it.

The rule: **pin the relationship, not the number.** Ask "would this test have
been red yesterday?" If not, it is not evidence.
