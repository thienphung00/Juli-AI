"use client";

import {
  Badge,
  Button,
  Form,
  FormActions,
  FormSubmit,
  TextField,
} from "@juli/ui";
import { formatDateTime } from "@juli/utils";
import { useCallback, useMemo, useState } from "react";

import {
  buildThresholdStorageKey,
  formatAllowedRange,
  getEffectiveSettingsValue,
  persistSettingsSave,
  thresholdFixtures,
  validateSettingsField,
} from "../lib/settings";
import { useDemoState } from "./demo-state";

export function SettingsThresholdsPanel() {
  const { mutableState, updateMutableState } = useDemoState();
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  const draftValues = useMemo(() => {
    const values: Record<string, string> = {};

    for (const threshold of thresholdFixtures) {
      const storageKey = buildThresholdStorageKey(threshold.key);
      values[storageKey] = getEffectiveSettingsValue(
        threshold,
        mutableState.settingsDraft,
        mutableState.settingsSaved,
        storageKey,
      );
    }

    return values;
  }, [mutableState.settingsDraft, mutableState.settingsSaved]);

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

  const commitSave = useCallback(async () => {
    setSaveError(null);
    setSavedMessage(null);

    const nextErrors: Record<string, string> = {};

    for (const threshold of thresholdFixtures) {
      if (!threshold.editable) {
        continue;
      }

      const storageKey = buildThresholdStorageKey(threshold.key);
      const value = draftValues[storageKey] ?? threshold.defaultValue;
      const error = validateSettingsField(threshold, value);

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

      for (const threshold of thresholdFixtures) {
        if (!threshold.editable) {
          continue;
        }

        const storageKey = buildThresholdStorageKey(threshold.key);
        committed[storageKey] = draftValues[storageKey] ?? threshold.defaultValue;
      }

      const nextDraft = { ...mutableState.settingsDraft };
      for (const threshold of thresholdFixtures) {
        delete nextDraft[buildThresholdStorageKey(threshold.key)];
      }

      updateMutableState((current) => ({
        ...current,
        settingsDraft: nextDraft,
        settingsSaved: committed,
        settingsLastSavedAt: new Date().toISOString(),
      }));
      setSavedMessage("Đã lưu ngưỡng toàn shop.");
    } catch {
      setSaveError("Không thể lưu cài đặt. Vui lòng thử lại.");
    } finally {
      setIsSaving(false);
    }
  }, [draftValues, mutableState.settingsDraft, mutableState.settingsSaved, updateMutableState]);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await commitSave();
  };

  return (
    <section
      aria-labelledby="settings-thresholds-title"
      className="settings-thresholds"
    >
      <h2 id="settings-thresholds-title">Ngưỡng</h2>
      <p className="settings-thresholds__intro">
        Thay đổi ngưỡng chỉ ảnh hưởng đề xuất trong tương lai — không phê duyệt
        hay thực thi quyết định hiện có.
      </p>

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
        {thresholdFixtures.map((threshold) => {
          const storageKey = buildThresholdStorageKey(threshold.key);
          const value = draftValues[storageKey] ?? threshold.defaultValue;

          if (!threshold.editable || threshold.unresolved) {
            return (
              <div className="settings-field settings-field--readonly" key={threshold.key}>
                <TextField
                  helperText={
                    threshold.unresolvedReason ??
                    "Chưa xác định — không thể chỉnh sửa."
                  }
                  id={`threshold-${threshold.key}`}
                  label={threshold.label}
                  readOnly
                  value={threshold.unresolved ? "Chưa xác định" : value}
                />
                <Badge variant="info">Chưa xác định</Badge>
                <p className="settings-field__impact">
                  Ảnh hưởng: {threshold.affectedWorkflowKeys.join(", ")}
                </p>
              </div>
            );
          }

          return (
            <div className="settings-field" key={threshold.key}>
              <TextField
                errorMessage={fieldErrors[storageKey]}
                helperText={`${formatAllowedRange(threshold)} Ảnh hưởng: ${threshold.affectedWorkflowKeys.join(", ")}.`}
                id={`threshold-${threshold.key}`}
                inputMode="decimal"
                label={`${threshold.label}${threshold.unit ? ` (${threshold.unit})` : ""}`}
                onChange={(event) => handleChange(storageKey, event.target.value)}
                value={value}
              />
            </div>
          );
        })}

        <FormActions>
          <FormSubmit disabled={isSaving} loading={isSaving}>
            Lưu ngưỡng
          </FormSubmit>
        </FormActions>
      </Form>
    </section>
  );
}
