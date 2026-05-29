"use client";

import { useRouter } from "next/navigation";
import { MODE_SELECT_OPTIONS } from "@/lib/mock-data/mode-select";
import { useModeGuard } from "@/lib/use-mode-guard";
import { useWorkspaceMode } from "@/lib/mode-context";

function PageSpinner() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="spinner" role="status" aria-label="Đang tải" />
    </div>
  );
}

export function ModeSelectionPage() {
  const { loading } = useModeGuard("require-no-mode");
  const { setMode } = useWorkspaceMode();
  const router = useRouter();

  if (loading) {
    return <PageSpinner />;
  }

  const handleSelect = (mode: (typeof MODE_SELECT_OPTIONS)[number]["mode"]) => {
    setMode(mode);
    router.replace("/");
  };

  return (
    <div
      className="flex min-h-screen flex-col items-center justify-center px-4 py-10"
      style={{ background: "var(--background)" }}
    >
      <div className="w-full max-w-md space-y-8">
        <div className="text-center">
          <h1 className="brand-wordmark brand-wordmark-lg">Juli</h1>
          <p className="mt-3 text-lg font-semibold" style={{ color: "var(--foreground)" }}>
            Bạn đang vận hành theo vai trò nào?
          </p>
          <p className="mt-2 text-sm" style={{ color: "var(--muted-foreground)" }}>
            Chọn chế độ để tùy chỉnh KPI, giao diện và điều hướng. Bạn có thể đổi sau trong header.
          </p>
        </div>

        <div className="space-y-4">
          {MODE_SELECT_OPTIONS.map((option) => (
            <button
              key={option.mode}
              type="button"
              aria-label={option.title}
              onClick={() => handleSelect(option.mode)}
              className="card w-full p-5 text-left transition-opacity hover:opacity-90"
            >
              <span className="text-lg font-semibold" style={{ color: "var(--foreground)" }}>
                {option.title}
              </span>
              <p className="mt-2 text-sm" style={{ color: "var(--muted-foreground)" }}>
                {option.description}
              </p>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
