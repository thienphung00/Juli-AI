import Foundation
@testable import JuliKit

final class MockKeychain: KeychainServiceProtocol, @unchecked Sendable {
    var storage: [String: Data] = [:]

    func save(key: String, data: Data) throws {
        storage[key] = data
    }

    func load(key: String) throws -> Data? {
        return storage[key]
    }

    func delete(key: String) throws {
        storage.removeValue(forKey: key)
    }
}
