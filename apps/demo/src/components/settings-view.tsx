"use client";

import { useId, useState } from "react";

import { useDemoState } from "./demo-state";
import { SettingsThresholdsPanel } from "./settings-thresholds-panel";
import { SettingsWorkflowList } from "./settings-workflow-list";

type SettingsSection = "templates" | "thresholds";

export function SettingsView() {
  const { mutableState, updateMutableState } = useDemoState();
  const templatesPanelId = useId();
  const thresholdsPanelId = useId();
  const activeSection: SettingsSection =
    mutableState.settingsActiveSection ?? "templates";

  const handleSelectSection = (section: SettingsSection) => {
    updateMutableState((current) => ({
      ...current,
      settingsActiveSection: section,
    }));
  };

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
          aria-controls={templatesPanelId}
          aria-selected={activeSection === "templates"}
          className="settings-view__tab"
          id="settings-tab-templates"
          onClick={() => handleSelectSection("templates")}
          role="tab"
          type="button"
        >
          Mẫu quy trình
        </button>
        <button
          aria-controls={thresholdsPanelId}
          aria-selected={activeSection === "thresholds"}
          className="settings-view__tab"
          id="settings-tab-thresholds"
          onClick={() => handleSelectSection("thresholds")}
          role="tab"
          type="button"
        >
          Ngưỡng
        </button>
      </div>

      <div
        aria-labelledby="settings-tab-templates"
        hidden={activeSection !== "templates"}
        id={templatesPanelId}
        role="tabpanel"
      >
        <SettingsWorkflowList />
      </div>

      <div
        aria-labelledby="settings-tab-thresholds"
        hidden={activeSection !== "thresholds"}
        id={thresholdsPanelId}
        role="tabpanel"
      >
        <SettingsThresholdsPanel />
      </div>
    </section>
  );
}
