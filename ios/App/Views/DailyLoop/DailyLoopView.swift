import SwiftUI
import JuliKit

struct DailyLoopView: View {
    @Bindable var viewModel: HomeViewModel
    @Bindable var liveAlertsStore: LiveAlertsStore

    var body: some View {
        TabView(selection: $viewModel.selectedTab) {
            ForEach(DailyLoopTab.allCases) { tab in
                tabContent(for: tab)
                    .tabItem {
                        Label(tab.displayName, systemImage: tab.systemImage)
                    }
                    .tag(tab)
            }
        }
    }

    @ViewBuilder
    private func tabContent(for tab: DailyLoopTab) -> some View {
        switch tab {
        case .morning:
            MorningSummaryView(shopName: viewModel.selectedShop?.name ?? "")
        case .preStream:
            PreStreamView()
        case .live:
            LiveAlertsView(store: liveAlertsStore)
        case .postStream:
            PostStreamView()
        case .evening:
            EveningPrepView()
        }
    }
}
