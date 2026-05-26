// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "JuliAI",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "JuliKit", targets: ["JuliKit"]),
    ],
    targets: [
        .target(
            name: "JuliKit",
            path: "Sources/JuliKit"
        ),
        .testTarget(
            name: "JuliKitTests",
            dependencies: ["JuliKit"],
            path: "Tests/JuliKitTests"
        ),
    ]
)
