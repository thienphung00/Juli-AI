import SwiftUI
import JuliKit

struct HomeView: View {
    @Bindable var viewModel: HomeViewModel
    @Bindable var router: AppNotificationRouter
    var onLogout: () -> Void

    @State private var showShopPicker = false
    @State private var path = NavigationPath()
    @State private var liveAlertsStore = LiveAlertsStore()

    var body: some View {
        NavigationStack(path: $path) {
            VStack(spacing: 0) {
                if viewModel.isUsingCachedData {
                    staleDataBanner
                }

                DailyLoopView(viewModel: viewModel, liveAlertsStore: liveAlertsStore)
            }
            .navigationTitle(viewModel.selectedShop?.name ?? "Juli AI")
            .navigationBarTitleDisplayMode(.inline)
            .navigationDestination(for: AppRoute.self) { route in
                switch route {
                case .orderDetail(let orderId):
                    PlaceholderTabView(
                        icon: "cart",
                        title: "Đơn hàng \(orderId)",
                        subtitle: "Màn hình chi tiết đơn hàng sẽ được bổ sung ở phiên bản tiếp theo.",
                        color: .blue
                    )
                case .livestream(let livestreamId):
                    PlaceholderTabView(
                        icon: "video",
                        title: "Livestream \(livestreamId)",
                        subtitle: "Màn hình chi tiết livestream sẽ được bổ sung ở phiên bản tiếp theo.",
                        color: .red
                    )
                case .inventory(let shopId):
                    PlaceholderTabView(
                        icon: "shippingbox",
                        title: "Tồn kho",
                        subtitle: shopId.map { "Shop: \($0)" } ?? "Màn hình tồn kho sẽ được bổ sung ở phiên bản tiếp theo.",
                        color: .purple
                    )
                }
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    shopPickerButton
                }
                ToolbarItem(placement: .topBarTrailing) {
                    logoutButton
                }
            }
            .sheet(isPresented: $showShopPicker) {
                ShopSelectionSheet(
                    shops: viewModel.shops,
                    selectedShop: viewModel.selectedShop,
                    onSelect: { shop in
                        viewModel.selectShop(shop)
                        showShopPicker = false
                    }
                )
                .presentationDetents([.medium])
            }
            .task {
                await viewModel.loadShops()
            }
            .onOpenURL { url in
                Task { @MainActor in
                    router.handleDeepLink(url: url)
                }
            }
            .onChange(of: router.pendingDeepLink) { _, _ in
                Task { @MainActor in
                    guard let link = router.consumePendingDeepLink() else { return }
                    handle(link: link)
                }
            }
            .onChange(of: router.lastAlertEvent) { _, _ in
                Task { @MainActor in
                    guard let event = router.consumeLastAlertEvent() else { return }
                    liveAlertsStore.ingest(event)
                }
            }
        }
    }

    private var staleDataBanner: some View {
        HStack(spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
            Text("Đang dùng dữ liệu cũ. Kéo để làm mới.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity)
        .background(.orange.opacity(0.1))
    }

    private var shopPickerButton: some View {
        Button {
            showShopPicker = true
        } label: {
            HStack(spacing: 4) {
                Image(systemName: "storefront")
                if viewModel.shops.count > 1 {
                    Image(systemName: "chevron.down")
                        .font(.caption2)
                }
            }
        }
        .disabled(viewModel.shops.count <= 1)
    }

    private var logoutButton: some View {
        Button {
            onLogout()
        } label: {
            Image(systemName: "rectangle.portrait.and.arrow.right")
        }
    }

    @MainActor
    private func handle(link: DeepLink) {
        switch link {
        case .orderDetail(let orderId):
            path.append(AppRoute.orderDetail(orderId: orderId))
        case .livestream(let livestreamId):
            viewModel.selectTab(.live)
            path.append(AppRoute.livestream(livestreamId: livestreamId))
        case .inventory(let shopId):
            path.append(AppRoute.inventory(shopId: shopId))
        }
    }
}

enum AppRoute: Hashable {
    case orderDetail(orderId: String)
    case livestream(livestreamId: String)
    case inventory(shopId: String?)
}
