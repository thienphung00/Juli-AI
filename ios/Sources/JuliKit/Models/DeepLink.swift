import Foundation

public enum DeepLink: Equatable, Sendable {
    case orderDetail(orderId: String)
    case livestream(livestreamId: String)
    case inventory(shopId: String?)
}

public enum DeepLinkParseError: Error, Equatable, Sendable {
    case unsupported
    case missingRequiredField(String)
}

public struct DeepLinkParser: Sendable {
    public init() {}

    public func parse(url: URL) throws -> DeepLink {
        guard url.scheme?.lowercased() == "juli" else { throw DeepLinkParseError.unsupported }

        let host = (url.host ?? "").lowercased()
        let pathParts = url.path.split(separator: "/").map(String.init)

        switch host {
        case "order":
            guard let orderId = pathParts.first, !orderId.isEmpty else {
                throw DeepLinkParseError.missingRequiredField("orderId")
            }
            return .orderDetail(orderId: orderId)

        case "livestream":
            guard let livestreamId = pathParts.first, !livestreamId.isEmpty else {
                throw DeepLinkParseError.missingRequiredField("livestreamId")
            }
            return .livestream(livestreamId: livestreamId)

        case "inventory":
            let shopId = URLComponents(url: url, resolvingAgainstBaseURL: false)?
                .queryItems?
                .first(where: { $0.name == "shop_id" })?
                .value
            return .inventory(shopId: shopId)

        default:
            throw DeepLinkParseError.unsupported
        }
    }

    /// Best-effort parsing from push `userInfo`.
    /// Expected allowlisted fields:
    /// - `type`: `order` | `livestream` | `inventory`
    /// - `order_id`, `livestream_id`, `shop_id`
    public func parse(userInfo: [AnyHashable: Any]) throws -> DeepLink {
        let type = (userInfo["type"] as? String)?.lowercased() ?? (userInfo["deeplink_type"] as? String)?.lowercased()
        guard let type else { throw DeepLinkParseError.missingRequiredField("type") }

        func str(_ key: String) -> String? {
            if let s = userInfo[key] as? String { return s }
            if let n = userInfo[key] as? NSNumber { return n.stringValue }
            return nil
        }

        switch type {
        case "order":
            guard let orderId = str("order_id"), !orderId.isEmpty else {
                throw DeepLinkParseError.missingRequiredField("order_id")
            }
            return .orderDetail(orderId: orderId)
        case "livestream":
            guard let livestreamId = str("livestream_id"), !livestreamId.isEmpty else {
                throw DeepLinkParseError.missingRequiredField("livestream_id")
            }
            return .livestream(livestreamId: livestreamId)
        case "inventory":
            return .inventory(shopId: str("shop_id"))
        default:
            throw DeepLinkParseError.unsupported
        }
    }
}

