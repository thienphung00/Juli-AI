# Purpose

Use when building a modern SwiftUI iOS app in this project: state management, MVVM-style separation, async/await, DI, and testability.

# Core Principles

- Views are declarative renderers; business rules live outside UI.
- Prefer value types (`struct`) and immutable inputs; mutate in one place.
- State is single-source-of-truth; avoid duplicating the same state across layers.
- Use modern observation (`@Observable`) and async/await for I/O.
- Dependency injection via protocols; no hard-coded singletons.
- Keep navigation type-safe; routes are data, not strings.
- Performance: reduce invalidation; keep `body` cheap.
- Testability is a design constraint (inject time, network, persistence).

# Preferred Patterns

- **MVVM-style separation**
  - `View`: layout + binding only.
  - `ViewModel` (`@Observable final class`): state + orchestration; calls domain/services.
  - `Service/Repository`: protocols + concrete implementations (network, persistence).
- **State & bindings**
  - `@State` for view-owned local state; `@Binding` for parent-owned state.
  - `@Observable` for multi-property models; `@Bindable` for editable bindings.
  - Use `@Environment` for shared dependencies (router/auth/config).
- **Async**
  - Start work with `.task {}`; keep cancellation-friendly (don’t ignore cancellation).
  - Ensure UI updates occur on main actor where required.
- **Navigation**
  - `NavigationStack` + `NavigationPath` with `Hashable` destinations.
- **Composition**
  - Extract subviews to limit re-render scope; small views beat massive views.
  - Use `ViewModifier` for shared styling, not copy/paste.

# Avoid

- Massive Views containing networking/persistence/business logic.
- Singleton-heavy architecture (`shared` everywhere) and hidden global state.
- Doing I/O or heavy computation in `body` / view initializers.
- Excessive state duplication (same data kept in multiple `@State` vars).
- Type erasure (`AnyView`) as a default; prefer `@ViewBuilder`.
- “ObservableObject/@Published everywhere” in new code when `@Observable` fits.

# Code Review Checklist

- **Separation**: UI does not contain business rules or I/O.
- **State**: single source of truth; bindings flow in one direction; no duplicate state.
- **DI**: dependencies injected via protocols/environment; no implicit globals.
- **Async**: `.task` used for loads; cancellation respected; main-thread correctness.
- **Navigation**: type-safe destinations; no stringly-typed routing.
- **Performance**: large lists use lazy containers; stable IDs; `body` stays cheap.
- **Tests**: view models/services can be tested with fakes; no hardwired networking.

# Agent Instructions

- Default to `@Observable` view models + protocol-based services/repositories.
- Keep views small; move logic into view models or domain/services.
- Inject dependencies (including clocks/UUID generators) so tests are deterministic.
- Use `NavigationStack` with `Hashable` enums/structs for destinations.
- When adding features, include a minimal test plan (view model unit tests first).

