import Foundation

public struct Shop: Codable, Equatable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let region: String

    public init(id: String, name: String, region: String) {
        self.id = id
        self.name = name
        self.region = region
    }
}
