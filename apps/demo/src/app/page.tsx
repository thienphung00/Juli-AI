import { DestinationCard } from "@juli/ui";
import { formatDateTime } from "@juli/utils";

import { demoSnapshot, homeDestinations } from "../lib/mock-data";

export default function HomePage() {
  return (
    <>
      <section aria-labelledby="home-title">
        <p className="demo-kicker">Trang chủ</p>
        <h1 className="demo-title" id="home-title">
          Bạn muốn làm gì tiếp theo?
        </h1>
        <p className="demo-intro">
          Juli gom mọi thứ vào đúng nơi để bạn có thể quyết định nhanh và hiểu
          rõ điều đang diễn ra trong shop.
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
            actionLabel="Mở trang"
            description={destination.description}
            eyebrow={destination.eyebrow}
            href={destination.href}
            icon={destination.icon}
            title={destination.label}
          />
        ))}
      </section>
    </>
  );
}
