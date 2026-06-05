/**
 * Issue #114 — Mock data schemas and seller personas (P1-1)
 */
import {
  loadPersona,
  listPersonaIds,
  validatePersona,
  FORBIDDEN_PII_KEYS,
} from "@/lib/mock-data/seller-personas";
import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";

const PERSONA_IDS: PersonaId[] = ["new", "leakage", "growth"];

describe("Issue #114: seller persona mock data", () => {
  describe("loadPersona", () => {
    it("returns typed persona for new", () => {
      const persona = loadPersona("new");

      expect(persona.profile.id).toBe("new");
      expect(persona.profile.shop_name.length).toBeGreaterThan(0);
      expect(persona.orders.length).toBeGreaterThanOrEqual(10);
      expect(persona.ad_campaigns.length).toBeGreaterThanOrEqual(2);
      expect(persona.tasks.length).toBeGreaterThan(0);
    });

    it("returns typed persona for leakage", () => {
      const persona = loadPersona("leakage");

      expect(persona.profile.id).toBe("leakage");
      expect(persona.profile.shop_name.length).toBeGreaterThan(0);
      expect(persona.orders.length).toBeGreaterThanOrEqual(10);
      expect(persona.ad_campaigns.length).toBeGreaterThanOrEqual(2);
      expect(persona.tasks.length).toBeGreaterThan(0);
    });

    it("returns typed persona for growth", () => {
      const persona = loadPersona("growth");

      expect(persona.profile.id).toBe("growth");
      expect(persona.profile.shop_name.length).toBeGreaterThan(0);
      expect(persona.orders.length).toBeGreaterThanOrEqual(10);
      expect(persona.ad_campaigns.length).toBeGreaterThanOrEqual(2);
      expect(persona.tasks.length).toBeGreaterThan(0);
    });

    it("throws for unknown persona id", () => {
      expect(() => loadPersona("unknown" as PersonaId)).toThrow(/Unknown persona/);
    });
  });

  describe("schema validation", () => {
    it("validates new persona against schemas", () => {
      const result = validatePersona(loadPersona("new"));
      expect(result.valid).toBe(true);
      expect(result.errors).toEqual([]);
    });

    it("validates leakage persona against schemas", () => {
      const result = validatePersona(loadPersona("leakage"));
      expect(result.valid).toBe(true);
      expect(result.errors).toEqual([]);
    });

    it("validates growth persona against schemas", () => {
      const result = validatePersona(loadPersona("growth"));
      expect(result.valid).toBe(true);
      expect(result.errors).toEqual([]);
    });
  });

  describe("Vietnamese realism", () => {
    it.each(PERSONA_IDS)("uses Vietnamese shop names and VND prices for %s", (id) => {
      const persona = loadPersona(id);

      expect(persona.profile.shop_name).toMatch(/[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]/i);
      expect(persona.orders.every((o) => o.total_vnd > 0)).toBe(true);
      expect(persona.orders.some((o) => /[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]/i.test(o.product_title))).toBe(true);
    });
  });

  describe("task copy colocation", () => {
    it("ships task title, body, and CTA with persona new", () => {
      const persona = loadPersona("new");

      for (const task of persona.tasks) {
        expect(task.title.trim().length).toBeGreaterThan(0);
        expect(task.body.trim().length).toBeGreaterThan(0);
        expect(task.cta_label.trim().length).toBeGreaterThan(0);
        expect(task.copy_source).toBe("mock");
      }
    });

    it("ships task title, body, and CTA with persona leakage", () => {
      const persona = loadPersona("leakage");

      for (const task of persona.tasks) {
        expect(task.title.trim().length).toBeGreaterThan(0);
        expect(task.body.trim().length).toBeGreaterThan(0);
        expect(task.cta_label.trim().length).toBeGreaterThan(0);
        expect(task.copy_source).toBe("mock");
      }
    });

    it("ships task title, body, and CTA with persona growth", () => {
      const persona = loadPersona("growth");

      for (const task of persona.tasks) {
        expect(task.title.trim().length).toBeGreaterThan(0);
        expect(task.body.trim().length).toBeGreaterThan(0);
        expect(task.cta_label.trim().length).toBeGreaterThan(0);
        expect(task.copy_source).toBe("mock");
      }
    });
  });

  describe("PII policy", () => {
    it("contains no forbidden buyer PII fields in new", () => {
      const persona = loadPersona("new");
      const serialized = JSON.stringify(persona).toLowerCase();

      for (const key of FORBIDDEN_PII_KEYS) {
        expect(serialized).not.toContain(`"${key.toLowerCase()}"`);
      }
    });

    it("contains no forbidden buyer PII fields in leakage", () => {
      const persona = loadPersona("leakage");
      const serialized = JSON.stringify(persona).toLowerCase();

      for (const key of FORBIDDEN_PII_KEYS) {
        expect(serialized).not.toContain(`"${key.toLowerCase()}"`);
      }
    });

    it("contains no forbidden buyer PII fields in growth", () => {
      const persona = loadPersona("growth");
      const serialized = JSON.stringify(persona).toLowerCase();

      for (const key of FORBIDDEN_PII_KEYS) {
        expect(serialized).not.toContain(`"${key.toLowerCase()}"`);
      }
    });

    it("uses masked buyer_id only in new orders and returns", () => {
      const persona = loadPersona("new");
      const buyerIds = [
        ...persona.orders.map((o) => o.buyer_id),
        ...persona.returns.map((r) => r.buyer_id),
      ];

      expect(buyerIds.length).toBeGreaterThan(0);
      for (const buyerId of buyerIds) {
        expect(buyerId).toMatch(/^buyer_[*x\d]+$/i);
        expect(buyerId).not.toMatch(/@/);
        expect(buyerId).not.toMatch(/\+?\d{9,}/);
      }
    });

    it("uses masked buyer_id only in leakage orders and returns", () => {
      const persona = loadPersona("leakage");
      const buyerIds = [
        ...persona.orders.map((o) => o.buyer_id),
        ...persona.returns.map((r) => r.buyer_id),
      ];

      expect(buyerIds.length).toBeGreaterThan(0);
      for (const buyerId of buyerIds) {
        expect(buyerId).toMatch(/^buyer_[*x\d]+$/i);
        expect(buyerId).not.toMatch(/@/);
        expect(buyerId).not.toMatch(/\+?\d{9,}/);
      }
    });

    it("uses masked buyer_id only in growth orders and returns", () => {
      const persona = loadPersona("growth");
      const buyerIds = [
        ...persona.orders.map((o) => o.buyer_id),
        ...persona.returns.map((r) => r.buyer_id),
      ];

      expect(buyerIds.length).toBeGreaterThan(0);
      for (const buyerId of buyerIds) {
        expect(buyerId).toMatch(/^buyer_[*x\d]+$/i);
        expect(buyerId).not.toMatch(/@/);
        expect(buyerId).not.toMatch(/\+?\d{9,}/);
      }
    });
  });

  describe("persona registry", () => {
    it("lists all three personas", () => {
      expect(listPersonaIds()).toEqual(expect.arrayContaining(PERSONA_IDS));
      expect(listPersonaIds()).toHaveLength(3);
    });
  });
});
