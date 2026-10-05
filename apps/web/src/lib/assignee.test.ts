import { describe, expect, it } from "vitest";
import { matchesSuggestion } from "./assignee";

describe("a quién sugerir para una tarea", () => {
  it("reconoce el rol o el nombre que se dijo en la reunión", () => {
    expect(matchesSuggestion({ name: "Laura Pérez", job_title: "Directora" }, "la Directora")).toBe(true);
    expect(matchesSuggestion({ name: "Laura Pérez", job_title: null }, "Laura")).toBe(true);
    expect(matchesSuggestion({ name: "Ana Gómez", job_title: "Orientadora (DOE)" }, "orientadora")).toBe(true);
  });

  it("no inventa coincidencias", () => {
    expect(matchesSuggestion({ name: "Ana Gómez", job_title: "Preceptora" }, "Directora")).toBe(false);
    expect(matchesSuggestion({ name: "Ana Gómez", job_title: "Preceptora" }, null)).toBe(false);
  });
});
