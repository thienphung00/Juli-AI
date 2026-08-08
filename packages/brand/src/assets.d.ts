// Raster asset imports resolve to a URL string (plain bundlers) or a
// StaticImageData-shaped object (Next.js). Consumers normalise via `assetSrc`.
declare module "*.png" {
  const asset: string | { src: string; height: number; width: number };
  export default asset;
}

declare module "*.webp" {
  const asset: string | { src: string; height: number; width: number };
  export default asset;
}
