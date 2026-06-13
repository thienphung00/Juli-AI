# Handoff: review → ship — Issue #217 (reopen)

## Issue

- **#217** — Home Real/Estimated visualizations + decision linking (P1.8-10 reopen)
- Parent: **#215**

## PR

- Branch: `fix/issue-217-home-viz-decision-linking` → `main`

## Root Cause

Original #217 shipped sparkline Reward tiles with text CTAs and 5 Daily Report tabs. Product review (#215 follow-up) required Real/Estimated two-tone bars, click-on-Estimated navigation, 3-tab consolidation, and Shop Health bar upgrade — scope superseded the closed implementation.

## Review Status

- Critical findings: 0
- Warnings: 0
- All 505 tests passing

## Rollback

Revert PR merge; Home returns to sparkline + 5-tab layout from prior #217.
