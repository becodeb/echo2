import { describe, expect, it } from "vitest";
import type { PublicPlan } from "./billing";
import { compareRows, planSpecs, priceLabel } from "./PlanCatalog";

const PLANS: PublicPlan[] = [
  { code: "base", name: "Gratis", scope: "any", price_usd: 0, features: {}, limits: { credits_per_month: 4 } },
  { code: "individual", name: "Individual", scope: "user", price_usd: 5, features: {}, limits: { people_hours_per_month: 6 } },
  { code: "individual_voz", name: "Individual + voz", scope: "user", price_usd: 10, features: { voice: true }, limits: { voice_minutes_per_month: 30 } },
  { code: "institucion", name: "Instituciones", scope: "organization", price_usd: null, features: {}, limits: {} },
] as PublicPlan[];

describe("catálogo de planes", () => {
  it("usa los topes de la base, no números fijos", () => {
    const specs = planSpecs(PLANS);
    expect(specs.map((spec) => spec.plan.code)).toEqual(["base", "individual", "individual_voz", "institucion"]);
    expect(specs[0].bullets).toContain("4 reuniones por mes con quién habló");
    expect(specs[1].bullets).toContain("6 h por mes con quién habló");
    expect(specs[2].bullets.join(" ")).toContain("30 min por mes");
  });

  it("lo que es de los planes pagos no figura en Gratis", () => {
    const rows = Object.fromEntries(compareRows(PLANS).map((row) => [row.label, row.cells]));
    expect(rows["Preguntale a Echo sobre todas"]).toEqual([false, true, true, true]);
    expect(rows["Word, Documento de Google y Drive"][0]).toBe(false);
    expect(rows["Duración de cada reunión"][0]).toBe("Hasta 1 h");
    expect(rows["Hablar con Echo por voz"]).toEqual([false, false, "30 min / mes", false]);
  });

  it("Instituciones va a medida", () => {
    expect(priceLabel(PLANS[3])).toEqual({ amount: "A medida", per: null });
    expect(priceLabel(PLANS[0]).amount).toBe("US$ 0");
  });
});
