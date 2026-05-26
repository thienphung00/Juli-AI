/**
 * AC3 — All UI text in Vietnamese with VND formatting (₫), diacritics,
 * and local date/time (PRD AC-13)
 */
import { formatVND, formatNumber, formatDate, formatDateTime } from "@/lib/format";

describe("AC3: Vietnamese locale formatting", () => {
  describe("VND currency formatting", () => {
    it("formats zero as VND", () => {
      const result = formatVND(0);
      expect(result).toContain("0");
      expect(result).toMatch(/₫|VND/);
    });

    it("formats large amounts with thousands separators", () => {
      const result = formatVND(1500000);
      // Vietnamese uses dot as thousands separator
      expect(result).toContain("1.500.000");
    });

    it("does not include decimal places for VND", () => {
      const result = formatVND(1234567);
      expect(result).not.toContain(",00");
      expect(result).not.toContain(".00");
    });
  });

  describe("Number formatting", () => {
    it("formats numbers with Vietnamese thousands separators", () => {
      const result = formatNumber(1234567);
      expect(result).toBe("1.234.567");
    });
  });

  describe("Date formatting", () => {
    it("formats ISO date in Vietnamese format (dd/mm/yyyy)", () => {
      const result = formatDate("2024-03-15T10:30:00Z");
      expect(result).toMatch(/15\/03\/2024/);
    });

    it("uses ICT timezone (UTC+7)", () => {
      // 2024-01-01T00:00:00Z is already Jan 1 07:00 in ICT
      const result = formatDateTime("2024-01-01T00:00:00Z");
      expect(result).toContain("01/01/2024");
      expect(result).toContain("07:00");
    });
  });

  describe("DateTime formatting", () => {
    it("includes both date and time", () => {
      const result = formatDateTime("2024-06-15T14:30:00Z");
      // 14:30 UTC = 21:30 ICT
      expect(result).toMatch(/15\/06\/2024/);
      expect(result).toContain("21:30");
    });
  });
});
