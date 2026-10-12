// Builds dist/ (load it unpacked, or zip it for the Chrome Web Store):
// each entry as one self-contained IIFE (content scripts cannot be ES modules),
// plus manifest.json and the popup page. JULI_API_ORIGIN (default
// https://api.app-juli.com) is baked into both the code and the host permission.
import { copyFile, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = resolve(root, "dist");
const origin = process.env.JULI_API_ORIGIN ?? "https://api.app-juli.com";
if (!/^https:\/\/[a-z0-9.-]+(:\d+)?$/.test(origin) && !/^http:\/\/localhost(:\d+)?$/.test(origin)) {
  throw new Error(`JULI_API_ORIGIN must be an https origin (or http://localhost), got ${origin}`);
}

const entries = {
  sw: "src/background/sw.ts",
  hook: "src/page/hook.ts",
  content: "src/content/content.ts",
  popup: "src/popup/popup.ts",
};

await rm(outDir, { recursive: true, force: true });
await mkdir(outDir, { recursive: true });
for (const [name, entry] of Object.entries(entries)) {
  await build({
    configFile: false,
    root,
    logLevel: "warn",
    define: { __JULI_API_ORIGIN__: JSON.stringify(origin) },
    build: {
      outDir,
      emptyOutDir: false,
      minify: false,
      sourcemap: false,
      target: "chrome111",
      lib: { entry: resolve(root, entry), formats: ["iife"], name: `juli_${name}`, fileName: () => `${name}.js` },
    },
  });
}

const manifest = (await readFile(resolve(root, "public/manifest.json"), "utf8")).replaceAll(
  "__JULI_API_ORIGIN__",
  origin,
);
await writeFile(resolve(outDir, "manifest.json"), manifest);
for (const file of ["popup.html", "popup.css"]) {
  await copyFile(resolve(root, "public", file), resolve(outDir, file));
}
console.log(`Juli Connector built in ${outDir} (API ${origin})`);
