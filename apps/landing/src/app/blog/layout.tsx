import type { ReactNode } from "react";

import "./blog.css";

/** `/blog` and its posts: only adds the blog stylesheet (kept out of globals.css, P33-D). */
export default function BlogLayout({ children }: Readonly<{ children: ReactNode }>) {
  return children;
}
