import { describe, expect, it } from "vitest";
import { formatChf } from "./format";

describe("formatChf", () => {
  it("includes the CHF symbol and the integer part of the amount", () => {
    const result = formatChf("50000");

    expect(result).toContain("CHF");
    expect(result).toContain("50");
    expect(result).toContain("000");
  });

  it("formats null as an em dash placeholder", () => {
    expect(formatChf(null)).toBe("–");
  });

  it("rounds to two decimal places", () => {
    const result = formatChf("12.5");

    expect(result).toContain("12");
    expect(result).toContain("50");
  });
});
