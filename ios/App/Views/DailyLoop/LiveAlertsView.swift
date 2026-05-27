import SwiftUI
import JuliKit

struct LiveAlertsView: View {
    @Bindable var store: LiveAlertsStore

    var body: some View {
        ZStack(alignment: .top) {
            VStack(spacing: 16) {
                HStack {
                    Label("Đang Live", systemImage: "video")
                        .font(.headline)
                    Spacer()
                    Button("Xoá") {
                        Task { @MainActor in store.clear() }
                    }
                    .font(.callout)
                    .disabled(store.recent.isEmpty)
                }
                .padding(.horizontal, 16)
                .padding(.top, 12)

                if store.recent.isEmpty {
                    PlaceholderTabView(
                        icon: "bolt.horizontal.circle",
                        title: "Chưa có cảnh báo",
                        subtitle: "Khi có giảm người xem hoặc sắp hết hàng, cảnh báo sẽ hiển thị ở đây theo thời gian thực.",
                        color: .red
                    )
                } else {
                    List {
                        ForEach(store.recent) { event in
                            VStack(alignment: .leading, spacing: 6) {
                                Text(event.title)
                                    .font(.headline)
                                Text(event.message)
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                            .padding(.vertical, 6)
                        }
                    }
                    .listStyle(.plain)
                }
            }
        }
    }
}
