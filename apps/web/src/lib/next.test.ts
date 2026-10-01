import { describe, expect, it } from "vitest";
import { safeNext } from "./next";

describe("safeNext", () => {
  it("vuelve solo a links de la propia app", () => {
    expect(safeNext("/meetings/123?tab=minutes")).toBe("/meetings/123?tab=minutes");
    expect(safeNext("//evil.com")).toBeNull();
    expect(safeNext("https://evil.com")).toBeNull();
    expect(safeNext("/login?next=/x")).toBeNull();
    expect(safeNext(null)).toBeNull();
  });
});
