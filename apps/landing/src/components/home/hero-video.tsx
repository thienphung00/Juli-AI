"use client";

import { useEffect, useRef, useState } from "react";

import { HERO_VIDEO, HERO_VIDEO_SCHEMA } from "../../lib/media";
import { Button } from "../ui/button";
import { Icon } from "../ui/icon";
import styles from "./home.module.css";

/**
 * "Xem video 1 phút" (Main.dc.html hero, D43.6 + D44). A secondary button that
 * opens a modal `<dialog>` with the sales video. The `<video>` element does not
 * exist until the visitor presses the button, so not a byte of the 9.5 MB file
 * is fetched on load; it keeps `preload="none"` and starts playing from the
 * click. Closing the dialog unmounts it again. VideoObject schema stays on `/`.
 */
export function HeroVideo() {
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!open || !dialog || dialog.open) return;
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
  }, [open]);

  return (
    <>
      <Button
        aria-haspopup="dialog"
        blockOnMobile
        data-testid="hero-video-play"
        icon="play"
        onClick={() => setOpen(true)}
        variant="secondary"
      >
        Xem video 1 phút
      </Button>
      {open ? (
        <dialog
          aria-labelledby="hero-video-title"
          className={styles.videoDialog}
          data-testid="hero-video-dialog"
          onClick={(event) => {
            // A click on the backdrop (the dialog box itself, outside the panel) closes it.
            if (event.target === event.currentTarget) dialogRef.current?.close();
          }}
          onClose={() => setOpen(false)}
          ref={dialogRef}
        >
          <div className={styles.videoPanel}>
            <div className={styles.videoBar}>
              <p className={styles.videoTitle} id="hero-video-title">
                Video giới thiệu Juli (1:04)
              </p>
              <button
                aria-label="Đóng video"
                className={styles.videoClose}
                onClick={() => dialogRef.current?.close()}
                type="button"
              >
                <Icon name="close" size={20} />
              </button>
            </div>
            <video
              aria-label={HERO_VIDEO_SCHEMA.description}
              autoPlay
              className={styles.videoMedia}
              controls
              data-testid="hero-demo-video"
              height={HERO_VIDEO.poster.large.height}
              playsInline
              poster={HERO_VIDEO.poster.large.webp}
              preload="none"
              src={HERO_VIDEO.src}
              width={HERO_VIDEO.poster.large.width}
            />
            <p className={styles.videoCaption}>
              Cách Juli đọc GMV theo từng chỉ số và đề xuất việc cần làm. Số liệu trong video là
              minh hoạ.
            </p>
          </div>
        </dialog>
      ) : null}
    </>
  );
}
