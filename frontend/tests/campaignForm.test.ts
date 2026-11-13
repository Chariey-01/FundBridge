import { describe, expect, it } from "vitest";
import { hasErrors, slugify, validateCampaign, validateNewCampaign } from "../src/lib/campaignForm.ts";

describe("campaign form mirrors the server's create rules", () => {
  const good = { title: "Clean water for Kibera", description: "A borehole for 300 families in the settlement.", category: "water_sanitation", slug: "clean-water-kibera", goal: "1500", currency: "USD", beneficiaryId: "b-1" };

  it("accepts a valid campaign", () => expect(hasErrors(validateNewCampaign(good))).toBe(false));

  it("rejects short descriptions, long titles, bad slugs and goals", () => {
    const e = validateNewCampaign({ ...good, title: "x".repeat(161), description: "too short", slug: "Bad Slug", goal: "0", beneficiaryId: " " });
    expect(e.title).toBeTruthy();
    expect(e.description).toMatch(/at least 20/);
    expect(e.slug).toBeTruthy();
    expect(e.goal).toBeTruthy();
    expect(e.beneficiaryId).toBeTruthy();
  });

  it("applies the same rules when editing", () => {
    expect(validateCampaign({ title: "Ok title", description: "short", category: "medical" }).description).toBeTruthy();
  });

  it("builds a URL-safe slug", () => expect(slugify("Água limpa — Kibera 2026!")).toBe("agua-limpa-kibera-2026"));
});
