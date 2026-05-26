import Foundation

public enum AuthError: Error, Equatable {
    case invalidPhoneNumber
    case otpVerificationFailed(String)
    case networkError(String)
    case sessionExpired
    case noSession
}

public protocol AuthServiceProtocol: Sendable {
    func sendOTP(phone: String) async throws
    func verifyOTP(phone: String, code: String) async throws -> AuthSession
    func restoreSession() async throws -> AuthSession?
    func logout() async throws
}

public protocol HTTPClient: Sendable {
    func data(for request: URLRequest) async throws -> (Data, URLResponse)
}

extension URLSession: HTTPClient {}

public final class AuthService: AuthServiceProtocol, @unchecked Sendable {
    private let supabaseURL: String
    private let anonKey: String
    private let httpClient: HTTPClient
    private let keychain: KeychainServiceProtocol

    static let sessionKeychainKey = "juli_auth_session"

    public init(
        supabaseURL: String,
        anonKey: String,
        httpClient: HTTPClient = URLSession.shared,
        keychain: KeychainServiceProtocol = KeychainService()
    ) {
        self.supabaseURL = supabaseURL
        self.anonKey = anonKey
        self.httpClient = httpClient
        self.keychain = keychain
    }

    public func sendOTP(phone: String) async throws {
        guard isValidVietnamesePhone(phone) else {
            throw AuthError.invalidPhoneNumber
        }

        guard let url = URL(string: "\(supabaseURL)/auth/v1/otp") else {
            throw AuthError.networkError("Invalid Supabase URL")
        }
        var request = URLRequest(url: url, timeoutInterval: 30)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(anonKey, forHTTPHeaderField: "apikey")

        let body: [String: String] = ["phone": phone]
        request.httpBody = try JSONEncoder().encode(body)

        let (_, response) = try await performRequest(request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? -1
            throw AuthError.networkError("OTP send failed with status \(statusCode)")
        }
    }

    public func verifyOTP(phone: String, code: String) async throws -> AuthSession {
        guard let url = URL(string: "\(supabaseURL)/auth/v1/verify") else {
            throw AuthError.networkError("Invalid Supabase URL")
        }
        var request = URLRequest(url: url, timeoutInterval: 30)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(anonKey, forHTTPHeaderField: "apikey")

        let body: [String: String] = [
            "phone": phone,
            "token": code,
            "type": "sms",
        ]
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await performRequest(request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? -1
            throw AuthError.otpVerificationFailed("Verification failed with status \(statusCode)")
        }

        let session = try parseSessionResponse(data)
        try storeSession(session)
        return session
    }

    public func restoreSession() async throws -> AuthSession? {
        guard let data = try keychain.load(key: Self.sessionKeychainKey) else {
            return nil
        }
        let session = try JSONDecoder.withISO8601.decode(AuthSession.self, from: data)
        if session.isExpired {
            try keychain.delete(key: Self.sessionKeychainKey)
            return nil
        }
        return session
    }

    public func logout() async throws {
        try keychain.delete(key: Self.sessionKeychainKey)
    }

    private func performRequest(_ request: URLRequest) async throws -> (Data, URLResponse) {
        do {
            return try await httpClient.data(for: request)
        } catch let error as AuthError {
            throw error
        } catch {
            throw AuthError.networkError(error.localizedDescription)
        }
    }

    private func parseSessionResponse(_ data: Data) throws -> AuthSession {
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]

        guard let accessToken = json?["access_token"] as? String,
              let refreshToken = json?["refresh_token"] as? String,
              let expiresIn = json?["expires_in"] as? Int,
              let user = json?["user"] as? [String: Any],
              let userId = user["id"] as? String else {
            throw AuthError.otpVerificationFailed("Invalid response format")
        }

        return AuthSession(
            accessToken: accessToken,
            refreshToken: refreshToken,
            expiresAt: Date().addingTimeInterval(TimeInterval(expiresIn)),
            userId: userId
        )
    }

    private func storeSession(_ session: AuthSession) throws {
        let data = try JSONEncoder.withISO8601.encode(session)
        try keychain.save(key: Self.sessionKeychainKey, data: data)
    }

    private func isValidVietnamesePhone(_ phone: String) -> Bool {
        let cleaned = phone.replacingOccurrences(of: " ", with: "")
        let pattern = #"^\+84[0-9]{9,10}$"#
        return cleaned.range(of: pattern, options: .regularExpression) != nil
    }
}

extension JSONEncoder {
    static let withISO8601: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }()
}

extension JSONDecoder {
    static let withISO8601: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }()
}
