"use client";

import { PageHeader } from "@juli/ui";
import Link from "next/link";
import { useParams } from "next/navigation";

import { getWorkflowTemplate } from "../lib/settings";
import {
  SETTINGS_WORKFLOW_DETAIL_VISITOR_PLACEHOLDER,
} from "./settings-view";

export function SettingsWorkflowDetail() {
  const params = useParams<{ workflowKey: string }>();
  const workflowKey = params.workflowKey;
  const template = getWorkflowTemplate(workflowKey);

  if (!template) {
    return (
      <section className="demo-placeholder" role="status">
        <p className="demo-kicker">Không tìm thấy</p>
        <h1>Mẫu quy trình không tồn tại</h1>
        <p>workflow_key này chưa có trong Demo.</p>
        <Link className="demo-placeholder__recovery" href="/settings">
          Về Cài đặt
        </Link>
      </section>
    );
  }

  return (
    <section
      aria-labelledby="settings-workflow-detail-title"
      className="settings-detail settings-detail--visitor-disabled"
      role="status"
    >
      <PageHeader
        subtitle="Chỉnh sửa mặc định và ngưỡng cho mẫu quy trình này. Thay đổi không phê duyệt đề xuất hiện có."
        title={template.displayName}
      />

      <p className="settings-detail__visitor-notice">
        {SETTINGS_WORKFLOW_DETAIL_VISITOR_PLACEHOLDER}
      </p>

      <Link className="settings-detail__back" href="/settings">
        Về Cài đặt
      </Link>
    </section>
  );
}
