import Foundation
#if canImport(Observation)
import Observation
#endif

@Observable
public final class LiveAlertsStore: @unchecked Sendable {
    public private(set) var recent: [AlertEvent] = []

    public init() {}

    @MainActor
    public func ingest(_ event: AlertEvent, maxCount: Int = 10) {
        recent.insert(event, at: 0)
        if recent.count > maxCount {
            recent = Array(recent.prefix(maxCount))
        }
    }

    @MainActor
    public func clear() {
        recent.removeAll()
    }
}

