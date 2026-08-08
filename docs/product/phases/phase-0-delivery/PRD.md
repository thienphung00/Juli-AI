# PRD: Phase 0 — Pre-user zero-downtime delivery on the existing server

> **Canonical docs:** [`EXECUTION.md`](../../../../EXECUTION.md) ·
> [ADR-035](../../../adr/035-public-release-evidence-and-automatic-rollback.md) (evidence + rollback,
> extended here rather than replaced) ·
> [ADR-027](../../../adr/027-database-migration-safety-pipeline.md) (migration safety) ·
> [`CONTEXT.md`](../../../../CONTEXT.md).
>
> **Parent issue:** [#820](https://github.com/thienphung00/Juli-AI/issues/820) — filed via `to-prd`.
> Child slices #832–#844 filed via `to-issues`; slice IDs are registered under
> `epicRegistry.820.childSlices` in
> [`agent-runtime/config/agent-runtime.config.yml`](../../../../agent-runtime/config/agent-runtime.config.yml).
>
> **Supersedes for the pre-user phase only:** the cloud-platform delivery approach in
> [#498](https://github.com/thienphung00/Juli-AI/issues/498). That PRD is retitled to the later
> scale phase rather than closed, and #832 records the superseding decision plus its re-entry
> trigger.

## Assumptions

- The grill handoff captured on #820 is authoritative; no re-interview.
- Delivery stays on the existing single VPS (2 vCPU, 4 GB RAM, 80 GB disk). No container
  platform, load balancer, image registry, cloud IAM federation, or new recurring cost.
- Builds move into CI; the server's role narrows to starting processes. This is what makes a
  transient duplicate instance affordable inside the 4 GB ceiling.
- Slot-based release indirection is **unproven** until #835 reports from the server. It is the
  one open risk that would invalidate the paired-slot design rather than merely complicate it;
  #836 fixes the packaging decision on that evidence.
- The existing per-application deploy scripts (`infra/scripts/deploy-release.sh`,
  `deploy-demo-release.sh`) keep working until the combined path in #844 has completed a real
  release, and only then are removed.

## Slices

| Slice | Issue | Type | Blocked by |
|-------|-------|------|------------|
| P0-DEL-ADR | [#832](https://github.com/thienphung00/Juli-AI/issues/832) supersede cloud ADR | AFK | — |
| P0-DEL-VERIFY | [#833](https://github.com/thienphung00/Juli-AI/issues/833) asset-level verification harness | AFK | — |
| P0-DEL-MIGGATE | [#834](https://github.com/thienphung00/Juli-AI/issues/834) additive-only migration gate | AFK | — |
| P0-DEL-SPIKE | [#835](https://github.com/thienphung00/Juli-AI/issues/835) slot indirection spike | HITL | — |
| P0-DEL-PKG | [#836](https://github.com/thienphung00/Juli-AI/issues/836) packaging shape decision | AFK | #835 |
| P0-DEL-ARTIFACT | [#837](https://github.com/thienphung00/Juli-AI/issues/837) build artifacts in CI | AFK | #836 |
| P0-DEL-CANDIDATE | [#838](https://github.com/thienphung00/Juli-AI/issues/838) candidate verify-and-discard (Demo) | HITL | #833, #834, #837 |
| P0-DEL-SWITCH | [#839](https://github.com/thienphung00/Juli-AI/issues/839) graceful switch via owned upstream | HITL | #838 |
| P0-DEL-ROLLBACK | [#840](https://github.com/thienphung00/Juli-AI/issues/840) post-cutover check + auto rollback | HITL | #839 |
| P0-DEL-LANDING | [#841](https://github.com/thienphung00/Juli-AI/issues/841) Landing production home | HITL | #837 |
| P0-DEL-CUTOVER | [#842](https://github.com/thienphung00/Juli-AI/issues/842) repoint main domain, retire Dashboard | HITL | #840, #841 |
| P0-DEL-SLOTS | [#843](https://github.com/thienphung00/Juli-AI/issues/843) paired slots for API + Landing | HITL | #840, #841 |
| P0-DEL-COMBINE | [#844](https://github.com/thienphung00/Juli-AI/issues/844) single change-detected deploy | HITL | #834, #843 |

## Problem Statement

Shipping the product to a first user is currently blocked by the delivery path, not by the product.

The landing page is nearly complete but has no way to reach production at all. The Demo — the core surface that needs the most iteration — reaches production only when a person remembers to run a script by hand, so "merged" and "live" routinely mean different things. Every deployment restarts services in place, so visitors see errors during each release. When a release turns out to be broken, the broken version stays serving users until a human notices and intervenes; a failed health check does not undo anything.

The previously chosen remedy is a cloud container platform with a load balancer, image registry, federated CI credentials, and in-network verification tasks. That approach solves the reliability problem but requires weeks of infrastructure work producing no user-facing value, and it adds recurring monthly cost before there is a single user. It optimises for scale at the direct expense of the two things that matter right now: speed of iteration and cost.

## Solution

Deliver the same release-safety guarantees on the server that already exists, using a single deployment command.

Every release builds once in CI, then runs on the server as a *candidate* alongside the currently live *stable* version. The candidate is reachable only from the server itself, never by visitors. It must prove itself — pages render, every stylesheet and script they reference actually loads, core API paths respond, and the service reports ready — before any traffic moves. Only then does traffic switch atomically and gracefully, so no visitor request is dropped. If the candidate fails any check, it is discarded and stable keeps serving; visitors never saw it. If a problem appears immediately after the switch, traffic returns to the retained previous version automatically.

One command deploys everything, but only what actually changed is rebuilt and restarted, so a landing-page copy edit never disturbs the API or the Demo. The landing page gains a production home for the first time, and the Demo joins the same automated path, ending the manual-deploy drift.

## User Stories

1. As a founder, I want the landing page to have a production home, so that my most finished asset can actually reach visitors.
2. As a founder, I want the Demo to deploy automatically when work merges, so that "merged" and "live" always mean the same thing.
3. As a visitor, I want the site to stay available during releases, so that I never encounter an error page because someone shipped.
4. As a visitor, I want to never be served a broken release, so that my first impression of the product is not a failure.
5. As an operator, I want one command to deploy the whole system, so that I do not maintain a separate procedure per application.
6. As an operator, I want only changed applications rebuilt and restarted, so that unrelated services are never disturbed by an unrelated change.
7. As a developer, I want the landing page to ship without waiting on the Demo, so that independent work releases independently.
8. As an operator, I want the API to deploy before the Demo when both change, so that the frontend never calls a backend that lacks its capabilities.
9. As an operator, I want each release built once in CI rather than on the server, so that a memory-constrained box is never asked to compile while serving traffic.
10. As an operator, I want the deployed artifact to correspond to an exact commit, so that what is running is always traceable.
11. As an operator, I want a candidate version started alongside the live one, so that a new release can be proven before it is exposed.
12. As an operator, I want the candidate reachable only from the server, so that no visitor can reach an unverified version.
13. As an operator, I want verification to fetch every stylesheet and script referenced by each page, so that a reachable page with broken assets is caught before cutover.
14. As an operator, I want verification to assert rendered content and interactivity, so that a successful status code alone cannot mask a broken application.
15. As an operator, I want verification to exercise core API paths, so that a healthy process with a broken route is caught.
16. As an operator, I want a failed candidate discarded with stable untouched, so that a bad release has zero visitor impact.
17. As an operator, I want the traffic switch to be graceful, so that in-flight requests complete rather than being dropped.
18. As an operator, I want an automatic check immediately after cutover, so that problems only visible from outside are detected at once.
19. As an operator, I want automatic return to the previous version when the post-cutover check fails, so that recovery does not wait for a human.
20. As an operator, I want the previous version retained for a bounded window, so that rollback is a traffic switch rather than a rebuild.
21. As an operator, I want rollback to be a single command, so that recovery under pressure is not error-prone.
22. As an operator, I want database changes to be additive only while two versions coexist, so that rolling back never leaves code and schema mismatched.
23. As an operator, I want destructive or data-moving changes barred from automatic release, so that a routine deploy cannot cause data loss.
24. As an operator, I want migrations applied before any candidate starts, so that ordering is deterministic.
25. As an operator, I want one release pool and one deployment lane, so that concurrent deploys cannot corrupt the live version's files.
26. As an operator, I want each deploy to record what ran and what its checks returned, so that I can tell afterwards what actually happened.
27. As an operator, I want the deployment to fail loudly and visibly, so that a silent partial success is impossible.
28. As an operator, I want old releases pruned on a retention policy, so that disk does not fill silently.
29. As a developer, I want to keep using local dev servers to preview changes, so that no additional preview environment needs maintaining.
30. As a developer, I want the internal dashboard to remain a development-only surface, so that no production hosting, domain, or certificate work is needed for it.
31. As an operator, I want seller sign-in to be unaffected by the public site reorganisation, so that changing what the main domain serves carries no authentication risk.
32. As an operator, I want the deployment to run within the existing server's memory, so that a release never exhausts resources and takes the site down.
33. As a founder, I want no new recurring infrastructure cost, so that spend stays near zero until there is revenue.
34. As a maintainer, I want the whole mechanism to be one readable script, so that it can be understood and changed without cloud expertise.
35. As a maintainer, I want the deferred cloud platform to have an explicit re-entry trigger, so that deferring is a decision with a review point rather than drift.

## Implementation Decisions

**Modules, by responsibility**

- **Release materializer** — turns a commit and its CI-built artifacts into an immutable on-disk release. Owns a single release pool, its layout, and retention/pruning. Interface: given a commit reference, produce a ready release location or fail.
- **Change detector** — compares the candidate commit against the live commit and determines which deployables changed. Emits the set of lanes to run and their required ordering. Interface: given two commit references, return the affected deployables in dependency order.
- **Candidate lifecycle manager** — starts and stops candidate instances on inactive, locally-bound ports. Owns slot allocation and guarantees it never touches the live instance. Interface: start candidate for a deployable, stop candidate, report candidate state.
- **Verification harness** — runs the evidence checks against a candidate and returns structured pass/fail with the reason. Covers readiness, rendered pages, exhaustive referenced-asset fetching, and core API paths. Interface: given a deployable and a local address, return an evidence result.
- **Traffic switch** — the only component that changes what the public sees. Repoints the web server's upstream targets and reloads gracefully. Explicitly reversible. Interface: switch a deployable to a target instance; report the prior target.
- **Rollback controller** — restores prior upstreams and instances. Invoked automatically on post-cutover failure and manually on demand. Interface: roll back one deployable or the whole release.
- **Migration gate** — validates that pending schema changes are additive-only, refuses anything destructive, and applies them before candidates start.
- **Release record** — records the commit, the lanes run, each check's actual result, the cutover outcome, and any rollback.

**Architecture and platform**

- Delivery stays on the existing single server (2 vCPU, 4 GB RAM, 80 GB disk). No container platform, no load balancer, no image registry, no cloud IAM federation, no additional recurring cost.
- The stable/candidate model is implemented with paired service slots per deployable and a graceful web-server reload for the switch. This preserves the previously accepted release-evidence contract while replacing its platform.
- Three production deployables: the landing site, the Demo site, and the API. The internal dashboard becomes development-only and is retired from production; it continues to be built and tested in CI but is never deployed.
- The main domain is repointed to the landing site. No new subdomain, DNS record, or TLS certificate is required, and the existing web-server provisioning list is unchanged in shape.
- The landing site has no backend dependency of any kind and therefore deploys entirely independently.
- The Demo depends on the API; when both change, the API is released first so the frontend never calls a backend missing its capabilities.
- Builds move off the server into CI. The server receives prepared artifacts and only starts processes. This removes compilation memory pressure from a 4 GB box and shortens deploys.
- A single release pool and a single deployment lane are mandatory, directly addressing prior corruption where concurrent lanes left the live release missing files.
- Sign-in is unaffected: OAuth callbacks are backend routes on the API domain and never referenced the main domain. Verified in the codebase at two independent call sites.

**Cutover and rollback design**

The defect being retired is one of *ordering*, not of a missing rollback. Today the sequence mutates first and verifies second, so by the time a check fails the broken version is already public. Adding rollback to that shape still exposes users for the duration of the check. The design therefore inverts the order: prove the candidate, then switch. Failure before the switch needs no rollback at all, because nothing the public can see has changed.

- **Traffic indirection.** Each service's public target is resolved through a dedicated upstream definition that the deployment owns, with the immediately previous definition retained beside it. Cutover is an atomic replacement of that definition followed by a graceful reload; rollback is restoring the retained copy and reloading. The live definition is the single source of truth for what is serving, and its retained predecessor is the undo. Site configuration is otherwise unchanged.
- **Configuration validation before reload.** The web server's configuration is validated before every reload. An invalid configuration is rejected and the previously loaded configuration continues serving, so a malformed switch cannot take the site down.
- **Paired slots.** Every deployable has two instance slots on distinct locally-bound ports, one live and one idle. Deploying repoints the idle slot at the new release and starts it; the live slot is never touched until traffic has moved. Slot assignments are fixed and known in advance so the deployment never has to discover state.
- **Ordering.** Migrations run before any candidate starts. Candidate verification runs before any traffic moves. The external check runs after traffic moves. Each stage is a hard gate on the next.
- **Migrations are never automatically reverted.** Additive-only schema changes are exactly what makes rollback safe: additive changes remain compatible with the previous code, so reverting code requires no schema undo. Safety comes from additivity, which is why the migration gate is a hard block rather than a warning.
- **Lanes run sequentially, not concurrently.** On a two-core, 4 GB server a transient duplicate instance is acceptable for one service at a time; several at once is an avoidable memory spike. Change detection makes a single lane the common case.
- **Two rollback tiers.** While the previous slot is still running, rollback is a traffic switch measured in seconds. After the previous slot has been stopped to reclaim memory, rollback restarts it from its retained release before switching. Release contents are retained for several versions so the second tier stays available; the previous slot stays running through a grace period after cutover so the first tier covers the window when regressions actually surface.

**Delivery increments**

The safety property and the downtime property are separable and should not be bundled into one change. The first increment applies candidate verification and discard to a single high-churn deployable, which by itself retires the risk of broken code remaining live. The second extends slots to the remaining deployables and adds the post-cutover check and traffic-switch rollback. Sequencing this way puts the safety payoff first.

**Assumptions and open decisions**

- Whether applications are packaged as self-contained build output or as build output plus a production dependency install is left open. Self-contained output is preferred for artifact size and start time; the current configuration deliberately avoids it, and that rationale must be confirmed before the packaging decision is fixed.
- The previously accepted cloud-platform architecture decision is superseded **for the pre-user phase only**, by a new decision record that names an explicit re-entry trigger. The existing cloud PRD is retitled to that later phase rather than closed.
- Architecture decision record numbering must be checked across active branches before allocation, since numbering has diverged between branches.
- The environment override for the OAuth callback address, and its registration in the external developer console, must both be confirmed against the API domain at cutover.

## Testing Decisions

Tests assert externally observable behaviour — what a visitor or operator can see — not internal implementation.

- **Asset-level verification is the highest-value test.** For every page under test, fetch every stylesheet and script the document references and assert each returns success **and returns a non-trivial body** — an empty or error-page response in place of a stylesheet must fail. This targets the known failure mode directly: a release missing built asset files, where the page loads and the styling does not.
- **Verification is split by cost, deliberately.** On-server checks during a deploy are protocol-level, because running a full browser on a two-core box mid-release is too expensive. The computed-styling and interactivity assertions run in continuous integration against the build artifact, before it ever ships. This split is a decision, not an oversight: on-server checks prove assets are served, integration checks prove they render. Neither alone is sufficient and the boundary must stay explicit.
- **Configuration-validation failure.** Assert that an invalid web-server configuration is rejected without interrupting the currently serving configuration.
- **Change detection correctness.** Assert that a landing-only change neither rebuilds nor restarts the API or Demo, that an API change orders before a dependent Demo change, and that a no-op change deploys nothing.
- **Candidate isolation.** Assert a candidate is not reachable from outside the server, and that starting or failing a candidate never affects the live instance.
- **Every failure path**, each asserting that stable continues serving and the release exits non-zero: candidate fails readiness, candidate serves a page with a missing asset, candidate fails an API path, migration gate rejects a destructive change, and the post-cutover check fails.
- **Rollback.** Assert automatic return to the previous version on post-cutover failure, and that manual rollback restores the prior version without a rebuild.
- **Graceful switch.** Assert that requests in flight during a cutover complete rather than erroring, and that no request observes an unavailable upstream.
- **Migration safety.** Assert additive-only changes pass, destructive ones are refused, and that the retained previous version remains compatible with the migrated schema.
- **Resource ceiling.** Assert a full deploy, including the transient duplicated instance, completes within the server's memory budget.
- **Release record truthfulness.** Assert the record reports actual check outcomes, and that a defaulted or assumed success cannot be recorded.

Prior art: the repository already has an evidence-and-rollback decision record, health-check and rollback scripts, a migration-safety allowlist, and a UI-only review build. Verification should extend these rather than introduce a parallel mechanism.

## Out of Scope

- Container orchestration, managed load balancers, image registries, cloud IAM federation, network address translation, cloud log/alarm services, and in-network verifier tasks. These are deferred to the later scale phase with an explicit re-entry trigger.
- Third-party managed frontend hosting. Explicitly rejected on recurring cost.
- A hosted preview or review environment. Local development servers are sufficient; no preview infrastructure will be maintained.
- Production deployment of the internal dashboard, and any domain, DNS, or certificate work for it.
- High availability, multi-node redundancy, and multi-region failover. A single server remains a single point of failure by deliberate choice.
- Percentage-based traffic canaries and request mirroring.
- A dedicated synthetic test account with isolated credentials, and the full auditable release-metadata contract, both deferred with the cloud platform.
- Any customer-facing product or feature work.

## Further Notes

**Risks**

- The server remains a single point of failure. Zero-downtime *deploys* are delivered; high availability is not. This is an accepted pre-user trade, and it is the principal thing the deferred cloud platform would buy.
- Memory is the binding constraint at 4 GB. Moving builds into CI is what makes the paired-slot approach safe; if builds were to remain on the server, a release could exhaust memory while serving traffic.
- Two versions briefly share one database, which is why additive-only schema changes are mandatory rather than advisory.
- Retiring the dashboard from production must not remove its CI type-checking and test coverage.
- **Slot-symlinked working directories are the design's one friction point.** Each slot resolves to a release through its own indirection, and the applications start from within that directory using the workspace package manager, whose dependency tree is itself symlinked. This is the same underlying constraint that led both applications to reject self-contained build output. It must be proven on the server before the slot layout is committed to, since it would invalidate the approach rather than merely complicate it.

**Rollout**

Land the delivery path before the domain change, so the landing site is provably deployable before it becomes what the main domain serves. Retire the dashboard from production in the same change that repoints the domain. Keep the existing per-application deploy scripts until the combined path has completed a real release, then remove them so only one path exists.

**Observability**

Deployment outcome and the retained rollback target should be visible without reading logs. Existing uptime monitoring should cover the landing site once it is live.

**Follow-ups**

- Establish the additive-only schema convention as an enforced check; it is currently required by policy but implemented nowhere.
- Revisit the deferred cloud platform when the named trigger is reached.
- Decompose this PRD into infrastructure, delivery, verification, and migration-safety issues before implementation.

