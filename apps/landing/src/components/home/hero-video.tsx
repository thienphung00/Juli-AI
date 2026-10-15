"use client";

import { useState } from "react";

import { HERO_VIDEO, HERO_VIDEO_SCHEMA } from "../../lib/media";
import { Picture } from "../picture";

/**
 * Hero visual (D43.6): a poster image (AVIF/WebP, width/height, the LCP
 * element) with a ▶ button. The `<video>` element does not exist until the
 * visitor presses play, so not a byte of the 9.5 MB file is fetched on load;
 * when it mounts it keeps `preload="none"` and starts playing from the click.
 * Both states share one 16:9 box, so swapping them shifts nothing.
 */
export function HeroVideo() {
  const [playing, setPlaying] = useState(false);

  return (
    <figure className="lp-home-video">
      <div className="lp-home-video__frame">
        {playing ? (
          <video
            aria-label={HERO_VIDEO_SCHEMA.description}
            autoPlay
            className="lp-home-video__media"
            controls
            data-testid="hero-demo-video"
            height={HERO_VIDEO.poster.large.height}
            playsInline
            poster={HERO_VIDEO.poster.large.webp}
            preload="none"
            src={HERO_VIDEO.src}
            width={HERO_VIDEO.poster.large.width}
          />
        ) : (
          <button
            aria-label="Phát video giới thiệu Juli (1 phút 4 giây)"
            className="lp-home-video__play"
            data-testid="hero-video-play"
            onClick={() => setPlaying(true)}
            type="button"
          >
            <Picture
              alt="Khung hình trong video giới thiệu: GMV = Hiển thị × CTR × CTOR × AOV"
              className="lp-home-video__media"
              priority
              sizes="(min-width: 56rem) 45vw, 100vw"
              variants={[HERO_VIDEO.poster.small, HERO_VIDEO.poster.large]}
            />
            <span aria-hidden="true" className="lp-home-video__icon">
              ▶ Xem video · 1:04
            </span>
          </button>
        )}
      </div>
      <figcaption className="lp-home-video__caption">
        Video giới thiệu (1:04): cách Juli đọc GMV theo từng chỉ số và đề xuất việc cần làm.
        Số liệu trong video là minh hoạ.
      </figcaption>
    </figure>
  );
}
