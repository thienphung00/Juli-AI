import XCTest
@testable import JuliKit

/// AC1 — Phone-OTP login via Supabase with native Vietnamese UI
final class AuthServiceTests: XCTestCase {

    private var httpClient: MockHTTPClient!
    private var keychain: MockKeychain!
    private var sut: AuthService!

    override func setUp() {
        super.setUp()
        httpClient = MockHTTPClient()
        keychain = MockKeychain()
        sut = AuthService(
            supabaseURL: "https://test.supabase.co",
            anonKey: "test-anon-key",
            httpClient: httpClient,
            keychain: keychain
        )
    }

    // MARK: - sendOTP

    /// AC1: valid Vietnamese phone sends OTP successfully
    func test_send_otp_success() async throws {
        httpClient.addResponse(json: [:], statusCode: 200)

        try await sut.sendOTP(phone: "+84912345678")

        XCTAssertEqual(httpClient.capturedRequests.count, 1)
        let request = httpClient.capturedRequests[0]
        XCTAssertEqual(request.url?.path, "/auth/v1/otp")
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.value(forHTTPHeaderField: "apikey"), "test-anon-key")
    }

    /// AC1: invalid phone number format is rejected before network call
    func test_send_otp_invalid_phone() async {
        do {
            try await sut.sendOTP(phone: "0912345678")
            XCTFail("Expected AuthError.invalidPhoneNumber")
        } catch let error as AuthError {
            XCTAssertEqual(error, .invalidPhoneNumber)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }

        XCTAssertTrue(httpClient.capturedRequests.isEmpty, "No request should be made for invalid phone")
    }

    /// AC1: phone without +84 prefix is rejected
    func test_send_otp_non_vietnamese_phone() async {
        do {
            try await sut.sendOTP(phone: "+1555123456")
            XCTFail("Expected AuthError.invalidPhoneNumber")
        } catch let error as AuthError {
            XCTAssertEqual(error, .invalidPhoneNumber)
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    // MARK: - verifyOTP

    /// AC1: successful OTP verification returns a session
    func test_verify_otp_returns_session() async throws {
        let sessionJSON: [String: Any] = [
            "access_token": "jwt-token-123",
            "refresh_token": "refresh-token-456",
            "expires_in": 3600,
            "user": ["id": "user-id-789"],
        ]
        httpClient.addResponse(json: sessionJSON, statusCode: 200)

        let session = try await sut.verifyOTP(phone: "+84912345678", code: "123456")

        XCTAssertEqual(session.accessToken, "jwt-token-123")
        XCTAssertEqual(session.refreshToken, "refresh-token-456")
        XCTAssertEqual(session.userId, "user-id-789")
        XCTAssertFalse(session.isExpired)
    }

    /// AC1: successful verification stores JWT in Keychain
    func test_verify_otp_stores_jwt_in_keychain() async throws {
        let sessionJSON: [String: Any] = [
            "access_token": "jwt-token-123",
            "refresh_token": "refresh-token-456",
            "expires_in": 3600,
            "user": ["id": "user-id-789"],
        ]
        httpClient.addResponse(json: sessionJSON, statusCode: 200)

        _ = try await sut.verifyOTP(phone: "+84912345678", code: "123456")

        let storedData = try keychain.load(key: AuthService.sessionKeychainKey)
        XCTAssertNotNil(storedData, "Session must be stored in Keychain")

        let storedSession = try JSONDecoder.withISO8601.decode(AuthSession.self, from: storedData!)
        XCTAssertEqual(storedSession.accessToken, "jwt-token-123")
    }

    /// AC1: failed verification returns error
    func test_verify_otp_server_error() async {
        httpClient.addResponse(json: ["error": "invalid_otp"], statusCode: 400)

        do {
            _ = try await sut.verifyOTP(phone: "+84912345678", code: "000000")
            XCTFail("Expected AuthError.otpVerificationFailed")
        } catch let error as AuthError {
            if case .otpVerificationFailed = error {
                // expected
            } else {
                XCTFail("Expected otpVerificationFailed, got \(error)")
            }
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    // MARK: - restoreSession

    /// AC1: restores session from Keychain on app launch
    func test_restore_session_from_keychain() async throws {
        let session = AuthSession(
            accessToken: "saved-jwt",
            refreshToken: "saved-refresh",
            expiresAt: Date().addingTimeInterval(3600),
            userId: "user-123"
        )
        let data = try JSONEncoder.withISO8601.encode(session)
        try keychain.save(key: AuthService.sessionKeychainKey, data: data)

        let restored = try await sut.restoreSession()

        XCTAssertNotNil(restored)
        XCTAssertEqual(restored?.accessToken, "saved-jwt")
    }

    /// AC1: expired session in Keychain is cleaned up
    func test_restore_session_expired_clears_keychain() async throws {
        let session = AuthSession(
            accessToken: "expired-jwt",
            refreshToken: "expired-refresh",
            expiresAt: Date().addingTimeInterval(-3600),
            userId: "user-123"
        )
        let data = try JSONEncoder.withISO8601.encode(session)
        try keychain.save(key: AuthService.sessionKeychainKey, data: data)

        let restored = try await sut.restoreSession()

        XCTAssertNil(restored)
        XCTAssertNil(try keychain.load(key: AuthService.sessionKeychainKey))
    }

    /// AC1: no session returns nil
    func test_restore_session_empty_keychain() async throws {
        let restored = try await sut.restoreSession()
        XCTAssertNil(restored)
    }

    // MARK: - logout

    func test_logout_clears_keychain() async throws {
        try keychain.save(key: AuthService.sessionKeychainKey, data: Data("test".utf8))

        try await sut.logout()

        XCTAssertNil(try keychain.load(key: AuthService.sessionKeychainKey))
    }
}
