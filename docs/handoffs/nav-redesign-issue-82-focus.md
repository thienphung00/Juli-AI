# Handoff: focus → tdd — Issue #82

## Issue
- **#82** — Nav redesign 7/8: Juli AI chat tab (mode-aware prompts + UI-only mock)
- Parent PRD: https://github.com/thienphung00/Juli-AI/issues/75
- Blocker #77: **merged** (Juli tab at `/ai-chat` in bottom nav)

## Acceptance criteria
- Juli tab opens a chat interface within 1 tap from bottom navigation.
- Suggested prompts differ between Seller and Affiliate mode.
- With `NEXT_PUBLIC_UI_ONLY=1`, chat renders and sends mock replies without API calls.

## Worktree
```bash
cd ../juli-ai-issue-82   # branch feat/issue-82-ai-chat-tab
```

## Context loaded (focus)

### Architecture
- `docs/architecture/map.md` — web tier only; no backend in MVP
- `docs/features/nav-redesign/PRD.md` — § Mock Data — AI Chat (~1380–1413)
- `web/MODULE.md` — `/ai-chat` placeholder → full chat UI
- Reference UI (not copy verbatim): `/Users/macos/Downloads/figma_design/src/app/components/AIAssistantScreen.tsx`

### Existing patterns
- Route: `web/src/app/ai-chat/page.tsx` → `AiChatPage` (placeholder)
- Component: `web/src/components/AiChatPage.tsx` — **replace placeholder**
- Mode: `useWorkspaceMode()` for seller vs affiliate prompts
- Shell: `AuthenticatedShell` — chat can use `title="Juli"` and optional subtitle
- Service pattern: `home.ts` / `services/*` with `isUiOnly` branch
- Nav: `/ai-chat` already in `BOTTOM_NAV_TABS` (#77)

### MCP / tools
- None required (frontend-only mock chat)

### Implementation approach

**New files**
| File | Purpose |
|------|---------|
| `web/src/lib/mock-data/ai-chat.ts` | `MOCK_AI_CHAT` — suggested_prompts (seller/affiliate), mock_conversation seed |
| `web/src/lib/services/ai-chat.ts` | `getChatBootstrap(mode)`, `sendMockMessage(mode, text)` — no API in UI-only |
| `web/src/components/ai-chat/ChatMessageList.tsx` | User + assistant bubbles |
| `web/src/components/ai-chat/ChatInput.tsx` | Input + send; Vietnamese placeholder |
| `web/src/components/ai-chat/SuggestedPrompts.tsx` | Mode-aware chip list |
| `web/src/__tests__/test_ai_chat_tab.test.tsx` | AC coverage |

**Modified files**
| File | Change |
|------|--------|
| `web/src/components/AiChatPage.tsx` | Compose chat UI; load bootstrap on mode change |
| `web/MODULE.md` | Update `/ai-chat` description |

**Chat behavior (MVP)**
- On load: show welcome (from mock or mode-specific copy) + suggested prompt chips
- Tap prompt or send message → append user bubble → mock assistant reply after short delay (no fetch)
- Seller vs affiliate: different `suggested_prompts` arrays (see PRD)
- Optional: action links on assistant messages (`href` from mock)
- Streaming: **not required** for MVP; optional placeholder comment only

**UI-only**
- `services/ai-chat.ts` never calls `api-client` when `isUiOnly`
- Deterministic mock replies (keyword map or default fallback)

### DO NOT touch
- `web/src/components/OperationPage.tsx`, `web/operation/**` — owned by #81
- `web/src/lib/nav-config.ts` — already shipped
- Backend `POST /v1/ai/chat` — v1.5 only

### Standards applied
- [x] Maintainability — small subcomponents under `ai-chat/`
- [x] Observability — `console.error` on unexpected service errors only
- [x] Security — sanitize display only; no user HTML injection

## TDD plan (red → green → refactor)

1. **RED** — `test_ai_chat_tab.test.tsx`:
   - Renders message list + input + send button
   - Seller mode shows seller suggested prompts (e.g. "Creator nào nên đẩy tối nay?")
   - Affiliate mode shows different prompts (e.g. "Sản phẩm nào đang xu hướng")
   - Sending a message appends user + mock assistant reply without API
   - UI-only path uses mock service only
2. **GREEN** — mock data + service + AiChatPage composition
3. **REFACTOR** — extract reply logic to service if component grows

## Review → ship checklist
- `cd web && npm test -- test_ai_chat_tab`
- `npm run lint` in web/
- PR title: `feat(web): Juli AI chat tab with mode-aware prompts (#82)`
- Parallel: commit locally; hand branch + PR draft to GitHub ops owner (do not push unless ops owner)
