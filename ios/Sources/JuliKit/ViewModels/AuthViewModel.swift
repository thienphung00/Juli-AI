import Foundation
import os
#if canImport(Observation)
import Observation
#endif

private let logger = Logger(subsystem: "com.juli.ai", category: "AuthViewModel")

public enum AuthState: Equatable, Sendable {
    case idle
    case sendingOTP
    case awaitingOTP
    case verifyingOTP
    case authenticated(AuthSession)
    case error(String)
}

@Observable
public final class AuthViewModel: @unchecked Sendable {
    public private(set) var state: AuthState = .idle
    public var phoneNumber: String = ""
    public var otpCode: String = ""

    private let authService: AuthServiceProtocol

    public init(authService: AuthServiceProtocol) {
        self.authService = authService
    }

    @MainActor
    public func sendOTP() async {
        state = .sendingOTP
        do {
            try await authService.sendOTP(phone: phoneNumber)
            state = .awaitingOTP
        } catch let error as AuthError {
            state = .error(errorMessage(for: error))
        } catch {
            state = .error(error.localizedDescription)
        }
    }

    @MainActor
    public func verifyOTP() async {
        state = .verifyingOTP
        do {
            let session = try await authService.verifyOTP(phone: phoneNumber, code: otpCode)
            state = .authenticated(session)
        } catch let error as AuthError {
            state = .error(errorMessage(for: error))
        } catch {
            state = .error(error.localizedDescription)
        }
    }

    @MainActor
    public func restoreSession() async {
        do {
            if let session = try await authService.restoreSession() {
                state = .authenticated(session)
            }
        } catch {
            logger.error("Failed to restore session: \(error.localizedDescription, privacy: .public)")
            state = .idle
        }
    }

    @MainActor
    public func logout() async {
        do {
            try await authService.logout()
        } catch {
            logger.warning("Logout cleanup failed: \(error.localizedDescription, privacy: .public)")
        }
        state = .idle
        phoneNumber = ""
        otpCode = ""
    }

    private func errorMessage(for error: AuthError) -> String {
        switch error {
        case .invalidPhoneNumber:
            return "Số điện thoại không hợp lệ. Vui lòng nhập số +84."
        case .otpVerificationFailed:
            return "Mã OTP không đúng. Vui lòng thử lại."
        case .networkError:
            return "Lỗi kết nối. Vui lòng kiểm tra mạng."
        case .sessionExpired:
            return "Phiên đã hết hạn. Vui lòng đăng nhập lại."
        case .noSession:
            return "Không có phiên đăng nhập."
        }
    }
}
