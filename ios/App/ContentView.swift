import SwiftUI

struct ContentView: View {
    @Bindable var authViewModel: AuthViewModel

    var body: some View {
        Group {
            switch authViewModel.state {
            case .authenticated(let session):
                let apiClient = APIClient(
                    baseURL: Configuration.apiBaseURL,
                    sessionProvider: { session }
                )
                let cache = OfflineCacheService()
                let homeVM = HomeViewModel(apiClient: apiClient, cache: cache)

                HomeView(viewModel: homeVM, onLogout: {
                    Task { await authViewModel.logout() }
                })

            default:
                LoginView(viewModel: authViewModel)
            }
        }
        .animation(.easeInOut, value: authViewModel.state == .idle)
    }
}
