import Foundation

public protocol OfflineCacheServiceProtocol: Sendable {
    func cache<T: Encodable>(key: String, value: T) throws
    func retrieve<T: Decodable>(key: String, type: T.Type) throws -> CachedValue<T>?
    func clear(key: String) throws
}

public final class OfflineCacheService: OfflineCacheServiceProtocol, @unchecked Sendable {
    private let fileManager: FileManager
    private let cacheDirectory: URL
    private let staleThreshold: TimeInterval

    public init(
        cacheDirectoryName: String = "juli_offline_cache",
        staleThreshold: TimeInterval = 300,
        fileManager: FileManager = .default
    ) {
        self.fileManager = fileManager
        self.staleThreshold = staleThreshold

        let base = fileManager.urls(for: .cachesDirectory, in: .userDomainMask).first!
        self.cacheDirectory = base.appendingPathComponent(cacheDirectoryName)

        try? fileManager.createDirectory(at: cacheDirectory, withIntermediateDirectories: true)
    }

    public func cache<T: Encodable>(key: String, value: T) throws {
        let wrapper = CacheWrapper(value: value, cachedAt: Date())
        let data = try JSONEncoder.withISO8601.encode(wrapper)
        let fileURL = cacheFileURL(for: key)
        try data.write(to: fileURL, options: .atomic)
    }

    public func retrieve<T: Decodable>(key: String, type: T.Type) throws -> CachedValue<T>? {
        let fileURL = cacheFileURL(for: key)

        guard fileManager.fileExists(atPath: fileURL.path) else {
            return nil
        }

        let data = try Data(contentsOf: fileURL)
        let wrapper = try JSONDecoder.withISO8601.decode(CacheWrapper<T>.self, from: data)

        return CachedValue(
            value: wrapper.value,
            cachedAt: wrapper.cachedAt,
            staleThreshold: staleThreshold
        )
    }

    public func clear(key: String) throws {
        let fileURL = cacheFileURL(for: key)
        if fileManager.fileExists(atPath: fileURL.path) {
            try fileManager.removeItem(at: fileURL)
        }
    }

    private func cacheFileURL(for key: String) -> URL {
        let sanitized = key.replacingOccurrences(of: "/", with: "_")
        return cacheDirectory.appendingPathComponent("\(sanitized).json")
    }
}

private struct CacheWrapper<T: Codable>: Codable {
    let value: T
    let cachedAt: Date
}
