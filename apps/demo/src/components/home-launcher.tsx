import { DestinationCard, DestinationIcon } from "@juli/ui";
import { formatDateTime } from "@juli/utils";

import { demoSnapshot, homeDestinations } from "../lib/mock-data";

/**
 * The captured-scenario replay a visitor sees after choosing "Dùng thử Demo"
 * (ADR-094 decision 1). Deliberately does not render `HomeActivityTracker` —
 * that widget reads `mutableState.executionRecords`/recommendation ids as if
 * they belonged to the visitor, which is exactly the "this feels like your
 * own shop" impression a client replay must not create. Kept import-graph
 * clean by construction: `mock-data.ts`, `@juli/ui`, `@juli/utils` only —
 * see `src/__tests__/replay-module-graph.test.ts`, which asserts no module
 * reachable from here issues a Juli backend v1 request.
 */
export function HomeLauncher() {
  return (
    <>
      <section aria-labelledby="home-title">
        <p className="demo-kicker">Trang chủ</p>
        <h1 className="demo-title" id="home-title">
          Quyết định nhanh, hiểu rõ shop.
        </h1>
        <p className="demo-intro">
          Hai nơi bạn cần: đề xuất đang chờ phê duyệt, và bức tranh toàn cảnh
          shop.
        </p>
        <p className="demo-notice" data-testid="mock-data-notice">
          {demoSnapshot.shopName} · dữ liệu mẫu cập nhật{" "}
          {formatDateTime(demoSnapshot.generatedAt)}
        </p>
      </section>

      <section className="demo-launchers" aria-label="Điểm đến chính">
        {homeDestinations.map((destination) => (
          <DestinationCard
            key={destination.href}
            actionLabel={destination.actionLabel}
            description={destination.description}
            eyebrow={destination.eyebrow}
            href={destination.href}
            icon={<DestinationIcon name={destination.icon} />}
            title={destination.label}
          />
        ))}
      </section>
    </>
  );
}
