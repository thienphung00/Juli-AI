import Foundation

public struct CachedValue<T: Sendable>: Sendable {
    public let value: T
    public let cachedAt: Date
    private let staleThreshold: TimeInterval

    public init(value: T, cachedAt: Date, staleThreshold: TimeInterval = 300) {
        self.value = value
        self.cachedAt = cachedAt
        self.staleThreshold = staleThreshold
    }

    public var isStale: Bool {
        Date().timeIntervalSince(cachedAt) > staleThreshold
    }

    public var age: TimeInterval {
        Date().timeIntervalSince(cachedAt)
    }
}
