import Foundation

public enum DailyLoopTab: String, CaseIterable, Identifiable, Sendable {
    case morning = "morning"
    case preStream = "pre_stream"
    case live = "live"
    case postStream = "post_stream"
    case evening = "evening"

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .morning: return "Sáng"
        case .preStream: return "Trước livestream"
        case .live: return "Đang live"
        case .postStream: return "Sau livestream"
        case .evening: return "Tối"
        }
    }

    public var systemImage: String {
        switch self {
        case .morning: return "sunrise"
        case .preStream: return "list.clipboard"
        case .live: return "video"
        case .postStream: return "chart.bar"
        case .evening: return "moon.stars"
        }
    }

    public static let defaultTab: DailyLoopTab = .morning
}
