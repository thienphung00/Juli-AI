import Foundation

public enum AlertKind: String, Codable, Sendable {
    case viewerDrop = "viewer_drop"
    case lowStock = "low_stock"
}

public struct AlertEvent: Codable, Equatable, Sendable, Identifiable {
    public let id: String
    public let kind: AlertKind
    public let title: String
    public let message: String
    public let createdAt: Date

    public let orderId: String?
    public let livestreamId: String?
    public let shopId: String?

    public init(
        id: String,
        kind: AlertKind,
        title: String,
        message: String,
        createdAt: Date,
        orderId: String? = nil,
        livestreamId: String? = nil,
        shopId: String? = nil
    ) {
        self.id = id
        self.kind = kind
        self.title = title
        self.message = message
        self.createdAt = createdAt
        self.orderId = orderId
        self.livestreamId = livestreamId
        self.shopId = shopId
    }
}

public enum AlertEventParseError: Error, Equatable, Sendable {
    case missingRequiredField(String)
    case unsupported
}

public struct AlertEventParser: Sendable {
    public init() {}

    /// Parses allowlisted push `userInfo` keys into a display-ready Vietnamese alert.
    /// Keys:
    /// - `alert_kind`: viewer_drop | low_stock
    /// - `title_vi`, `message_vi` (preferred)
    /// - fallback: `title`, `message`
    /// - ids: `alert_id`, `livestream_id`, `order_id`, `shop_id`
    public func parse(userInfo: [AnyHashable: Any], now: Date = Date()) throws -> AlertEvent {
        func str(_ key: String) -> String? {
            if let s = userInfo[key] as? String { return s }
            if let n = userInfo[key] as? NSNumber { return n.stringValue }
            return nil
        }

        let rawKind = (str("alert_kind") ?? str("kind"))?.lowercased()
        guard let rawKind else { throw AlertEventParseError.missingRequiredField("alert_kind") }
        guard let kind = AlertKind(rawValue: rawKind) else { throw AlertEventParseError.unsupported }

        let title = str("title_vi") ?? str("title") ?? defaultTitle(for: kind)
        let message = str("message_vi") ?? str("message") ?? defaultMessage(for: kind)

        let id = str("alert_id") ?? UUID().uuidString
        let createdAt = (userInfo["created_at"] as? Date) ?? now

        return AlertEvent(
            id: id,
            kind: kind,
            title: title,
            message: message,
            createdAt: createdAt,
            orderId: str("order_id"),
            livestreamId: str("livestream_id"),
            shopId: str("shop_id")
        )
    }

    private func defaultTitle(for kind: AlertKind) -> String {
        switch kind {
        case .viewerDrop:
            return "Cảnh báo: giảm người xem"
        case .lowStock:
            return "Cảnh báo: sắp hết hàng"
        }
    }

    private func defaultMessage(for kind: AlertKind) -> String {
        switch kind {
        case .viewerDrop:
            return "Số người xem đang giảm. Hãy đổi kịch bản hoặc tăng tương tác ngay."
        case .lowStock:
            return "Tồn kho thấp. Hãy ghim sản phẩm khác hoặc chuẩn bị restock."
        }
    }
}

