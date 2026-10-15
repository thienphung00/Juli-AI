import styles from "./diagrams.module.css";

/**
 * Block-built diagrams of the capability pages (D44.3: diagrams in markup, no
 * images, no invented numbers). Each is a `<figure>` whose content is real
 * text (lists), so screen readers read the steps, not a picture.
 */

function cx(...names: Array<string | false | null | undefined>): string {
  return names.filter(Boolean).join(" ");
}

/* ————— Five streams (Phân tích, Product.dc.html "Năm luồng truy cập") ————— */

const STREAMS = [
  { group: "Khách tự tìm đến", name: "Thẻ sản phẩm", where: "Tab Sản phẩm" },
  { group: "Khách tự tìm đến", name: "Tab cửa hàng", where: "Tab Sản phẩm" },
  { group: "Nội dung", name: "Video", where: "Tab Nội dung" },
  { group: "Nội dung", name: "LIVE", where: "Tab Nội dung" },
  { group: "Nội dung", name: "Liên kết", where: "Trang chủ" },
] as const;

/** The five traffic streams TikTok Shop records, and where Juli shows each one. */
export function StreamGrid() {
  return (
    <figure className={styles.figure}>
      <ul aria-label="Năm luồng truy cập" className={styles.streams}>
        {STREAMS.map((stream) => (
          <li className={styles.stream} key={stream.name}>
            <span className={styles.meta}>{stream.group}</span>
            <span className={styles.streamName}>{stream.name}</span>
            <span className={styles.where}>Trong Juli: {stream.where}</span>
          </li>
        ))}
      </ul>
      <figcaption className={styles.caption}>
        Năm luồng của mục Lưu lượng truy cập sản phẩm trên Trung tâm nhà bán hàng, và nơi Juli hiển
        thị từng luồng.
      </figcaption>
    </figure>
  );
}

/* ————— Flow / timeline ————— */

export interface ProcessStep {
  /** Small label above the title: "Bước 1", "Ngày 7", "Bạn"… */
  marker: string;
  title: string;
  body: string;
  /** The seller's step: pink tint (D44.2, "the Duyệt step"). */
  you?: boolean;
}

export interface ProcessDiagramProps {
  steps: readonly ProcessStep[];
  /** Names the list for screen readers. */
  label: string;
  caption?: string;
  /** `flow` = cards joined by arrows · `timeline` = dots on a line. */
  variant?: "flow" | "timeline";
}

/**
 * A short ordered process, built in markup: "Duyệt → Thực thi → Hoàn tác"
 * (flow) or "Trước → Ngày 7 → Ngày 14" (timeline). A row ≥ 760 px, a vertical
 * list on phones. Same DOM at every width.
 */
export function ProcessDiagram({ steps, label, caption, variant = "flow" }: ProcessDiagramProps) {
  return (
    <figure className={cx(styles.figure, styles[variant])}>
      <ol aria-label={label} className={styles.steps}>
        {steps.map((step) => (
          <li className={cx(styles.step, step.you && styles.stepYou)} key={step.title}>
            <span aria-hidden="true" className={styles.dot} />
            <span className={styles.meta}>{step.marker}</span>
            <span className={styles.stepTitle}>{step.title}</span>
            <span className={styles.stepBody}>{step.body}</span>
          </li>
        ))}
      </ol>
      {caption ? <figcaption className={styles.caption}>{caption}</figcaption> : null}
    </figure>
  );
}
