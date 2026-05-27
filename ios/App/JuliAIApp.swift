import SwiftUI

@main
struct JuliAIApp: App {
    @UIApplicationDelegateAdaptor(JuliAIAppDelegate.self) private var appDelegate
    @State private var authViewModel: AuthViewModel
    @State private var homeViewModel: HomeViewModel?

    init() {
        let authService = AuthService(
            supabaseURL: Configuration.supabaseURL,
            anonKey: Configuration.supabaseAnonKey
        )
        _authViewModel = State(initialValue: AuthViewModel(authService: authService))
    }

    var body: some Scene {
        WindowGroup {
            ContentView(authViewModel: authViewModel)
                .task {
                    await authViewModel.restoreSession()
                }
        }
    }
}

enum Configuration {
    static var supabaseURL: String {
        ProcessInfo.processInfo.environment["SUPABASE_URL"] ?? "https://your-project.supabase.co"
    }

    static var supabaseAnonKey: String {
        ProcessInfo.processInfo.environment["SUPABASE_ANON_KEY"] ?? ""
    }

    static var apiBaseURL: String {
        ProcessInfo.processInfo.environment["API_BASE_URL"] ?? "https://api.juli.ai"
    }
}
