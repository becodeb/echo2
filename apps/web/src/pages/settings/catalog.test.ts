import { describe, expect, it } from "vitest";
import { normalize, resolvePath, searchSettings, visibleSections, type Viewer } from "./catalog";

const admin: Viewer = { admin: true, directive: true, managesLevels: true };
const member: Viewer = { admin: false, directive: false, managesLevels: false };
const directive: Viewer = { admin: false, directive: true, managesLevels: true };

describe("normalize", () => {
  it("saca acentos y mayúsculas", () => {
    expect(normalize("  Inglés NUMERACIÓN ")).toBe("ingles numeracion");
  });
});

describe("searchSettings", () => {
  it("encuentra el membrete por nombre y por lo que tiene adentro", () => {
    const [first] = searchSettings("membrete", admin);
    expect(first.section).toBe("letterhead");
    expect(first.target).toBeUndefined();
    expect(searchSettings("logo", admin)[0]).toMatchObject({ section: "letterhead", target: "letterhead-logo" });
    expect(searchSettings("firma", admin)[0]).toMatchObject({ section: "letterhead", target: "letterhead-signatures" });
  });

  it("no distingue acentos", () => {
    expect(searchSettings("inglés", admin)[0]).toMatchObject({ section: "template", target: "minutes-language" });
    expect(searchSettings("numero", admin)[0].section).toBe("numbering");
    expect(searchSettings("NÚMERO", admin)[0].section).toBe("numbering");
  });

  it("drive trae los dos Drive", () => {
    const sections = searchSettings("drive", admin).map((hit) => hit.section);
    expect(sections).toContain("my-drive");
    expect(sections).toContain("drive");
  });

  it("todas las palabras tienen que estar", () => {
    expect(searchSettings("borrar mis datos", member)[0]).toMatchObject({ section: "privacy", target: "privacy-requests" });
    expect(searchSettings("voz", member)[0].section).toBe("my-voice");
    expect(searchSettings("membrete zzz", admin)).toEqual([]);
  });

  it("no muestra lo que la persona no ve", () => {
    expect(searchSettings("membrete", member)).toEqual([]);
    expect(searchSettings("nivel", member)).toEqual([]);
    expect(searchSettings("diccionario", directive)).toEqual([]);
    expect(searchSettings("invitar", member)[0].section).toBe("org");
  });

  it("dice dónde está cada resultado", () => {
    expect(searchSettings("logo", admin)[0].where).toBe("Actas · Membrete");
  });
});

describe("visibleSections", () => {
  it("cada uno ve sus grupos", () => {
    expect(visibleSections(member).map((section) => section.id)).toEqual(["my-voice", "my-drive", "privacy", "org", "drive"]);
    expect(visibleSections(directive).map((section) => section.group)).not.toContain("advanced");
    expect(visibleSections(admin)).toHaveLength(12);
  });
});

describe("resolvePath", () => {
  it("las rutas viejas siguen andando", () => {
    expect(resolvePath("my-drive")).toEqual({ section: "my-drive" });
    expect(resolvePath("ai")).toEqual({ section: "template", target: "minutes-language" });
    expect(resolvePath("notifications")).toEqual({ section: null });
    expect(resolvePath("")).toEqual({ section: null });
  });
});
