# Design System Source Context

> **Non-authoritative historical intake evidence.** This generated setup record
> documents the inputs available when the package was created. It cannot override
> the root design authorities, product structures, or reusable specifications.
> Any dashboard-first, retired workflow, or old-path language below is historical
> context, not current product direction.

Use this file for provenance only. Current previews and UI-kit examples must
follow the authority hierarchy and implementation paths under `apps/dashboard`.

## Company / Product

Canonical design-system title: Juli is an app Design System

Juli is an app that aims to feel intentional (minimal cognitive load, color usage and all designs must serve a purpose in improving user experience), trusted (shows progress, thoughts, listen - allow users to override recommendations with their inputs) , has a personality (hence the name Juli and the bird logo - AI assistant). It transforms shop data into clear opportunities, risks, and ranked recommendations—showing expected business impact, confidence, and reasoning before any action is taken.

## GitHub Repositories

- None linked.

Connector status: GitHub connector is not configured; repository intake will use local git credentials or authenticated GitHub CLI when possible.

## Local Code

Linked folders readable by the local agent:
- /Users/macos/Juli-AI-v2

### Local Folder Intake Runbook

Local folder intake is required before drafting from linked local code folders:
1. For each linked folder, run the bounded local intake command before writing design-system files:
   - `"$OD_NODE_BIN" "$OD_BIN" tools connectors local-design-context --path '/Users/macos/Juli-AI-v2' --output context/local-code/Juli-AI-v2.md`
2. The command selects design-system-relevant source files plus available logos/icons/fonts, writes a reviewable evidence note, and copies snapshots under `context/local-code/`.
3. Inspect the generated evidence note plus snapshots for README, package manifests, Tailwind/theme/token files, global CSS, font declarations, component source, layout shells, icons/logos/assets, and representative app entry files.
4. If the command cannot read a linked folder or write snapshots, stop and explain the local file access problem instead of inventing tokens from the folder name.

Copied browser-selected code snapshot files under `context/local-code/`: none.

## Design And Brand Resources

Figma files selected: none.

Locally parsed Figma summaries under `context/figma/`: none.
Fonts, logos, and assets selected: none.

Uploaded brand asset files under `assets/`: none.

## Notes

