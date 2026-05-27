import XCTest
@testable import JuliKit

final class PushNotificationParsingTests: XCTestCase {

    func test_push_notification_rendering_uses_vietnamese_title_and_message() throws {
        let userInfo: [AnyHashable: Any] = [
            "alert_kind": "low_stock",
            "title_vi": "Cảnh báo: sắp hết hàng — Áo thun",
            "message_vi": "Sản phẩm \"Áo thun\" chỉ còn 3 chiếc. Hãy ghim sản phẩm khác hoặc restock.",
            "alert_id": "a1",
            "shop_id": "s1",
        ]

        let event = try AlertEventParser().parse(userInfo: userInfo, now: Date(timeIntervalSince1970: 0))

        XCTAssertEqual(event.kind, .lowStock)
        XCTAssertEqual(event.title, "Cảnh báo: sắp hết hàng — Áo thun")
        XCTAssertTrue(event.message.contains("chỉ còn 3 chiếc"))
    }

    func test_notification_deep_link_from_userInfo_order() throws {
        let userInfo: [AnyHashable: Any] = [
            "type": "order",
            "order_id": "o_123",
        ]

        let link = try DeepLinkParser().parse(userInfo: userInfo)
        XCTAssertEqual(link, .orderDetail(orderId: "o_123"))
    }

    func test_notification_deep_link_from_url_livestream() throws {
        let url = URL(string: "juli://livestream/ls_456")!
        let link = try DeepLinkParser().parse(url: url)
        XCTAssertEqual(link, .livestream(livestreamId: "ls_456"))
    }

    func test_livestream_alert_overlay_store_ingests_recent_events() async throws {
        let store = LiveAlertsStore()
        let event = AlertEvent(
            id: "e1",
            kind: .viewerDrop,
            title: "Cảnh báo: giảm người xem",
            message: "Người xem giảm mạnh trong 2 phút gần đây.",
            createdAt: Date(timeIntervalSince1970: 0),
            livestreamId: "ls_1"
        )

        await MainActor.run {
            store.ingest(event)
        }

        let recent = await MainActor.run { store.recent }
        XCTAssertEqual(recent.count, 1)
        XCTAssertEqual(recent.first?.id, "e1")
    }
}

