import SwiftUI

struct ShopSelectionSheet: View {
    let shops: [Shop]
    let selectedShop: Shop?
    let onSelect: (Shop) -> Void

    var body: some View {
        NavigationStack {
            List(shops) { shop in
                Button {
                    onSelect(shop)
                } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(shop.name)
                                .font(.body)
                                .foregroundStyle(.primary)
                            Text(shop.region)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }

                        Spacer()

                        if shop.id == selectedShop?.id {
                            Image(systemName: "checkmark")
                                .foregroundStyle(.blue)
                        }
                    }
                }
            }
            .navigationTitle("Chọn Shop")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}
