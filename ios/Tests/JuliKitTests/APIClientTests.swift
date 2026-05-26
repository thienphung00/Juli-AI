import XCTest
@testable import JuliKit

/// AC3 — API client attaches Bearer token and fetches shop data
final class APIClientTests: XCTestCase {

    private var httpClient: MockHTTPClient!
    private var session: AuthSession!
    private var sut: APIClient!

    override func setUp() {
        super.setUp()
        httpClient = MockHTTPClient()
        session = AuthSession(
            accessToken: "test-jwt-token",
            refreshToken: "test-refresh",
            expiresAt: Date().addingTimeInterval(3600),
            userId: "user-123"
        )
        sut = APIClient(
            baseURL: "https://api.juli.ai",
            httpClient: httpClient,
            sessionProvider: { [session] in session }
        )
    }

    /// AC3: API client attaches Bearer token to every request
    func test_api_client_attaches_bearer_token() async throws {
        let shopsJSON = [["id": "shop-1", "name": "Shop Test", "region": "VN"]]
        httpClient.addResponse(json: shopsJSON, statusCode: 200)

        let _: [Shop] = try await sut.get(path: "/v1/shops")

        XCTAssertEqual(httpClient.capturedRequests.count, 1)
        let request = httpClient.capturedRequests[0]
        XCTAssertEqual(
            request.value(forHTTPHeaderField: "Authorization"),
            "Bearer test-jwt-token"
        )
    }

    /// AC3: API client attaches X-Shop-Id header when provided
    func test_api_client_attaches_shop_id_header() async throws {
        let shopJSON = ["id": "shop-1", "name": "Shop Test", "region": "VN"]
        httpClient.addResponse(json: shopJSON, statusCode: 200)

        let _: Shop = try await sut.get(path: "/v1/shops/me", shopId: "shop-1")

        let request = httpClient.capturedRequests[0]
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-Shop-Id"), "shop-1")
    }

    /// AC3: fetching shops returns parsed shop list
    func test_fetch_shops_success() async throws {
        let shopsJSON: [[String: String]] = [
            ["id": "shop-1", "name": "Shop Một", "region": "VN"],
            ["id": "shop-2", "name": "Shop Hai", "region": "VN"],
        ]
        httpClient.addResponse(json: shopsJSON, statusCode: 200)

        let shops: [Shop] = try await sut.get(path: "/v1/shops")

        XCTAssertEqual(shops.count, 2)
        XCTAssertEqual(shops[0].name, "Shop Một")
        XCTAssertEqual(shops[1].name, "Shop Hai")
    }

    /// AC3: 401 response throws unauthorized
    func test_api_client_unauthorized_throws() async {
        httpClient.addResponse(json: ["error": "unauthorized"], statusCode: 401)

        do {
            let _: [Shop] = try await sut.get(path: "/v1/shops")
            XCTFail("Expected APIError.unauthorized")
        } catch let error as APIError {
            XCTAssertEqual(error, .unauthorized)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    /// AC3: no session throws noSession error
    func test_api_client_no_session_throws() async {
        let clientWithoutSession = APIClient(
            baseURL: "https://api.juli.ai",
            httpClient: httpClient,
            sessionProvider: { nil }
        )

        do {
            let _: [Shop] = try await clientWithoutSession.get(path: "/v1/shops")
            XCTFail("Expected APIError.noSession")
        } catch let error as APIError {
            XCTAssertEqual(error, .noSession)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }
}
