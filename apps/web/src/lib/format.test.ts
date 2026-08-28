import { describe, expect, it } from "vitest";
import { formatDuration, formatMs } from "../components/ui";

describe("formatMs", () => {
  it("formatea mm:ss", () => {
    expect(formatMs(0)).toBe("00:00");
    expect(formatMs(65_000)).toBe("01:05");
  });
  it("formatea hh:mm:ss", () => {
    expect(formatMs(3_725_000)).toBe("01:02:05");
  });
  it("tolera null", () => {
    expect(formatMs(null)).toBe("--:--");
    expect(formatMs(undefined)).toBe("--:--");
  });
});

describe("formatDuration", () => {
  it("minutos", () => {
    expect(formatDuration(0)).toBe("0 min");
    expect(formatDuration(300)).toBe("5 min");
  });
  it("horas", () => {
    expect(formatDuration(5400)).toBe("1 h 30 min");
  });
});
