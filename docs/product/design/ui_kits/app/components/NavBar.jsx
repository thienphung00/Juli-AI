// Four-destination IA. source_examples/NavBar.tsx is historical evidence only.
const NAV_TABS = [
  { id: "home", label: "Trang chủ", icon: "home" },
  { id: "decisions", label: "Quyết định", icon: "check" },
  { id: "analytics", label: "Phân tích", icon: "chart" },
  { id: "settings", label: "Cài đặt", icon: "settings" },
];

function NavIcon({ name, color, size = 22 }) {
  const common = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: color, strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" };
  switch (name) {
    case "home":
      return (<svg {...common}><path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" /></svg>);
    case "check":
      return (<svg {...common}><path d="M4 12l6 6L20 6" /></svg>);
    case "chart":
      return (<svg {...common}><path d="M4 20V10M12 20V4M20 20v-7" /></svg>);
    case "settings":
      return (<svg {...common}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21h-4v-.09A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3v-4h.09A1.7 1.7 0 0 0 4.6 8.6a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3h4v.09A1.7 1.7 0 0 0 15.4 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.15.36.36.7.6 1 .3.28.68.42 1.1.4h.09v4h-.09a1.7 1.7 0 0 0-1.7.6z" /></svg>);
    default:
      return null;
  }
}

function NavBar({ active, onNavigate }) {
  return (
    <nav
      aria-label="Điều hướng chính"
      style={{ position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 50, background: "var(--card)", borderTop: "1px solid var(--border)" }}
      className="safe-area-bottom"
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-around", maxWidth: 480, margin: "0 auto", paddingTop: 8, paddingBottom: 12 }}>
        {NAV_TABS.map((tab) => {
          const isActive = active === tab.id;
          const activeColor = "var(--primary)";
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => onNavigate(tab.id)}
              aria-current={isActive ? "page" : undefined}
              style={{
                position: "relative",
                display: "flex",
                minHeight: 44,
                minWidth: 44,
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: 4,
                borderRadius: 12,
                padding: "4px 12px",
                border: "none",
                background: "transparent",
                cursor: "pointer",
              }}
            >
              {isActive && (
                <span style={{ position: "absolute", inset: 0, borderRadius: 12, background: "color-mix(in srgb, var(--primary) 12%, transparent)" }} />
              )}
              <span style={{ position: "relative", display: "flex", height: 28, width: 28, alignItems: "center", justifyContent: "center" }}>
                <NavIcon name={tab.icon} color={isActive ? activeColor : "var(--muted-foreground)"} />
              </span>
              <span style={{ fontSize: 11, fontWeight: 600, color: isActive ? activeColor : "var(--muted-foreground)" }}>{tab.label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}

window.NavBar = NavBar;
