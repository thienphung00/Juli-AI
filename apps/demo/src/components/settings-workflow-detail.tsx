"use client";

import {
  Badge,
  Button,
  ConfirmDialog,
  Form,
  FormActions,
  FormSubmit,
  PageHeader,
  TextField,
} from "@juli/ui";
import { formatDateTime } from "@juli/utils";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import {
  buildSettingsFieldStorageKey,
  formatAllowedRange,
  getEffectiveSettingsValue,
  getWorkflowTemplate,
  persistSettingsSave,
  validateSettingsField,
} from "../lib/settings";
import { useDemoState } from "./demo-state";

export function SettingsWorkflowDetail() {
  const params = useParams<{ workflowKey: string }>();
  const router = useRouter();
  const workflowKey = params.workflowKey;
  const template = getWorkflowTemplate(workflowKey);
  const { mutableState, updateMutableState } = useDemoState();
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const [leaveDialogOpen, setLeaveDialogOpen] = useState(false);

  const fieldValues = useMemo(() => {
    if (!template) {
      return {};
    }

    const values: Record<string, string> = {};

    for (const field of template.fields) {
      const storageKey = buildSettingsFieldStorageKey(workflowKey, field.key);
      values[storageKey] = getEffectiveSettingsValue(
        field,
        mutableState.settingsDraft,
        mutableState.settingsSaved,
        storageKey,
      );
    }

    return values;
  }, [mutableState.settingsDraft, mutableState.settingsSaved, template, workflowKey]);

  const hasUnsavedChanges = useMemo(() => {
    if (!template) {
      return false;
    }

    return template.fields.some((field) => {
      const storageKey = buildSettingsFieldStorageKey(workflowKey, field.key);
      const current = fieldValues[storageKey] ?? field.defaultValue;
      const saved =
        mutableState.settingsSaved[storageKey] ?? field.defaultValue;

      return current !== saved;
    });
  }, [fieldValues, mutableState.settingsSaved, template, workflowKey]);

  const handleChange = useCallback(
    (storageKey: string, value: string) => {
      setSavedMessage(null);
      setSaveError(null);
      setFieldErrors((current) => {
        const next = { ...current };
        delete next[storageKey];
        return next;
      });

      updateMutableState((current) => ({
        ...current,
        settingsDraft: {
          ...current.settingsDraft,
          [storageKey]: value,
        },
      }));
    },
    [updateMutableState],
  );

  const discardChanges = useCallback(() => {
    if (!template) {
      return;
    }

    updateMutableState((current) => {
      const nextDraft = { ...current.settingsDraft };

      for (const field of template.fields) {
        delete nextDraft[buildSettingsFieldStorageKey(workflowKey, field.key)];
      }

      return {
        ...current,
        settingsDraft: nextDraft,
      };
    });
    setFieldErrors({});
    setSaveError(null);
    setSavedMessage(null);
  }, [template, updateMutableState, workflowKey]);

  const commitSave = async () => {
    if (!template) {
      return;
    }

    setSaveError(null);
    setSavedMessage(null);

    const nextErrors: Record<string, string> = {};

    for (const field of template.fields) {
      if (!field.editable) {
        continue;
      }

      const storageKey = buildSettingsFieldStorageKey(workflowKey, field.key);
      const value = fieldValues[storageKey] ?? field.defaultValue;
      const error = validateSettingsField(field, value);

      if (error) {
        nextErrors[storageKey] = error;
      }
    }

    if (Object.keys(nextErrors).length > 0) {
      setFieldErrors(nextErrors);
      return;
    }

    setFieldErrors({});
    setIsSaving(true);

    try {
      await persistSettingsSave();

      const committed = { ...mutableState.settingsSaved };

      for (const field of template.fields) {
        const storageKey = buildSettingsFieldStorageKey(workflowKey, field.key);
        committed[storageKey] = fieldValues[storageKey] ?? field.defaultValue;
      }

      const nextDraft = { ...mutableState.settingsDraft };
      for (const field of template.fields) {
        delete nextDraft[buildSettingsFieldStorageKey(workflowKey, field.key)];
      }

      updateMutableState((current) => ({
        ...current,
        settingsDraft: nextDraft,
        settingsSaved: committed,
        settingsLastSavedAt: new Date().toISOString(),
      }));
      setSavedMessage(`Đã lưu mẫu quy trình ${template.displayName}.`);
    } catch {
      setSaveError("Không thể lưu cài đặt. Vui lòng thử lại.");
    } finally {
      setIsSaving(false);
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await commitSave();
  };

  const handleBackClick = (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (!hasUnsavedChanges) {
      return;
    }

    event.preventDefault();
    setLeaveDialogOpen(true);
  };

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
    <section className="settings-detail">
      <PageHeader
        subtitle="Chỉnh sửa mặc định và ngưỡng cho mẫu quy trình này. Thay đổi không phê duyệt đề xuất hiện có."
        title={template.displayName}
      />

      <p className="settings-detail__meta">
        <code>{template.workflowKey}</code>
        <span aria-hidden="true"> · </span>
        <span>{template.toolName}</span>
        <Badge variant="capability">{template.capabilityBadge}</Badge>
      </p>

      <Link
        className="settings-detail__back"
        href="/settings"
        onClick={handleBackClick}
      >
        Về Cài đặt
      </Link>

      {saveError ? (
        <p className="settings-feedback settings-feedback--error" role="alert">
          {saveError}{" "}
          <Button onClick={() => void commitSave()} variant="secondary">
            Thử lại
          </Button>
        </p>
      ) : null}

      {savedMessage ? (
        <p
          aria-label="Xác nhận đã lưu"
          aria-live="polite"
          className="settings-feedback settings-feedback--success"
          role="status"
        >
          {savedMessage}
          {mutableState.settingsLastSavedAt
            ? ` Cập nhật lần cuối: ${formatDateTime(mutableState.settingsLastSavedAt)}.`
            : null}
        </p>
      ) : null}

      <Form className="settings-form" onSubmit={(event) => void handleSubmit(event)}>
        {template.fields.map((field) => {
          const storageKey = buildSettingsFieldStorageKey(workflowKey, field.key);
          const value = fieldValues[storageKey] ?? field.defaultValue;

          return (
            <div className="settings-field" key={field.key}>
              <TextField
                disabled={isSaving}
                errorMessage={fieldErrors[storageKey]}
                helperText={
                  field.helperText
                    ? `${formatAllowedRange(field)} ${field.helperText}`
                    : formatAllowedRange(field)
                }
                id={`settings-${storageKey}`}
                inputMode="decimal"
                label={`${field.label}${field.unit ? ` (${field.unit})` : ""}`}
                onChange={(event) => handleChange(storageKey, event.target.value)}
                value={value}
              />
            </div>
          );
        })}

        {template.fbtFields.map((field) => (
          <div className="settings-field settings-field--readonly" key={field.key}>
            <TextField
              helperText={
                field.unresolvedReason ??
                "Chưa xác định — không thể chỉnh sửa."
              }
              id={`settings-fbt-${field.key}`}
              label={field.label}
              readOnly
              value="Chưa xác định"
            />
            <Badge variant="info">Chưa xác định</Badge>
          </div>
        ))}

        <FormActions className="settings-detail__actions">
          <Button
            disabled={isSaving || !hasUnsavedChanges}
            onClick={discardChanges}
            type="button"
            variant="secondary"
          >
            Huỷ bỏ thay đổi
          </Button>
          <FormSubmit disabled={isSaving || !hasUnsavedChanges} loading={isSaving}>
            Lưu
          </FormSubmit>
        </FormActions>
      </Form>

      <ConfirmDialog
        cancelLabel="Tiếp tục chỉnh sửa"
        confirmLabel="Huỷ bỏ thay đổi"
        description="Bạn có thay đổi chưa lưu cho mẫu quy trình này. Huỷ bỏ sẽ trả về giá trị đã lưu gần nhất."
        onConfirm={() => {
          discardChanges();
          router.push("/settings");
        }}
        onOpenChange={setLeaveDialogOpen}
        open={leaveDialogOpen}
        title="Thay đổi chưa lưu"
      />
    </section>
  );
}
