import type { HomeAlertCard } from "@/lib/mock-data/home";

const SEVERITY_STYLES: Record<
  HomeAlertCard["severity"],
  { background: string; border: string; label: string }
> = {
  high: {
    background: "#ef444420",
    border: "#ef4444",
    label: "CẢNH BÁO",
  },
  medium: {
    background: "#f59e0b20",
    border: "#f59e0b",
    label: "CHÚ Ý",
  },
  low: {
    background: "#3b82f620",
    border: "#3b82f6",
    label: "THÔNG BÁO",
  },
  info: {
    background: "#10b98120",
    border: "#10b981",
    label: "THÔNG BÁO",
  },
};

export function AlertBannerCard({ alert }: { alert: HomeAlertCard }) {
  const styles = SEVERITY_STYLES[alert.severity];

  return (
    <div
      className="card p-4"
      data-testid={`home-alert-card-${alert.id}`}
      style={{ borderLeft: `3px solid ${styles.border}` }}
    >
      <div className="flex items-start justify-between gap-2">
        <p
          className="text-xs font-bold tracking-wide"
          style={{ color: styles.border }}
        >
          {styles.label}
        </p>
      </div>
      <p className="mt-1 text-sm font-semibold">{alert.title}</p>
      <p className="text-muted mt-1 text-sm">{alert.body}</p>
      {alert.action_label && alert.action_href && (
        <a
          href={alert.action_href}
          className="mt-3 inline-block text-sm font-semibold"
          style={{ color: "var(--primary)" }}
          data-testid="home-alert-action"
        >
          {alert.action_label} →
        </a>
      )}
    </div>
  );
}
