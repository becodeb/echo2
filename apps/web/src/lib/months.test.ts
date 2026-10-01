import { describe, expect, it } from "vitest";
import { currentMonth } from "../lib/months";

describe("currentMonth", () => {
  it("corta el mes con la hora de Argentina, como el servidor", () => {
    // 1° de octubre a las 01:30 UTC es todavía 30 de septiembre en Argentina.
    expect(currentMonth(new Date("2026-10-01T01:30:00Z"))).toBe("2026-09");
    expect(currentMonth(new Date("2026-10-01T03:00:00Z"))).toBe("2026-10");
  });
});
