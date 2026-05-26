import SwiftUI

/// AC3 — Morning screen placeholder: profit summary + low-stock alerts
/// Full implementation lands in a future slice once API endpoints for
/// orders/products/inventory are wired to the iOS client.
struct MorningSummaryView: View {
    let shopName: String

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                headerSection
                profitPlaceholder
                alertsPlaceholder
            }
            .padding()
        }
    }

    private var headerSection: some View {
        VStack(spacing: 4) {
            Text("Chào buổi sáng ☀️")
                .font(.title2.bold())
            Text(shopName)
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 8)
    }

    private var profitPlaceholder: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Lợi nhuận hôm qua", systemImage: "chart.line.uptrend.xyaxis")
                .font(.headline)

            RoundedRectangle(cornerRadius: 12)
                .fill(.quaternary)
                .frame(height: 120)
                .overlay {
                    VStack(spacing: 8) {
                        Image(systemName: "chart.bar.fill")
                            .font(.title)
                            .foregroundStyle(.secondary)
                        Text("Dữ liệu sẽ hiển thị ở đây")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                    }
                }
        }
    }

    private var alertsPlaceholder: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Cảnh báo tồn kho", systemImage: "exclamationmark.triangle")
                .font(.headline)

            RoundedRectangle(cornerRadius: 12)
                .fill(.quaternary)
                .frame(height: 80)
                .overlay {
                    VStack(spacing: 8) {
                        Image(systemName: "shippingbox.fill")
                            .font(.title2)
                            .foregroundStyle(.secondary)
                        Text("Chưa có cảnh báo")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                    }
                }
        }
    }
}
