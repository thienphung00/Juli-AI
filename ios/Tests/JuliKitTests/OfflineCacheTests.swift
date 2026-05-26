import XCTest
@testable import JuliKit

/// AC5 — Offline-capable: caches last sync data, shows stale-data indicator
final class OfflineCacheTests: XCTestCase {

    private var sut: OfflineCacheService!

    override func setUp() {
        super.setUp()
        sut = OfflineCacheService(
            cacheDirectoryName: "juli_test_cache_\(UUID().uuidString)",
            staleThreshold: 2
        )
    }

    override func tearDown() {
        sut = nil
        super.tearDown()
    }

    /// AC5: cache stores and retrieves data correctly
    func test_cache_store_and_retrieve() throws {
        let shops = [
            Shop(id: "s1", name: "Shop Một", region: "VN"),
            Shop(id: "s2", name: "Shop Hai", region: "VN"),
        ]

        try sut.cache(key: "shops", value: shops)

        let cached = try sut.retrieve(key: "shops", type: [Shop].self)
        XCTAssertNotNil(cached)
        XCTAssertEqual(cached?.value.count, 2)
        XCTAssertEqual(cached?.value[0].name, "Shop Một")
    }

    /// AC5: empty cache returns nil
    func test_cache_empty_returns_nil() throws {
        let cached = try sut.retrieve(key: "nonexistent", type: [Shop].self)
        XCTAssertNil(cached)
    }

    /// AC5: stale-data indicator activates after threshold
    func test_cache_staleness_detection() throws {
        let shops = [Shop(id: "s1", name: "Test", region: "VN")]
        try sut.cache(key: "shops", value: shops)

        let fresh = try sut.retrieve(key: "shops", type: [Shop].self)
        XCTAssertNotNil(fresh)
        XCTAssertFalse(fresh!.isStale, "Freshly cached data should not be stale")

        // Wait for staleness threshold (2 seconds for test)
        let expectation = XCTestExpectation(description: "Wait for staleness")
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
            expectation.fulfill()
        }
        wait(for: [expectation], timeout: 5)

        let stale = try sut.retrieve(key: "shops", type: [Shop].self)
        XCTAssertNotNil(stale)
        XCTAssertTrue(stale!.isStale, "Data older than threshold should be stale")
    }

    /// AC5: clear removes cached data
    func test_cache_clear() throws {
        let shops = [Shop(id: "s1", name: "Test", region: "VN")]
        try sut.cache(key: "shops", value: shops)

        try sut.clear(key: "shops")

        let cached = try sut.retrieve(key: "shops", type: [Shop].self)
        XCTAssertNil(cached)
    }
}
