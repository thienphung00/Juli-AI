import Foundation

public enum APIError: Error, Equatable {
    case unauthorized
    case forbidden
    case notFound
    case serverError(Int)
    case networkError(String)
    case decodingError(String)
    case noSession
}

public protocol APIClientProtocol: Sendable {
    func get<T: Decodable>(path: String, shopId: String?) async throws -> T
}

public final class APIClient: APIClientProtocol, @unchecked Sendable {
    private let baseURL: String
    private let httpClient: HTTPClient
    private let sessionProvider: @Sendable () async -> AuthSession?

    public init(
        baseURL: String,
        httpClient: HTTPClient = URLSession.shared,
        sessionProvider: @escaping @Sendable () async -> AuthSession?
    ) {
        self.baseURL = baseURL
        self.httpClient = httpClient
        self.sessionProvider = sessionProvider
    }

    public func get<T: Decodable>(path: String, shopId: String? = nil) async throws -> T {
        guard let session = await sessionProvider() else {
            throw APIError.noSession
        }

        guard let url = URL(string: "\(baseURL)\(path)") else {
            throw APIError.networkError("Invalid URL: \(baseURL)\(path)")
        }
        var request = URLRequest(url: url, timeoutInterval: 30)
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(session.accessToken)", forHTTPHeaderField: "Authorization")

        if let shopId {
            request.setValue(shopId, forHTTPHeaderField: "X-Shop-Id")
        }

        let (data, response) = try await performRequest(request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.networkError("Invalid response")
        }

        switch httpResponse.statusCode {
        case 200...299:
            break
        case 401:
            throw APIError.unauthorized
        case 403:
            throw APIError.forbidden
        case 404:
            throw APIError.notFound
        default:
            throw APIError.serverError(httpResponse.statusCode)
        }

        do {
            return try JSONDecoder.withISO8601.decode(T.self, from: data)
        } catch {
            throw APIError.decodingError(error.localizedDescription)
        }
    }

    private func performRequest(_ request: URLRequest) async throws -> (Data, URLResponse) {
        do {
            return try await httpClient.data(for: request)
        } catch let error as APIError {
            throw error
        } catch {
            throw APIError.networkError(error.localizedDescription)
        }
    }
}
