import SwiftUI

struct LoginView: View {
    @Bindable var viewModel: AuthViewModel

    var body: some View {
        NavigationStack {
            VStack(spacing: 32) {
                Spacer()

                VStack(spacing: 12) {
                    Image(systemName: "storefront")
                        .font(.system(size: 64))
                        .foregroundStyle(.blue)

                    Text("Juli AI")
                        .font(.largeTitle.bold())

                    Text("Quản lý TikTok Shop thông minh")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                VStack(spacing: 16) {
                    switch viewModel.state {
                    case .idle, .sendingOTP, .error:
                        phoneInputSection

                    case .awaitingOTP, .verifyingOTP:
                        otpInputSection

                    case .authenticated:
                        EmptyView()
                    }
                }
                .padding(.horizontal, 24)

                if case .error(let message) = viewModel.state {
                    Text(message)
                        .font(.callout)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 24)
                }

                Spacer()
                Spacer()
            }
            .navigationBarHidden(true)
        }
    }

    private var phoneInputSection: some View {
        VStack(spacing: 16) {
            HStack {
                Text("🇻🇳 +84")
                    .font(.body.monospaced())
                    .padding(.horizontal, 12)
                    .padding(.vertical, 14)
                    .background(.quaternary)
                    .clipShape(RoundedRectangle(cornerRadius: 10))

                TextField("Số điện thoại", text: $viewModel.phoneNumber)
                    .keyboardType(.phonePad)
                    .textContentType(.telephoneNumber)
                    .padding(14)
                    .background(.quaternary)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
            }

            Button {
                Task { await viewModel.sendOTP() }
            } label: {
                Group {
                    if viewModel.state == .sendingOTP {
                        ProgressView()
                            .tint(.white)
                    } else {
                        Text("Gửi mã OTP")
                    }
                }
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
            }
            .buttonStyle(.borderedProminent)
            .disabled(viewModel.phoneNumber.isEmpty || viewModel.state == .sendingOTP)
        }
    }

    private var otpInputSection: some View {
        VStack(spacing: 16) {
            Text("Nhập mã OTP đã gửi đến\n\(viewModel.phoneNumber)")
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            TextField("Mã OTP", text: $viewModel.otpCode)
                .keyboardType(.numberPad)
                .textContentType(.oneTimeCode)
                .multilineTextAlignment(.center)
                .font(.title2.monospaced())
                .padding(14)
                .background(.quaternary)
                .clipShape(RoundedRectangle(cornerRadius: 10))

            Button {
                Task { await viewModel.verifyOTP() }
            } label: {
                Group {
                    if viewModel.state == .verifyingOTP {
                        ProgressView()
                            .tint(.white)
                    } else {
                        Text("Xác nhận")
                    }
                }
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
            }
            .buttonStyle(.borderedProminent)
            .disabled(viewModel.otpCode.count < 6 || viewModel.state == .verifyingOTP)

            Button("Đổi số điện thoại") {
                viewModel.otpCode = ""
                Task { await viewModel.logout() }
            }
            .font(.callout)
        }
    }
}
