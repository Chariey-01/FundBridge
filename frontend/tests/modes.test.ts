import { describe, expect, it } from "vitest";
import { environmentModes, isTestEnvironment, paypalMode, payoutMode } from "../src/lib/modes.ts";
import { INTEGRATIONS, PUBLIC_CONFIG } from "./helpers.tsx";

describe("environment labels never overstate what is real", () => {
  it("does not claim PayPal's own Sandbox when the server only says 'sandbox' (AUD-11)", () => {
    const m = paypalMode("sandbox");
    expect(m.mode).toBe("sandbox");
    expect(m.label).toMatch(/test mode, no real money/i);
    expect(m.detail).toMatch(/does not yet report whether .* PayPal's Sandbox or a local stand-in/);
  });

  it("labels a local stand-in as not PayPal, and unknown modes as not real", () => {
    expect(paypalMode("local_standin").label).toMatch(/not PayPal/);
    expect(paypalMode("local_standin").mode).toBe("simulated");
    expect(paypalMode(undefined).mode).toBe("unconfigured");
    expect(paypalMode("unconfigured").label).toBe("Donations unavailable");
  });

  it("labels simulated payouts and simulated SMS", () => {
    expect(payoutMode(PUBLIC_CONFIG).label).toBe("Payouts simulated, no money is sent");
    const modes = environmentModes(PUBLIC_CONFIG, INTEGRATIONS as never);
    const sms = modes.find((m) => m.key === "sms")!;
    expect(sms.mode).toBe("simulated");
    expect(sms.detail).toMatch(/not delivered to any phone/);
    expect(modes.find((m) => m.key === "ussd")!.label).toMatch(/not yet verified on a live network/);
    expect(isTestEnvironment(modes)).toBe(true);
  });

  it("even live SMS is not presented as confirmed delivery", () => {
    const live = { ...INTEGRATIONS, messaging: { ...INTEGRATIONS.messaging, sms: { provider: "africastalking", mode: "africastalking_live", delivery_confirmed: false } } };
    expect(environmentModes(PUBLIC_CONFIG, live as never).find((m) => m.key === "sms")!.detail).toMatch(/not confirmed/);
  });
});