Brand feel: trusted, modern, has a personality, interactive.
Visual style: clean white canvas, Inter typography, rounded cards, subtle shadows, restrained pink accent (#F86BA5).
Prioritize clarity, trust, explainability, and measurable impact.
Avoid generic analytics-dashboard styling, technical jargon, autonomous-action messaging, and cliché purple AI gradients.

## Review Contract

- `/design-systems/create` only collected setup inputs. All GitHub extraction, local evidence intake, source reading, design-system construction, package audit, and artifact writes should happen inside this project workspace.
- The root design authorities are canonical; this intake record is not.
- Use the canonical design-system title above for package labels unless a root
  authority defines a newer title.
- colors_and_type.css should hold concrete reusable tokens when the source evidence supports them; if fonts/ contains preserved font files, colors_and_type.css must bind those files with @font-face, @import, or url(...) references so typography does not fall back to substitute fonts.
- README.md and SKILL.md should make the extracted system reusable as a real Open Design design-system package.
- README.md should include a source-backed Product Overview/Product Context section, source repository or source folder references, package contents, a concrete `## Preview Manifest` listing every generated `preview/*.html` card, and reuse workflow, similar to Claude Design exports.
- SKILL.md should include YAML frontmatter with `name`, `description`, and `user-invocable`, plus Claude-style reusable skill sections: What is inside, Source context, When to use this skill, How to use, and Design system highlights. Historical guidance pointed at an uppercase design file; current consumers must follow the root authority hierarchy, `colors_and_type.css`, `preview/`, `source_examples/`, and `ui_kits/app/`.
- README.md, the root authorities, and ui_kits/app/README.md must describe the final focused preview cards and `ui_kits/app/` paths, not old scaffold names such as `preview/typography-scale.html` or `ui_kits/generated_interface/`.
- preview/ should contain small reviewable HTML cards for typography, color themes, spacing, radius, shadows, brand assets, and component evidence.
- source_examples/ or equivalent root/nested source files should preserve selected high-signal original components when snapshots include substantial app/component source, similar to Claude Design exports that keep files like SelectModelButton.tsx or ChatNavBar/index.tsx alongside the package. These examples should contain substantive original implementation code, not tiny stubs that only share the component name.
- ui_kits/app/ should contain an applied interface example, plus substantive role-based files under `ui_kits/app/components/` when the source snapshots include representative app shells, navigation, chat/input surfaces, or reusable components. `ui_kits/app/README.md` should explain structure, component files, usage, design notes, and source basis. `ui_kits/app/index.html` must load `../../colors_and_type.css`, must load/import/compose the modular component files, and must mount/render the composed interface instead of staying as a standalone generic static mock or disconnected script list. If the entry directly loads `.jsx`/`.tsx` files, include React, ReactDOM, and Babel standalone scripts and expose each loaded component as `window.ComponentName` / `globalThis.ComponentName`, or write compiled browser-ready JavaScript instead. For chat/workspace evidence, cover app shell, sidebar/navigation, assistant/list rail, chat area, input bar/composer, and message bubble/comment roles; the app shell component must compose those roles into one product-like surface. Placeholder component shells are not sufficient.
Claude-style UI-kit entry contract:
- When `ui_kits/app/components/*.jsx` or `*.tsx` files exist, `ui_kits/app/index.html` must behave like a runnable browser entry, not a static mock.
- Use the same structure as Claude Design exports: load React, ReactDOM, and Babel standalone scripts, load `../../colors_and_type.css`, create a `#root`, load each component script from `components/`, then render the composed `App` component.
- `App.jsx` must assign `window.App = App` (or `globalThis.App = App`), and every directly loaded component file must expose the same browser global for its component name.
- Use this skeleton for direct JSX component kits, replacing the component list only when evidence supports different names:
```html
<script src="https://unpkg.com/react@18.3.1/umd/react.development.js"></script>
<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js"></script>
<script src="https://unpkg.com/@babel/standalone@7.29.0/babel.min.js"></script>
<link rel="stylesheet" href="../../colors_and_type.css">
<div id="root"></div>
<script type="text/babel" src="components/Sidebar.jsx"></script>
<script type="text/babel" src="components/AssistantsList.jsx"></script>
<script type="text/babel" src="components/ChatArea.jsx"></script>
<script type="text/babel" src="components/MessageBubble.jsx"></script>
<script type="text/babel" src="components/InputBar.jsx"></script>
<script type="text/babel" src="components/App.jsx"></script>
<script type="text/babel">
const { App } = window;
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
</script>
```
- Preview cards and UI-kit visuals should explicitly label or model source-backed modules from the captured evidence instead of generic placeholder modules.
- assets/, build/, fonts/, and context/ should preserve logos, app icons, tray icons, installer/runtime icons, wordmarks, font files, provenance, and source notes for future projects.
Claude-style build asset contract:
- When evidence includes `context/.../files/build/...`, create a root `build/` directory and copy representative runtime assets there with their original filenames and path intent, such as `build/icon.png`, `build/logo.png`, `build/tray_icon.png`, and `build/icon.ico`.
- Copy those runtime assets byte-for-byte from the captured `context/.../files/...` snapshots. Do not redraw, re-encode, optimize, or substitute generated placeholders for files that the evidence already captured.
- Do not satisfy build/runtime icon evidence by only renaming those files into `assets/`. `assets/` may include convenience aliases, but root `build/` must preserve the source runtime files for future agents and package consumers.
- `preview/brand-assets.html` should reference at least some real preserved files from `build/` or `assets/` with `<img>`, `<picture>`, `<object>`, or CSS `url(...)`, and README.md / SKILL.md should mention `build/` in the package manifest when it exists.
- preview/brand-assets.html should visibly reference preserved files from assets/ or build/ instead of recreating logos/icons as inline placeholder drawings.
- GitHub evidence must come from the bounded `github-design-context` command, not direct connector tree/content/raw tool calls. The command tries this-device git first, authenticated GitHub CLI second, and connector-platform fallback only when local access cannot read the repository.
- Linked local folder evidence should come from the bounded `local-design-context` command, which writes a local evidence note and snapshots under `context/local-code/` before final design-system rules are drafted.
- Before marking the design system ready, run `"$OD_NODE_BIN" "$OD_BIN" tools connectors design-system-package-audit --path . --fail-on-warnings` and fix every reported error or warning.
- Draft design systems cannot be used by other projects until published.
