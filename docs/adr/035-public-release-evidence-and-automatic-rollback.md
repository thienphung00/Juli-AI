# ADR 035: Public release evidence and automatic rollback

**Status:** Accepted  
**Date:** 2026-07-24  
**Deciders:** grill-with-docs (Architect)
**Supersedes (in part):** ADR-020's single-VPS/no-new-compute, manual-rollback, and
no-staging constraints for public delivery

## Context

The Demo deployment exposed that a reachable HTML document and a successful deployment
command do not prove a usable public application: static CSS or JavaScript can fail while
localhost health checks and HTTP status probes remain green. The release path also leaves
a failed cutover live for manual recovery, and public Demo deployment and uptime coverage
are not part of the same automated release evidence as the other public surfaces.

Options: (1) retain command/localhost checks and use manual recovery; (2) introduce
warning-only public smoke checks; (3) run an isolated candidate target with no public
traffic, prove it through synthetic verification, then atomically promote or discard it.

## Decision

Every public Juli deployment must satisfy a **Release evidence contract** before it is
recorded as successful. The contract requires build integrity, critical static-asset
reachability, browser-rendered smoke coverage, and a tested rollback path for every
public surface, including `demo.app-juli.com`.

The pre-user release platform is AWS ECS on Fargate behind an Application Load Balancer:
immutable ECR images are delivered from GitHub Actions using OIDC, ECS keeps stable and
candidate task sets live concurrently, and CloudWatch verifies target health and scheduled
synthetic checks. This is Git-controlled delivery with an auditable desired state, not
controller-reconciled GitOps; EKS and a GitOps controller are explicitly deferred.

While user traffic is low, the candidate is reachable only through a restricted test
listener or hostname and receives **zero** public user traffic. Synthetic browser journeys,
API checks, static-asset probes, readiness, and migration-compatibility checks form the
promotion gate. Those journeys use a dedicated Synthetic shop and credentials. Candidate
task sets do not run background workers, schedulers, or production side-effect dispatch.
Missing or failed evidence discards the candidate and leaves stable serving 100% of public
traffic; the release exits non-zero. A passing candidate automatically triggers an atomic
full cutover, while stable remains available for immediate rollback. Release metadata must
report actual check and promotion results rather than claimed or defaulted success.

## Consequences

- Deployment automation gains a strict external verification and rollback responsibility;
  manual “looks good” confirmation or promotion is not sufficient.
- Public delivery requires independent stable and candidate deployment targets plus an
  isolated test route; a single VPS with two local ports does not meet this boundary.
- ECS/Fargate avoids Kubernetes control-plane and self-managed metrics costs while keeping
  an upgrade path to EKS if controller-reconciled GitOps becomes necessary.
- Percentage-based user-traffic canaries, CloudWatch RUM, and Application Signals are
  deferred until traffic volume makes comparative metrics reliable.
- Candidate verification uses a dedicated Synthetic shop and disables background/side-effect
  processing, so it cannot act on or mutate a customer Shop.
- A public-surface change cannot be considered shipped until its relevant external smoke
  checks pass.
- Meta Agent must halt Executor assignment for any public-release change without a
  release-evidence plan that names the affected surfaces, candidate journey, static-asset
  checks, migration compatibility, rollback assertion, and phase artifacts.
- Rollback safety must account for migrations: an automatic code rollback cannot claim a
  schema downgrade unless that downgrade is explicitly safe and executed.
- The Meta Agent must treat failed release evidence as an execution failure and use its
  artifacts to propose measurable routing, test, or release-gate improvements rather than
  closing the task.
