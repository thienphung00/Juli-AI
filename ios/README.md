# Juli AI — iOS App

Native SwiftUI app for TikTok Shop sellers. Provides phone-OTP authentication
via Supabase and a daily value loop navigation shell.

## Requirements

- Xcode 16+ (Swift 6.0 toolchain)
- iOS 17+ deployment target
- macOS 14+ for development

## Project Structure

```
ios/
├── Package.swift              # Swift package (JuliKit library + tests)
├── Sources/JuliKit/           # Testable business logic
│   ├── Models/                # Data models (AuthSession, Shop, DailyLoopTab)
│   ├── Services/              # Auth, API, Keychain, Offline cache
│   └── ViewModels/            # AuthViewModel, HomeViewModel
├── Tests/JuliKitTests/        # XCTest suite
│   └── Helpers/               # Mock HTTP client, Mock keychain
├── App/                       # SwiftUI app target (Xcode project)
│   ├── JuliAIApp.swift        # @main entry point
│   ├── ContentView.swift      # Auth state routing
│   └── Views/                 # SwiftUI views
│       ├── Auth/              # Login + OTP verification
│       ├── Home/              # Homepage + shop picker
│       └── DailyLoop/         # 5-tab daily loop shell
└── MODULE.md                  # Module contract
```

## Setup

### Option 1: Xcode Project (recommended)

1. Open Xcode → File → New → Project → iOS → App
2. Product Name: `JuliAI`, Interface: SwiftUI, Language: Swift
3. Add `JuliKit` as a local Swift Package dependency
4. Copy `App/` files into the app target
5. Add environment variables in scheme: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `API_BASE_URL`

### Option 2: Swift Package (library tests only)

```bash
cd ios/
swift test    # requires Xcode installed
```

## Configuration

Set these environment variables (or use an `.xcconfig` file):

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Supabase project URL (e.g. `https://xxx.supabase.co`) |
| `SUPABASE_ANON_KEY` | Supabase anonymous/public key |
| `API_BASE_URL` | Juli API base URL (e.g. `https://api.juli.ai`) |

## Architecture

- **Auth**: Direct Supabase REST API calls via URLSession (no heavy SDK)
- **Storage**: JWT stored in Keychain (never UserDefaults)
- **API**: URLSession with automatic Bearer token injection
- **Offline**: File-based cache with 5-minute staleness threshold
- **Navigation**: TabView-based daily loop (morning → pre-stream → live → post-stream → evening)

## What's Included (Issue #42)

- [x] Phone-OTP login with Vietnamese UI
- [x] JWT Keychain storage + session restore
- [x] Shop selection homepage
- [x] Daily value loop shell with 5 tabs
- [x] Offline cache with stale-data indicator
- [ ] Push notifications (deferred to #46)
- [ ] Live alerts (deferred to #46)
- [ ] Full morning screen data (needs API endpoints from #37)
