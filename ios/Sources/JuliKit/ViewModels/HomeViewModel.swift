import Foundation
#if canImport(Observation)
import Observation
#endif

@Observable
public final class HomeViewModel: @unchecked Sendable {
    public private(set) var shops: [Shop] = []
    public var selectedShop: Shop?
    public var selectedTab: DailyLoopTab = .morning
    public private(set) var isLoading = false
    public private(set) var errorMessage: String?
    public private(set) var isUsingCachedData = false

    private let apiClient: APIClientProtocol
    private let cache: OfflineCacheServiceProtocol

    private static let shopsCacheKey = "shops_list"

    public init(apiClient: APIClientProtocol, cache: OfflineCacheServiceProtocol) {
        self.apiClient = apiClient
        self.cache = cache
    }

    @MainActor
    public func loadShops() async {
        isLoading = true
        errorMessage = nil
        isUsingCachedData = false

        do {
            let fetched: [Shop] = try await apiClient.get(path: "/v1/shops", shopId: nil)
            shops = fetched
            selectedShop = fetched.first
            try? cache.cache(key: Self.shopsCacheKey, value: fetched)
            isUsingCachedData = false
        } catch {
            if let cached = try? cache.retrieve(key: Self.shopsCacheKey, type: [Shop].self) {
                shops = cached.value
                selectedShop = cached.value.first
                isUsingCachedData = cached.isStale
            }
            errorMessage = "Không thể tải danh sách shop. Đang dùng dữ liệu cũ."
        }

        isLoading = false
    }

    public func selectShop(_ shop: Shop) {
        selectedShop = shop
    }

    public func selectTab(_ tab: DailyLoopTab) {
        selectedTab = tab
    }
}
