# ADR-057: Pre-user delivery stays on the single VPS — ADR-035's platform superseded, its evidence contract retained

**Status:** Accepted
**Date:** 2026-08-07
**Deciders:** grill-with-docs (Architect), PRD [#820](https://github.com/thienphung00/Juli-AI/issues/820)

**Supersedes (in part), for the pre-user phase only:**
[ADR-035](035-public-release-evidence-and-automatic-rollback.md) — its **platform** paragraph
(AWS ECS on Fargate, ALB, ECR, GitHub Actions OIDC, CloudWatch synthetics) and the consequence
that "a single VPS with two local ports does not meet this boundary". ADR-035's **release
evidence contract, candidate isolation, automatic cutover, automatic rollback, metadata
honesty, and Meta halt gate are retained unchanged** and remain the authority those gates cite.

**Reinstates (in part):**
[ADR-020](020-vps-ssh-continuous-delivery-and-secrets-manager.md) — its single-VPS /
"no new compute infra" constraint and its single `~/releases` pool. ADR-020's *manual-only*
rollback is **not** reinstated.

**Related:** [ADR-003](003-ai-native-cicd-policy.md) (artifact-driven gates) ·
[ADR-017](017-product-monorepo-deployment-architecture.md) (monorepo deploy split) ·
[ADR-027](027-database-migration-safety-pipeline.md) (migration safety) ·
[#498](https://github.com/thienphung00/Juli-AI/issues/498) (the cloud PRD, deferred and
retitled, **open**) · `docs/product/phases/phase-0-delivery/PRD.md`

---

## Context

ADR-035 was accepted on 2026-07-24 after the Demo deployment proved that a reachable HTML
document and a zero-exit deploy command do not prove a usable public application: stylesheets
and scripts can fail while localhost health checks stay green. That diagnosis was correct and
nothing since has weakened it.

ADR-035 answered it with two things bundled into one decision: a **release evidence contract**
(what must be proven before a release counts as successful) and a **platform** on which to
prove it (ECS/Fargate + ALB + ECR + OIDC + CloudWatch). Only the second has turned out to be
wrong for the phase we are actually in.

Three facts, none of which held or were visible when ADR-035 was written:

1. **There are still no users.** ADR-035 called ECS the "pre-user release platform"; two weeks
   later the platform has not been built, and the thing blocking a first user is the *delivery
   path*, not the product. Weeks of cloud infrastructure work produce no user-facing value and
   start a recurring bill before the first seller exists. The NAT gateway alone — accepted in
   #498 as "a deliberate pre-user cost trade-off" — is a monthly charge against zero revenue.
2. **The evidence contract does not actually require separate hardware.** The property the
   contract needs is *the public cannot reach the candidate while it is being proven*. ADR-035
   asserted that only independent deployment targets plus an isolated test route can supply
   that, and wrote off "a single VPS with two local ports". A candidate bound to loopback on
   the existing box supplies the same property by a cheaper mechanism: it is not merely
   restricted from the public, it is unreachable from the public network at all.
3. **The delivery defect is an ordering defect, not a platform defect.** Today the release
   mutates first and verifies second, so a failing check finds a broken version already public.
   Inverting the order — prove the candidate, then switch traffic — retires that risk on any
   platform. Buying ECS to fix an ordering bug is paying for the wrong thing.

What ECS/Fargate genuinely buys that the VPS does not is **high availability**: surviving the
loss of a machine. That is real, and it is not delivered here. It is the substance of what is
being deferred, and it is why this deferral needs a trigger rather than a hope.

The alternative to deciding this explicitly is drift: #498 quietly stops being worked on,
nobody records why, and in six months no one can tell whether the cloud platform was rejected,
postponed, or forgotten.

---

## Decision

**For the pre-user phase, public delivery stays on the existing single VPS
(2 vCPU / 4 GB RAM / 80 GB disk). ADR-035's release evidence contract is retained in full and
re-implemented with paired local service slots behind an nginx upstream that the deployment
owns. Only the platform is replaced.**

### 1. Retained from ADR-035, unchanged

These clauses carry over verbatim in force. Re-read ADR-035 for their wording; this ADR does
not restate or relax them.

| Retained clause | Where it now lives |
|-----------------|--------------------|
| Every public deployment must satisfy the **release evidence contract** — build integrity, critical static-asset reachability, browser-rendered smoke coverage, tested rollback for every public surface including `demo.app-juli.com` | Unchanged; PRD #820 extends it to the landing site |
| The candidate receives **zero** public user traffic while it is proven | Candidate binds to loopback on an idle slot port; not merely restricted, unroutable from outside |
| Missing or failed evidence **discards the candidate**, stable keeps 100% of traffic, the release exits non-zero | Unchanged |
| A passing candidate triggers an **automatic atomic cutover**; stable stays available for immediate rollback | Atomic replacement of the owned upstream definition + graceful nginx reload |
| Candidate instances **do not run** background workers, schedulers, or production side-effect dispatch | Unchanged |
| **Release metadata must report actual results**, never claimed or defaulted success | Unchanged; still enforced by `check_release_metadata_honesty.py` |
| An automatic code rollback **cannot claim a schema downgrade** unless that downgrade is explicitly safe and executed | Strengthened: the additive-only migration gate (#834) makes downgrade unnecessary rather than optional |
| A public-surface change is **not shipped** until its external smoke checks pass | Unchanged |
| **Meta must halt** Executor assignment for any public-release change without a release-evidence plan naming affected surfaces, candidate journey, static-asset checks, migration compatibility, rollback assertion, and phase artifacts | Unchanged. **ADR-035 remains the ADR cited by `check_public_release_evidence_plan.py`, `check_release_evidence_plan_continuity.py`, and `check_public_release_classification.py`.** This ADR changes no gate, no schema, and no `required*` field |
| Percentage-based user-traffic canaries, request mirroring, CloudWatch RUM, Application Signals stay deferred | Unchanged |

### 2. Superseded for the pre-user phase

| Superseded clause (ADR-035) | Replacement |
|-----------------------------|-------------|
| "The pre-user release platform is AWS ECS on Fargate behind an Application Load Balancer: immutable ECR images … delivered from GitHub Actions using OIDC, ECS keeps stable and candidate task sets live concurrently, and CloudWatch verifies target health and scheduled synthetic checks." | The existing VPS. Two locally-bound service slots per deployable (one live, one idle), an nginx upstream definition owned by the deployment with its predecessor retained beside it, and a commit-addressed release directory in the single `~/releases` pool. Artifacts are built once in CI and shipped to the server; the server starts processes and never compiles. |
| "Public delivery requires independent stable and candidate deployment targets plus an isolated test route; **a single VPS with two local ports does not meet this boundary**." | **Reversed.** Two local ports do meet the boundary, because the boundary the contract requires is public-unreachability of the candidate, and loopback binding satisfies it more strictly than a restricted ALB listener does. Independent hardware buys availability, not isolation, and availability is not what this contract asserts. |
| "ECS/Fargate avoids Kubernetes control-plane and self-managed metrics costs while keeping an upgrade path to EKS if controller-reconciled GitOps becomes necessary." | Moot while the platform is deferred. The upgrade path is preserved by #498 remaining open, not by standing the platform up. |

### 3. Narrowed with the platform — recorded, not silently dropped

Three guarantees genuinely shrink. They are named here so the reduction is a decision rather
than an omission, and each is restored when the platform is re-entered.

- **Dedicated Synthetic shop and isolated credentials** — deferred. The residual protection is
  that candidate instances run no workers, no schedulers, and no side-effect dispatch, so a
  candidate cannot mutate a customer Shop. This is weaker than a separate account and is
  accepted only while there are no customer Shops of consequence.
- **In-network ephemeral verifier task** — replaced by a deliberate two-place split: on-server
  checks during a deploy are **protocol-level only** (readiness, rendered page bodies,
  exhaustive fetch of every referenced stylesheet and script with a non-trivial body assertion,
  core API paths), while **computed-styling and interactivity assertions run in CI against the
  build artifact before it ships**. Running a browser on a 2-vCPU box mid-release is not
  affordable. Neither half alone satisfies ADR-035's "browser-rendered smoke coverage"; the
  boundary between them must stay explicit and must not be quietly collapsed into one side.
- **Full auditable release metadata** narrows from image-digest immutability plus verifier exit
  codes to a **commit-addressed release record**. The honesty requirement survives intact; the
  digest-level immutability does not.

### 4. Reinstated from ADR-020, and what is not

ADR-035 superseded ADR-020 "in part" on three points. Two come back and one does not:

- **Single VPS / no new compute infra — reinstated.** No container platform, no load balancer,
  no image registry, no cloud IAM federation, no new recurring cost. AWS Secrets Manager
  (a *service*, not compute) remains as ADR-020 established it.
- **No staging environment — reaffirmed.** A candidate slot is not a staging environment: it
  exists for the duration of one release and is never a maintained destination. Local dev
  servers remain the preview mechanism.
- **Manual-only, `workflow_dispatch` rollback — NOT reinstated.** ADR-035's automatic rollback
  stands and is extended into two tiers: while the previous slot is still running, rollback is
  a traffic switch measured in seconds; after that slot is stopped to reclaim memory, rollback
  restarts it from its retained release before switching. ADR-020's manual path becomes the
  operator-invoked entry point to the same mechanism, not a separate one.
- **One release pool, one deployment lane — mandatory, not advisory.** ADR-020's `~/releases`
  pool is retained and hardened. Concurrent deploy lanes have already corrupted a live release
  by leaving it missing files; a single lane is the fix and is a hard constraint, not a default.

### 5. Re-entry trigger

Deferral without a trigger is drift. **Re-open [#498](https://github.com/thienphung00/Juli-AI/issues/498)
and reach a written decision within 14 days when any one of T1–T5 has been observed.** Each
trigger names the artifact in which it becomes visible, so that crossing it is noticed by
someone doing ordinary work rather than by someone remembering to look.

> **T1 — First non-founder revenue.** A payment for Juli is received from a seller who is not
> the founder. *Observed in:* the payment processor's transaction list, the moment the first
> charge settles.
>
> **T2 — A second person can deploy.** Anyone other than the founder is granted the ability to
> release to production — an SSH key on the server, or permission to run `release.yml` or
> `rollback.yml`. *Observed in:* the server's `authorized_keys`, and the actor column of the
> GitHub Actions release run history showing two distinct humans.
>
> **T3 — The 4 GB ceiling is reached.** Either a release aborts or is OOM-killed on memory, or
> the release record reports peak memory above 3.0 GB (75% of 4 GB) on three consecutive
> releases. *Observed in:* the release record emitted by every deploy, which carries peak
> memory for exactly this purpose.
>
> **T4 — Single-server unavailability reaches a user.** One unplanned outage of the whole
> public site lasting longer than 30 minutes occurs after T1 has fired. *Observed in:* the
> Slack alert raised by `uptime.yml`.
>
> **T5 — An external requirement a single unmanaged box cannot meet.** A signed customer
> contract, a TikTok platform requirement, or a compliance obligation names an uptime
> commitment, environment separation, or infrastructure-audit evidence. *Observed in:* the
> contract or requirement document itself.
>
> Growth in traffic, revenue, headcount, or ambition that does not cross T1–T5 is **not** a
> trigger. "It feels like time", "we're scaling", and "this feels fragile" are **not** triggers.
> Conversely, crossing any one of T1–T5 obliges a decision, not necessarily a migration: the
> outcome may be a new ADR that reaffirms the VPS with reasons, but it may not be silence.

T3 imposes a requirement on the delivery slices: **the release record must carry peak memory
observed during the deploy.** Without it T3 is unobservable and this deferral has four triggers,
not five. T4 imposes a second: **`uptime.yml` must cover the landing site once it is live**,
which PRD #820 already requires for its own reasons.

### 6. #498 is deferred and retitled, not closed

[#498](https://github.com/thienphung00/Juli-AI/issues/498) is retitled to name the later scale
phase and **remains open**, carrying T1–T5 in a comment. Its Implementation Decisions line
"ADR-035 is the architecture authority" is now read as: ADR-035 for the evidence contract,
this ADR for the pre-user platform, and #498's own contents for the platform to be built when
a trigger fires. Closing it would destroy the design work already done and make the deferral
indistinguishable from abandonment.

---

## Rationale

| Factor | Why this decision |
|--------|-------------------|
| Cost | ECS + ALB + ECR + a NAT gateway is a recurring monthly bill starting before the first seller. The VPS is already paid for. Pre-revenue, spend near zero is a product decision, not a finance one. |
| Speed | The cloud platform is weeks of infrastructure work producing nothing a visitor can see. The candidate-verify-then-switch path reuses a server, a web server, and deploy scripts that already exist, and delivers the safety property in its first increment. |
| The contract does not need the platform | Candidate isolation is a reachability property. Loopback binding satisfies it. ADR-035 conflated the property with one mechanism for achieving it, and that conflation is the specific error corrected here. |
| The real defect is ordering | Verify-then-switch retires "broken code stays live" on any platform. Fixing it on the existing box is the smaller change and is available now. |
| Honesty about what is lost | High availability is not delivered. Saying so, and attaching an observable trigger, is worth more than a platform that would have delivered it in three months' time to zero users. |
| Comprehensibility | One readable shell script on a box the founder already administers can be changed by the one person who maintains it. An ECS/ALB/OIDC/CloudWatch estate cannot, by the same person, at the same speed. |
| Reversibility | Nothing here forecloses ECS. #498 keeps its design; artifacts are already built in CI, which is the same prerequisite the container path needs. Re-entry is resumption, not a restart. |

---

## Consequences

- **Positive:** the landing site gets a production home and the Demo joins an automated path,
  ending the manual-deploy drift where "merged" and "live" mean different things — without
  waiting on a cloud build-out.
- **Positive:** the release-safety property (a broken candidate is never public) lands in the
  first increment, ahead of the zero-downtime property, because they are separable.
- **Positive:** no new recurring infrastructure cost. Spend stays near zero until revenue.
- **Negative — the accepted trade:** the server remains a single point of failure. Zero-downtime
  *deploys* are delivered; high availability is not. This is precisely what the deferred
  platform would have bought, and T4 is the trigger that prices it.
- **Negative:** memory at 4 GB is the binding constraint. Moving builds into CI is what makes a
  transient duplicate instance affordable; if builds ever return to the server, this design is
  unsafe and T3 will fire.
- **Negative:** the dedicated Synthetic shop is deferred, so candidate isolation from customer
  data rests on candidates running no workers, schedulers, or side-effect dispatch. That
  invariant is now load-bearing and must be asserted by test, not assumed.
- **Binding on delivery slices:** the release record must carry peak deploy memory (T3), and
  `uptime.yml` must cover the landing site once live (T4). A trigger with no artifact behind it
  is not a trigger.
- **Binding on verification:** the protocol-level / browser-level split is a decision, not an
  oversight. Removing either half silently reduces ADR-035's coverage; changing the boundary
  requires a new ADR.
- **Unchanged for the harness:** no gate, schema, validator, or `required*` field is modified by
  this ADR. `check_public_release_evidence_plan.py`,
  `check_release_evidence_plan_continuity.py`, and `check_public_release_classification.py`
  continue to cite ADR-035, and every public-surface issue still needs a release-evidence plan.
- **Risk carried into implementation:** slot-symlinked working directories are unproven on the
  server. Each slot resolves to a release through its own indirection and the apps start from
  inside it using the workspace package manager, whose dependency tree is itself symlinked.
  This would invalidate the paired-slot design rather than merely complicate it, and is why
  [#835](https://github.com/thienphung00/Juli-AI/issues/835) is a spike that runs before the
  slot layout is committed to.
- **Documentation debt, deliberately left:** `CONTEXT.md` and `docs/architecture/MODULES.md`
  still describe ADR-035 / #498 ECS as the public release platform under §12.1. Those
  statements are now scoped to the post-trigger phase. They are not edited here to avoid
  colliding with concurrent work in sibling worktrees; correcting them is a follow-up.

---

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Build ECS/Fargate now, as ADR-035 and #498 specify | Weeks of infrastructure work and a recurring bill, both before the first user, to fix an ordering defect that does not require a new platform. Optimises for a scale that does not exist at the direct expense of the two things that do matter now: cost and iteration speed. |
| Close #498 and drop the cloud path entirely | Discards real design work and converts a deferral into an amnesia. The availability gap is genuine; it needs a review point, not a deletion. |
| Defer with a soft trigger ("revisit when we grow") | Unfalsifiable. Nobody can point at growth and say it happened, so the review never occurs and the deferral silently becomes permanent. This is the failure mode T1–T5 exist to prevent. |
| Third-party managed frontend hosting (Vercel/Netlify) for the landing and Demo | Recurring cost, and it splits delivery across two mechanisms with two rollback stories. The API still needs the VPS path, so nothing is eliminated. |
| Keep the current deploy path and only add rollback | Adding rollback to a mutate-then-verify sequence still exposes visitors for the duration of the check. The defect is the order, and rollback does not reorder anything. |
| A second VPS as a staging environment | Recurring cost and a permanently maintained environment, to approximate what a candidate slot supplies for the length of one release. Reaffirms ADR-020's "no staging" for the same reasons. |
| Superseding ADR-035 wholesale and writing one new contract | Would restate — and inevitably drift from — a contract that is correct and is already wired into three CI validators and the Meta halt gate. The platform is the only wrong part; superseding only the platform keeps those gates citing a document that is still true. |

---

## ADR number allocation

Numbering has diverged across branches, so 057 was allocated only after checking that it is
unused everywhere, on **2026-08-07**:

- **All 30 remote heads on `origin`** were enumerated with `git ls-remote --heads origin` and
  each branch's `docs/adr/` listed with `git ls-tree`. Highest number present on any remote
  branch: **056** (`056-brand-asset-package.md`, on `main` and 15 others).
- **All 75 local branches** (`git for-each-ref refs/heads/`) — highest present: **056**.
- **All 68 active worktrees**, including the sibling PRD #820 slices `issue-833`, `issue-834`,
  `issue-835`, `issue-836` and `phase0-prd` — no uncommitted ADR above 056 in any of them.
- **055 is taken but not yet on `main`:** `055-decision-plan-review.md` exists on
  `feature/dpr-demo-wave` and `claude/repo-code-editing-verify-qvcgri`. It must not be reused.
- **044 and 045 are not free for reuse.** Neither has ever existed as a file in any branch's
  history (`git log --all --diff-filter=A -- 'docs/adr/044*' 'docs/adr/045*'` returns nothing),
  but **044 is semantically claimed**: `backend/src/juli_backend/services/gold_kpi_envelope_contract.py`,
  `gold_kpi_envelope_serving.py`, `tests/unit/test_gold_kpi_envelopes.py`, and
  `agent-runtime/config/slice-routing.yml` all cite "ADR-044" for the Demo Main KPI override,
  which actually landed as [ADR-049](049-demo-analytics-main-kpi-override.md);
  `agent-runtime.config.yml` records the mismatch explicitly as
  `ADR-049 (PRD calls it 'ADR-044')`. Reusing 044 would collide with live code comments. 045
  carries no such claim but sits in the same unexplained gap; both gaps are left open rather
  than re-litigated.

**Allocated: 057.** Anyone allocating 058 or later should repeat this check rather than reading
only `main`.

---

## References

- [ADR-035](035-public-release-evidence-and-automatic-rollback.md) — release evidence contract
  (retained) and the ECS platform (superseded here for the pre-user phase)
- [ADR-020](020-vps-ssh-continuous-delivery-and-secrets-manager.md) — VPS/SSH delivery,
  `~/releases` pool, AWS Secrets Manager (single-VPS constraint reinstated)
- [ADR-027](027-database-migration-safety-pipeline.md) — migration safety pipeline
- [#820](https://github.com/thienphung00/Juli-AI/issues/820) — PRD: pre-user zero-downtime
  delivery on the existing server; `docs/product/phases/phase-0-delivery/PRD.md`
- [#498](https://github.com/thienphung00/Juli-AI/issues/498) — the cloud platform PRD, deferred
  to the post-trigger scale phase and **open**
- [#832](https://github.com/thienphung00/Juli-AI/issues/832) — the slice that produced this ADR
- `agent-runtime/scripts/validate/check_public_release_evidence_plan.py`,
  `check_release_evidence_plan_continuity.py`, `check_public_release_classification.py`,
  `check_release_metadata_honesty.py` — unchanged; still cite ADR-035
