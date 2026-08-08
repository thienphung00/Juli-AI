/**
 * Stand-in for `@juli/brand/assets/*.png` static imports under vitest — shaped
 * like Next.js `StaticImageData` so `next/image` (incl. `placeholder="blur"`)
 * renders without the real binary.
 */
const staticImageStub = {
  src: "/asset-stub.png",
  height: 120,
  width: 120,
  blurDataURL:
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
};

export default staticImageStub;
