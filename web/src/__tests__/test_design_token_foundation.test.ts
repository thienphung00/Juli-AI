/**
 * Issue #174 — Design token foundation (ADR-015): theme swap, semantic palette,
 * state/elevation utilities (P1.8-8 slice 1).
 */
import fs from "fs";
import path from "path";
import {
  applyWorkspaceTheme,
  WORKSPACE_MODE_STORAGE_KEY,
} from "@/lib/workspace-mode";
import { WORKSPACE_THEME_INIT_SCRIPT } from "@/lib/theme-init";

const globalsCssPath = path.join(__dirname, "../app/globals.css");
const globalsCss = fs.readFileSync(globalsCssPath, "utf8");

beforeEach(() => {
  document.documentElement.className = "";
});

describe("Design token foundation (#174)", () => {
  describe("theme bootstrap", () => {
    it("applies light theme (no dark class) for seller workspace mode", () => {
      applyWorkspaceTheme("seller");
      expect(document.documentElement.classList.contains("dark")).toBe(false);
    });

    it("applies dark theme for affiliate workspace mode", () => {
      applyWorkspaceTheme("affiliate");
      expect(document.documentElement.classList.contains("dark")).toBe(true);
    });

    it("inline init script maps seller to light and affiliate to dark", () => {
      expect(WORKSPACE_THEME_INIT_SCRIPT).toContain(WORKSPACE_MODE_STORAGE_KEY);
      expect(WORKSPACE_THEME_INIT_SCRIPT).toMatch(
        /m==="seller"\)\{[^}]*classList\.remove\("dark"\)/,
      );
      expect(WORKSPACE_THEME_INIT_SCRIPT).toMatch(
        /m==="affiliate"\)\{[^}]*classList\.add\("dark"\)/,
      );
    });
  });

  describe("semantic palette tokens in globals.css", () => {
    it("defines ADR-015 semantic hex values", () => {
      expect(globalsCss).toMatch(/--success:\s*#16a34a/i);
      expect(globalsCss).toMatch(/--destructive:\s*#e5484d/i);
      expect(globalsCss).toMatch(/--warning:\s*#f59e0b/i);
      expect(globalsCss).toMatch(/--info:\s*#2563eb/i);
    });

    it("defines semantic background tint variables", () => {
      expect(globalsCss).toMatch(/--success-tint:/);
      expect(globalsCss).toMatch(/--destructive-tint:/);
      expect(globalsCss).toMatch(/--warning-tint:/);
      expect(globalsCss).toMatch(/--info-tint:/);
    });

    it("maps seller to white canvas and affiliate to dark canvas (#191)", () => {
      expect(globalsCss).toMatch(/Seller \(light\)/);
      expect(globalsCss).toMatch(/Affiliate \(dark\)/);
      expect(globalsCss).toMatch(
        /html:not\(\.dark\)[\s\S]*--background:\s*#ffffff/,
      );
      expect(globalsCss).toMatch(
        /html\.dark[\s\S]*--background:\s*#050505/,
      );
    });
  });

  describe("state and elevation utilities in globals.css", () => {
    it("defines 3-step elevation scale", () => {
      expect(globalsCss).toMatch(/--shadow-sm:/);
      expect(globalsCss).toMatch(/--shadow-md:/);
      expect(globalsCss).toMatch(/--shadow-lg:/);
      expect(globalsCss).toMatch(/\.elevation-sm/);
      expect(globalsCss).toMatch(/\.elevation-md/);
      expect(globalsCss).toMatch(/\.elevation-lg/);
    });

    it("extends interactive primitives with hover, active, and focus-visible states", () => {
      expect(globalsCss).toMatch(/\.btn-primary:focus-visible/);
      expect(globalsCss).toMatch(/\.btn-primary:active/);
      expect(globalsCss).toMatch(/\.btn-secondary:focus-visible/);
      expect(globalsCss).toMatch(/\.card-interactive/);
      expect(globalsCss).toMatch(/\.field-input:focus-visible/);
    });
  });
});
