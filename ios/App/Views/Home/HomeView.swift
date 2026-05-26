import SwiftUI

struct HomeView: View {
    @Bindable var viewModel: HomeViewModel
    var onLogout: () -> Void

    @State private var showShopPicker = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if viewModel.isUsingCachedData {
                    staleDataBanner
                }

                DailyLoopView(viewModel: viewModel)
            }
            .navigationTitle(viewModel.selectedShop?.name ?? "Juli AI")
            .navigationBarTitleDisplayMode(.inline)
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
}
