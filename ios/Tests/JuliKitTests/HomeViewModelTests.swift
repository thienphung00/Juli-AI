import XCTest
@testable import JuliKit

/// AC4 — Daily value loop navigation: all tabs present, default is morning
final class HomeViewModelTests: XCTestCase {

    /// AC4: all five daily loop tabs are present
    func test_daily_loop_all_tabs_present() {
        let tabs = DailyLoopTab.allCases

        XCTAssertEqual(tabs.count, 5)
        XCTAssertTrue(tabs.contains(.morning))
        XCTAssertTrue(tabs.contains(.preStream))
        XCTAssertTrue(tabs.contains(.live))
        XCTAssertTrue(tabs.contains(.postStream))
        XCTAssertTrue(tabs.contains(.evening))
    }

    /// AC4: default tab is morning
    func test_daily_loop_default_tab_morning() {
        XCTAssertEqual(DailyLoopTab.defaultTab, .morning)

        let vm = HomeViewModel(
            apiClient: MockAPIClient(),
            cache: MockOfflineCache()
        )
        XCTAssertEqual(vm.selectedTab, .morning)
    }

    /// AC4: tab selection updates the selected tab
    func test_daily_loop_tab_selection() {
        let vm = HomeViewModel(
            apiClient: MockAPIClient(),
            cache: MockOfflineCache()
        )

        vm.selectTab(.preStream)
        XCTAssertEqual(vm.selectedTab, .preStream)

        vm.selectTab(.evening)
        XCTAssertEqual(vm.selectedTab, .evening)
    }

    /// AC4: daily loop tabs have Vietnamese display names
    func test_daily_loop_tabs_have_display_names() {
        for tab in DailyLoopTab.allCases {
            XCTAssertFalse(tab.displayName.isEmpty, "\(tab) should have a display name")
        }

        XCTAssertEqual(DailyLoopTab.morning.displayName, "Sáng")
    }

    /// AC3 + AC5: load shops from API, fallback to cache on failure
    @MainActor
    func test_load_shops_success() async {
        let mockAPI = MockAPIClient()
        mockAPI.shopsToReturn = [
            Shop(id: "s1", name: "Shop Một", region: "VN"),
        ]
        let vm = HomeViewModel(apiClient: mockAPI, cache: MockOfflineCache())

        await vm.loadShops()

        XCTAssertEqual(vm.shops.count, 1)
        XCTAssertEqual(vm.selectedShop?.id, "s1")
        XCTAssertFalse(vm.isUsingCachedData)
    }

    /// AC5: shows stale data indicator when using cached data
    @MainActor
    func test_load_shops_falls_back_to_cache() async {
        let mockAPI = MockAPIClient()
        mockAPI.shouldThrow = APIError.networkError("offline")

        let mockCache = MockOfflineCache()
        mockCache.cachedShops = [Shop(id: "s1", name: "Cached Shop", region: "VN")]
        mockCache.isStale = true

        let vm = HomeViewModel(apiClient: mockAPI, cache: mockCache)
        await vm.loadShops()

        XCTAssertEqual(vm.shops.count, 1)
        XCTAssertEqual(vm.shops[0].name, "Cached Shop")
        XCTAssertTrue(vm.isUsingCachedData, "Should show stale data indicator")
    }

    /// AC5: shop selection persists
    @MainActor
    func test_shop_selection() async {
        let mockAPI = MockAPIClient()
        mockAPI.shopsToReturn = [
            Shop(id: "s1", name: "Shop 1", region: "VN"),
            Shop(id: "s2", name: "Shop 2", region: "VN"),
        ]
        let vm = HomeViewModel(apiClient: mockAPI, cache: MockOfflineCache())
        await vm.loadShops()

        vm.selectShop(vm.shops[1])

        XCTAssertEqual(vm.selectedShop?.id, "s2")
    }
}

// MARK: - Test Doubles

private final class MockAPIClient: APIClientProtocol, @unchecked Sendable {
    var shopsToReturn: [Shop] = []
    var shouldThrow: Error?

    func get<T: Decodable>(path: String, shopId: String?) async throws -> T {
        if let error = shouldThrow { throw error }
        return shopsToReturn as! T
    }
}

private final class MockOfflineCache: OfflineCacheServiceProtocol, @unchecked Sendable {
    var cachedShops: [Shop]?
    var isStale = false
    var storedValues: [String: Any] = [:]

    func cache<T: Encodable>(key: String, value: T) throws {
        storedValues[key] = value
    }

    func retrieve<T: Decodable>(key: String, type: T.Type) throws -> CachedValue<T>? {
        if T.self == [Shop].self, let shops = cachedShops {
            let cachedAt = isStale ? Date().addingTimeInterval(-600) : Date()
            return CachedValue(
                value: shops as! T,
                cachedAt: cachedAt,
                staleThreshold: 300
            )
        }
        return nil
    }

    func clear(key: String) throws {
        storedValues.removeValue(forKey: key)
    }
}
