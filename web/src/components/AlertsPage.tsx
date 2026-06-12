"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, type AlertHistoryItem, type AlertRuleInput } from "@/lib/api-client";
import { formatDateTime } from "@/lib/format";
import { AuthenticatedShell } from "./AuthenticatedShell";

type Tab = "config" | "history";

type ThresholdModel =
  | { kind: "inventory_low_stock"; days_until_depletion: string }
  | { kind: "velocity_spike"; velocity_change_pct: string }
  | { kind: "gmv_drop"; gmv_drop_pct: string }
  | { kind: "generic"; value: string };

type RuleDraft = {
  id: string;
  alert_type: ThresholdModel["kind"];
  channel: "fcm";
  is_active: boolean;
  cooldown_seconds: string;
  threshold: ThresholdModel;
};

const ALERT_TYPE_OPTIONS: Array<{ value: RuleDraft["alert_type"]; label: string }> = [
  { value: "inventory_low_stock", label: "Tồn kho sắp hết" },
  { value: "velocity_spike", label: "Tốc độ bán tăng bất thường" },
  { value: "gmv_drop", label: "GMV giảm mạnh" },
  { value: "generic", label: "Khác" },
];

function makeDraft(seed?: Partial<RuleDraft>): RuleDraft {
  const id = seed?.id ?? `rule-${Math.random().toString(16).slice(2)}`;
  const alert_type = seed?.alert_type ?? "inventory_low_stock";
  const threshold: ThresholdModel =
    seed?.threshold ??
    (alert_type === "inventory_low_stock"
      ? { kind: "inventory_low_stock", days_until_depletion: "7" }
      : alert_type === "velocity_spike"
        ? { kind: "velocity_spike", velocity_change_pct: "30" }
        : alert_type === "gmv_drop"
          ? { kind: "gmv_drop", gmv_drop_pct: "20" }
          : { kind: "generic", value: "1" });

  return {
    id,
    alert_type,
    channel: "fcm",
    is_active: seed?.is_active ?? true,
    cooldown_seconds: seed?.cooldown_seconds ?? "3600",
    threshold,
  };
}

function thresholdToJson(threshold: ThresholdModel): Record<string, unknown> | null {
  switch (threshold.kind) {
    case "inventory_low_stock": {
      const days = Number(threshold.days_until_depletion);
      if (!Number.isFinite(days) || days <= 0) return null;
      return { days_until_depletion: days };
    }
    case "velocity_spike": {
      const pct = Number(threshold.velocity_change_pct);
      if (!Number.isFinite(pct) || pct <= 0) return null;
      return { velocity_change_pct: pct };
    }
    case "gmv_drop": {
      const pct = Number(threshold.gmv_drop_pct);
      if (!Number.isFinite(pct) || pct <= 0) return null;
      return { gmv_drop_pct: pct };
    }
    case "generic": {
      const value = Number(threshold.value);
      if (!Number.isFinite(value)) return null;
      return { value };
    }
  }
}

