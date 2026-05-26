import Foundation
@testable import JuliKit

final class MockHTTPClient: HTTPClient, @unchecked Sendable {
    var responses: [(Data, URLResponse)] = []
    var capturedRequests: [URLRequest] = []
    var shouldThrow: Error?
    private var callIndex = 0

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        capturedRequests.append(request)
        if let error = shouldThrow {
            throw error
        }
        guard callIndex < responses.count else {
            fatalError("MockHTTPClient: no response configured for call \(callIndex)")
        }
        let response = responses[callIndex]
        callIndex += 1
        return response
    }

    func addResponse(json: Any, statusCode: Int = 200) {
        let data = try! JSONSerialization.data(withJSONObject: json)
        let response = HTTPURLResponse(
            url: URL(string: "https://test.supabase.co")!,
            statusCode: statusCode,
            httpVersion: nil,
            headerFields: nil
        )!
        responses.append((data, response))
    }

    func addResponse(data: Data, statusCode: Int = 200) {
        let response = HTTPURLResponse(
            url: URL(string: "https://test.supabase.co")!,
            statusCode: statusCode,
            httpVersion: nil,
            headerFields: nil
        )!
        responses.append((data, response))
    }
}
