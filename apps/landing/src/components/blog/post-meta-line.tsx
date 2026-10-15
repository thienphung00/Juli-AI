import { formatDate } from "../../content/blog";

/** "Đội ngũ Juli AI · Đăng 15/10/2026 · Cập nhật 20/10/2026 · 18 phút đọc" */
export function PostMetaLine({
  author,
  publishedAt,
  updatedAt,
  minutes,
}: {
  author?: string;
  publishedAt: string;
  updatedAt: string;
  minutes: number;
}) {
  return (
    <p className="lp-blog__meta">
      {author ? <span>{author}</span> : null}
      <span>
        Đăng <time dateTime={publishedAt}>{formatDate(publishedAt)}</time>
      </span>
      {updatedAt !== publishedAt ? (
        <span>
          Cập nhật <time dateTime={updatedAt}>{formatDate(updatedAt)}</time>
        </span>
      ) : null}
      <span>{minutes} phút đọc</span>
    </p>
  );
}
