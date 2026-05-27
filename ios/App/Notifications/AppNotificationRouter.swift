import Foundation
import JuliKit
#if canImport(Observation)
import Observation
#endif

@Observable
final class AppNotificationRouter: @unchecked Sendable {
    static let shared = AppNotificationRouter()

    private let deepLinkParser = DeepLinkParser()
    private let alertParser = AlertEventParser()

    var pendingDeepLink: DeepLink?
    var lastAlertEvent: AlertEvent?

    private init() {}

    @MainActor
    func handleDeepLink(url: URL) {
        do {
            pendingDeepLink = try deepLinkParser.parse(url: url)
        } catch {
            pendingDeepLink = nil
        }
    }

    @MainActor
    func handleNotification(userInfo: [AnyHashable: Any]) {
        // Alert overlay (best-effort; never block navigation)
        if let event = try? alertParser.parse(userInfo: userInfo) {
            lastAlertEvent = event
        }

        // Deep link (best-effort)
        if let link = try? deepLinkParser.parse(userInfo: userInfo) {
            pendingDeepLink = link
        }
    }

    @MainActor
    func consumePendingDeepLink() -> DeepLink? {
        let link = pendingDeepLink
        pendingDeepLink = nil
        return link
    }

    @MainActor
    func consumeLastAlertEvent() -> AlertEvent? {
        let event = lastAlertEvent
        lastAlertEvent = nil
        return event
    }
}

