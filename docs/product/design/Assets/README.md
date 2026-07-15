# Assets

Brand elements (logo, icon) are supplied by the designer and imported by the
developer — no markdown docs belong in this folder, only image files.

## Status

`logo.png` (Juli wordmark) and `icon.png` (Juli bird icon) are **not yet
available**. A search of the linked codebase (`/Users/macos/Juli-AI-v2`) found no
logo/icon asset files — only unrelated favicons in third-party package output
(`node_modules`, coverage reports). Per this design system's own governance rule
("never invent tokens outside these files"), no placeholder logo has been
generated here.

## When the real files arrive

Drop them in as:

- `logo.png` — Juli wordmark
- `icon.png` — Juli bird icon

Then update:
- `../design.md` if the real mark introduces any color not already in the
  palette (it shouldn't — the wordmark uses `--brand-gradient`, per
  `.brand-wordmark` in the codebase).
- `Screens/*.md` and `Components/navigation.md` wherever a header/wordmark
  placement is described, to reference the real file paths.
