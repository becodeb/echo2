import { describe, expect, it } from "vitest";
import { addDays, dayLabel, isoDay, monthGrid, nextMeetingIn, parseDay, weekStart } from "./agenda";

describe("fechas de la agenda", () => {
  it("van en hora local, sin correrse de día", () => {
    expect(isoDay(new Date(2026, 10, 2, 23, 59))).toBe("2026-11-02");
    expect(parseDay("2026-11-02").getDate()).toBe(2);
    expect(addDays("2026-10-30", 3)).toBe("2026-11-02");
  });

  it("la semana empieza el lunes", () => {
    expect(weekStart("2026-11-02")).toBe("2026-11-02");
    expect(weekStart("2026-11-08")).toBe("2026-11-02");
    expect(dayLabel("2026-11-02")).toBe("Lunes 2 de noviembre");
  });

  it("la grilla del mes son semanas completas", () => {
    const grid = monthGrid("2026-11-15");
    expect(grid[0][0]).toEqual({ iso: "2026-10-26", inMonth: false });
    expect(grid[0][6]).toEqual({ iso: "2026-11-01", inMonth: true });
    expect(grid.at(-1)?.at(-1)?.iso).toBe("2026-12-06");
  });
});

describe("nextMeetingIn", () => {
  it("encuentra la frase y el día", () => {
    const acta = "# Acta\n\nLa docente comenta.\n\nSe acuerda una nueva reunión en dos semanas para ver cómo sigue.";
    expect(nextMeetingIn(acta, "2026-11-02")).toEqual({
      sentence: "Se acuerda una nueva reunión en dos semanas para ver cómo sigue.",
      date: "2026-11-16",
    });
    expect(nextMeetingIn("Volver a reunirse la semana que viene.", "2026-11-02")?.date).toBe("2026-11-09");
    // Sin plazo: dos semanas; si cae en fin de semana, el lunes.
    expect(nextMeetingIn("Habrá otra reunión.", "2026-11-04")?.date).toBe("2026-11-18");
    expect(nextMeetingIn("Nueva reunión en 4 días.", "2026-11-05")?.date).toBe("2026-11-09");
    // Un mes con nombre: el primer día hábil de ese mes.
    expect(nextMeetingIn("Se acuerda volver a reunirse en diciembre.", "2026-11-02")?.date).toBe("2026-12-01");
    expect(nextMeetingIn("Nueva reunión en marzo.", "2026-11-02")?.date).toBe("2027-03-01");
  });

  it("sin acuerdo de volver a reunirse, nada", () => {
    expect(nextMeetingIn("La familia cuenta que en casa repasan juntos.", "2026-11-02")).toBeNull();
  });
});
