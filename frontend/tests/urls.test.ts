import { describe, expect, it } from "vitest";
import { safeNext } from "../src/lib/roleHome.ts";
import { safeHttpsUrl } from "../src/lib/urls.ts";

describe("links and redirects cannot leave the site unsafely", () => {
  it("accepts only https checkout links", () => {
    expect(safeHttpsUrl("https://www.sandbox.paypal.com/checkoutnow?token=O1")).toBe("https://www.sandbox.paypal.com/checkoutnow?token=O1");
    for (const bad of ["javascript:alert(1)", "JAVASCRIPT:alert(1)", "data:text/html,<script>x</script>", "http://paypal.com/x", "//evil.example", "/relative", "", null, undefined])
      expect(safeHttpsUrl(bad as string | null | undefined)).toBeNull();
  });

  it("accepts only same-site paths after sign-in", () => {
    expect(safeNext("/creator/campaigns/abc?x=1")).toBe("/creator/campaigns/abc?x=1");
    for (const bad of ["//evil.example", "/\\evil.example", "/\\/evil.example", "https://evil.example", "evil", "/a\nb", "/a\u0000", null])
      expect(safeNext(bad)).toBeNull();
  });
});