export function AlertsPage() {
  const [tab, setTab] = useState<Tab>("config");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);
  const [rules, setRules] = useState<RuleDraft[]>(() => [
    makeDraft({ alert_type: "inventory_low_stock" }),
    makeDraft({ alert_type: "velocity_spike" }),
  ]);

  const [history, setHistory] = useState<AlertHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const rulesPayload: AlertRuleInput[] = useMemo(() => {
    return rules.map((r) => ({
      alert_type: r.alert_type,
      channel: r.channel,
      is_active: r.is_active,
      cooldown_seconds: Number(r.cooldown_seconds || "3600"),
      threshold: thresholdToJson(r.threshold),
    }));
  }, [rules]);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const res = await api.alerts.history({ limit: 50 });
      setHistory(res.items ?? []);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setHistory([]);
      } else {
        setHistoryError("Không thể tải lịch sử cảnh báo. Vui lòng thử lại.");
      }
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === "history") {
      loadHistory();
    }
  }, [tab, loadHistory]);

  const onSave = async () => {
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(null);
    try {
      await api.alerts.upsertConfig(rulesPayload);
      setSaveSuccess("Đã lưu cấu hình cảnh báo");
    } catch {
      setSaveError("Không thể lưu cấu hình. Vui lòng thử lại.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <AuthenticatedShell title="Cảnh báo">
      <div className="mb-4 flex items-center gap-2">
        <TabButton active={tab === "config"} onClick={() => setTab("config")}>
          Cấu hình
        </TabButton>
        <TabButton active={tab === "history"} onClick={() => setTab("history")}>
          Lịch sử
        </TabButton>
      </div>
        {tab === "config" ? (
          <section data-testid="alerts-config">
            <p className="mb-3 text-sm" style={{ color: "var(--muted-foreground)" }}>
              Tuỳ chỉnh ngưỡng theo từng loại cảnh báo cho shop hiện tại.
            </p>

            {saveError && (
              <p role="alert" className="mb-4 rounded-xl p-3 text-sm" style={{ background: "#ef444420", color: "#ef4444" }}>
                {saveError}
              </p>
            )}
            {saveSuccess && (
              <p role="status" className="mb-4 rounded-xl p-3 text-sm" style={{ background: "#10b98120", color: "#10b981" }}>
                {saveSuccess}
              </p>
            )}

            <div className="space-y-3" data-testid="alerts-rule-builder">
              {rules.map((rule, idx) => (
                <RuleCard
                  key={rule.id}
                  rule={rule}
                  index={idx}
                  onChange={(next) =>
                    setRules((prev) =>
                      prev.map((r) => (r.id === rule.id ? next : r))
                    )
                  }
                  onRemove={() => setRules((prev) => prev.filter((r) => r.id !== rule.id))}
                />
              ))}
            </div>

            <div className="mt-4 flex gap-2">
              <button
                type="button"
                className="flex-1 rounded-xl px-3 py-2.5 text-sm font-semibold"
                style={{ background: "var(--muted)", border: "1px solid var(--border)", color: "var(--foreground)" }}
                onClick={() => setRules((prev) => [...prev, makeDraft()])}
                data-testid="add-alert-rule"
              >
                + Thêm rule
              </button>
              <button
                type="button"
                className="flex-1 rounded-xl px-3 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
                style={{ background: "var(--brand-gradient)" }}
                onClick={onSave}
                disabled={saving || rules.length === 0}
                data-testid="save-alert-config"
              >
                {saving ? "Đang lưu..." : "Lưu cấu hình"}
              </button>
            </div>
          </section>
        ) : (
          <section data-testid="alerts-history">
            {historyError && (
              <p role="alert" className="mb-4 rounded-xl p-3 text-sm" style={{ background: "#ef444420", color: "#ef4444" }}>
                {historyError}
              </p>
            )}

            {historyLoading ? (
              <div className="flex justify-center py-12">
                <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
              </div>
            ) : history.length === 0 ? (
              <div className="py-12 text-center" data-testid="alerts-history-empty">
                <p className="text-lg font-medium" style={{ color: "var(--muted-foreground)" }}>
                  Chưa có cảnh báo nào
                </p>
                <p className="mt-1 text-sm" style={{ color: "var(--muted-foreground)", opacity: 0.6 }}>
                  Lịch sử sẽ hiển thị khi rule được kích hoạt
                </p>
              </div>
            ) : (
              <div className="space-y-3" data-testid="alerts-history-list">
                {history.map((item) => (
                  <HistoryCard key={item.id} item={item} />
                ))}
              </div>
            )}
          </section>
        )}
    </AuthenticatedShell>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className="rounded-xl px-3 py-2 text-xs font-semibold"
      style={
        active
          ? { background: "var(--muted)", border: "1px solid var(--border)", color: "var(--foreground)" }
          : { background: "transparent", border: "1px solid transparent", color: "var(--muted-foreground)" }
      }
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function RuleCard({
  rule,
  index,
  onChange,
  onRemove,
}: {
  rule: RuleDraft;
  index: number;
  onChange: (next: RuleDraft) => void;
  onRemove: () => void;
}) {
  const updateThresholdKind = (kind: RuleDraft["alert_type"]) => {
    const next = makeDraft({
      id: rule.id,
      alert_type: kind,
      is_active: rule.is_active,
      cooldown_seconds: rule.cooldown_seconds,
    });
    onChange(next);
  };

  return (
    <div className="card p-4" data-testid="alert-rule-card">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-semibold">Rule #{index + 1}</p>
        <button
          type="button"
          className="rounded-lg px-2 py-1 text-xs font-semibold"
          style={{ background: "#ef444420", color: "#ef4444" }}
          onClick={onRemove}
          aria-label={`Xoá rule ${index + 1}`}
        >
          Xoá
        </button>
      </div>

      <div className="mt-3 space-y-3">
        <label className="block text-xs font-medium" style={{ color: "var(--muted-foreground)" }}>
          Loại cảnh báo
          <select
            aria-label={`Loại cảnh báo ${index + 1}`}
            className="mt-1 w-full rounded-xl px-3 py-2.5 text-sm focus:outline-none"
            style={{ background: "var(--muted)", border: "1px solid var(--border)", color: "var(--foreground)" }}
            value={rule.alert_type}
            onChange={(e) => updateThresholdKind(e.target.value as RuleDraft["alert_type"])}
          >
            {ALERT_TYPE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value} style={{ background: "var(--card)" }}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>

        <div className="grid grid-cols-2 gap-2">
          <label className="block text-xs font-medium" style={{ color: "var(--muted-foreground)" }}>
            Bật/Tắt
            <div className="mt-1 flex items-center gap-2 rounded-xl px-3 py-2.5" style={{ background: "var(--muted)", border: "1px solid var(--border)" }}>
              <input
                aria-label={`Kích hoạt rule ${index + 1}`}
                type="checkbox"
                checked={rule.is_active}
                onChange={(e) => onChange({ ...rule, is_active: e.target.checked })}
              />
              <span className="text-sm" style={{ color: "var(--foreground)" }}>
                {rule.is_active ? "Đang bật" : "Đang tắt"}
              </span>
            </div>
          </label>

          <label className="block text-xs font-medium" style={{ color: "var(--muted-foreground)" }}>
            Cooldown (giây)
            <input
              aria-label={`Cooldown rule ${index + 1}`}
              inputMode="numeric"
              className="mt-1 w-full rounded-xl px-3 py-2.5 text-sm focus:outline-none"
              style={{ background: "var(--muted)", border: "1px solid var(--border)", color: "var(--foreground)" }}
              value={rule.cooldown_seconds}
              onChange={(e) => onChange({ ...rule, cooldown_seconds: e.target.value })}
            />
          </label>
        </div>

        <ThresholdEditor
          model={rule.threshold}
          index={index}
          onChange={(threshold) => onChange({ ...rule, threshold })}
        />
      </div>
    </div>
  );
}

function ThresholdEditor({
  model,
  index,
  onChange,
}: {
  model: ThresholdModel;
  index: number;
  onChange: (next: ThresholdModel) => void;
}) {
  const label =
    model.kind === "inventory_low_stock"
      ? "Ngưỡng (ngày tới hết hàng)"
      : model.kind === "velocity_spike"
        ? "Ngưỡng (% tăng tốc độ bán)"
        : model.kind === "gmv_drop"
          ? "Ngưỡng (% giảm GMV)"
          : "Ngưỡng (giá trị)";

  const value =
    model.kind === "inventory_low_stock"
      ? model.days_until_depletion
      : model.kind === "velocity_spike"
        ? model.velocity_change_pct
        : model.kind === "gmv_drop"
          ? model.gmv_drop_pct
          : model.value;

  const setValue = (nextValue: string) => {
    if (model.kind === "inventory_low_stock") onChange({ ...model, days_until_depletion: nextValue });
    else if (model.kind === "velocity_spike") onChange({ ...model, velocity_change_pct: nextValue });
    else if (model.kind === "gmv_drop") onChange({ ...model, gmv_drop_pct: nextValue });
    else onChange({ ...model, value: nextValue });
  };

  return (
    <label className="block text-xs font-medium" style={{ color: "var(--muted-foreground)" }}>
      {label}
      <input
        aria-label={`Ngưỡng rule ${index + 1}`}
        inputMode="numeric"
        className="mt-1 w-full rounded-xl px-3 py-2.5 text-sm focus:outline-none"
        style={{ background: "var(--muted)", border: "1px solid var(--border)", color: "var(--foreground)" }}
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
    </label>
  );
}

function HistoryCard({ item }: { item: AlertHistoryItem }) {
  return (
    <div className="card p-4" data-testid="alert-history-card">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{toAlertLabel(item.alert_type)}</p>
          <p className="mt-0.5 text-xs" style={{ color: "var(--muted-foreground)" }}>
            {formatDateTime(item.triggered_at)}
          </p>
        </div>
        <span className="badge" style={statusStyle(item.status)}>
          {toStatusLabel(item.status)}
        </span>
      </div>

      <div className="mt-2 flex items-center justify-between" style={{ borderTop: "1px solid var(--border)", paddingTop: "10px", marginTop: "10px" }}>
        <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>
          Kênh: {item.channel.toUpperCase()}
        </p>
        <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>
          #{item.id.slice(0, 8)}
        </p>
      </div>
    </div>
  );
}

function toAlertLabel(alertType: string): string {
  const map: Record<string, string> = {
    inventory_low_stock: "Tồn kho sắp hết",
    velocity_spike: "Tốc độ bán tăng bất thường",
    gmv_drop: "GMV giảm mạnh",
  };
  return map[alertType] ?? alertType;
}

function toStatusLabel(status: string): string {
  const map: Record<string, string> = {
    delivered: "Đã gửi",
    sent: "Đã gửi",
    failed: "Thất bại",
    triggered: "Đã kích hoạt",
  };
  return map[status] ?? status;
}

function statusStyle(status: string): React.CSSProperties {
  if (status === "failed") return { background: "#ef444420", color: "#ef4444" };
  if (status === "sent" || status === "delivered") return { background: "#10b98120", color: "#10b981" };
  return { background: "var(--muted)", color: "var(--muted-foreground)" };
}

