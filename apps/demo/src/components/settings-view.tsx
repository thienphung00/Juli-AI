"use client";

import { useDemoState } from "./demo-state";

export const SETTINGS_VISITOR_PLACEHOLDER =
  "Mẫu quy trình và ngưỡng yêu cầu Sign-in. Bạn vẫn có thể khám phá toàn bộ Demo bằng dữ liệu mẫu.";

export const SETTINGS_WORKFLOW_DETAIL_VISITOR_PLACEHOLDER =
  "Chỉnh sửa mẫu quy trình yêu cầu Sign-in. Bạn vẫn có thể khám phá toàn bộ Demo bằng dữ liệu mẫu.";

export function SettingsView() {
  const { requestSignIn } = useDemoState();

  return (
    <section aria-labelledby="settings-title" className="settings-view">
      <p className="demo-kicker">Cài đặt</p>
      <h1 className="demo-title" id="settings-title">
        Cài đặt
      </h1>
      <p className="demo-intro">
        Mẫu quy trình và ngưỡng ảnh hưởng đến đề xuất trong tương lai — không
        thay thế việc phê duyệt tại Quyết định.
      </p>

      <div
        aria-label="Phần cài đặt"
        className="settings-view__tabs"
        role="tablist"
      >
        <button
          aria-disabled="true"
          aria-selected="true"
          className="settings-view__tab"
          id="settings-tab-templates"
          onClick={requestSignIn}
          role="tab"
          type="button"
        >
          Mẫu quy trình
        </button>
        <button
          aria-disabled="true"
          aria-selected="false"
          className="settings-view__tab"
          id="settings-tab-thresholds"
          onClick={requestSignIn}
          role="tab"
          type="button"
        >
          Ngưỡng
        </button>
      </div>

      <div
        aria-labelledby="settings-tab-templates"
        className="settings-view__placeholder"
        id="settings-visitor-panel"
        role="tabpanel"
      >
        <p className="settings-view__visitor-notice" role="status">
          {SETTINGS_VISITOR_PLACEHOLDER}
        </p>
      </div>
    </section>
  );
}
