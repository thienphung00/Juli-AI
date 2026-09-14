/**
 * dictionary.md `demo.mode.replay` (issue #1907) — the single source for
 * DemoShell's header mode-switcher label, replacing the developer-facing
 * "Mock" that used to sit in front of sellers.
 *
 * The e2e exit-gate specs import this same constant, so a spec can never
 * drift from what the component actually renders; the unit suite
 * (demo-shell.test.tsx) pins the literal Vietnamese instead, so neither
 * the component nor the specs can drift from dictionary.md.
 */
export const DEMO_MODE_REPLAY_LABEL = "Bản minh họa";
