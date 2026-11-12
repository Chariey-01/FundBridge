import { describe, expect, it } from "vitest";
import { formatMoney, isValidAmount, normaliseAmount, percentOf, toCents } from "../src/lib/money.ts";

describe("money is handled as decimal strings, never floats", () => {
  it("formats with grouping and two decimals", () => {
    expect(formatMoney("1234567.5", "USD")).toBe("USD 1,234,567.50");
    expect(formatMoney("0.10", "EUR")).toBe("EUR 0.10");
    expect(formatMoney("25", "USD")).toBe("USD 25.00");
  });

  it("keeps cents exact where floats would not", () => {
    expect(toCents("0.10") + toCents("0.20")).toBe(30n); // 0.1 + 0.2 !== 0.3 in floats
    expect(toCents("1999999999999.99")).toBe(199999999999999n);
  });

  it("computes progress from cents and clamps it", () => {
    expect(percentOf("250.00", "1000.00")).toBe(25);
    expect(percentOf("1500.00", "1000.00")).toBe(100);
    expect(percentOf("5.00", "0.00")).toBe(0);
  });

  it("accepts only positive amounts with at most two decimals", () => {
    for (const v of ["25", "25.5", "25.50", "0.01"]) expect(isValidAmount(v)).toBe(true);
    for (const v of ["0", "0.00", "-5", "1.234", "abc", "", "1e3", " "]) expect(isValidAmount(v)).toBe(false);
    expect(normaliseAmount("025.5")).toBe("25.50");
  });
});
