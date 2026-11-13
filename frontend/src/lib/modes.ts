import { channelModes, type ChannelMode, type IntegrationStatus } from "../api/client.ts";

/** GET /api/v1/public/config */
export interface PublicConfig {
  payments: { paypal: { mode: string } };
  payouts: { provider: string; mode: string };
  feature_phone?: { sms: boolean; ussd: boolean };
}

export interface ModeLabel { key: string; channel: string; mode: ChannelMode; label: string; detail: string }

/**
 * PayPal. Today the backend reports "sandbox" whenever a client id is configured, including when
 * PAYPAL_BASE_URL points at a local stand-in (release audit AUD-11), so "sandbox" is shown as
 * "test mode" without claiming it is PayPal's own Sandbox. "local_standin" and "live" are the values
 * proposed to the backend so the two can be told apart; until it sends them, they never appear.
 */
export function paypalMode(mode: string | undefined): ModeLabel {
  const base = { key: "paypal", channel: "Donations" };
  switch (mode) {
    case "live":
      return { ...base, mode: "live", label: "PayPal (live payments)", detail: "Donations are real PayPal payments." };
    case "local_standin":
      return { ...base, mode: "simulated", label: "Local PayPal stand-in, not PayPal",
        detail: "Orders and captures are answered by a local test double. No money moves and PayPal is never contacted." };
    case "sandbox":
      return { ...base, mode: "sandbox", label: "PayPal test mode, no real money",
        detail: "The server uses test credentials, so no real money moves. It does not yet report whether these reach PayPal's Sandbox or a local stand-in." };
    case "unconfigured":
      return { ...base, mode: "unconfigured", label: "Donations unavailable",
        detail: "No payment provider is configured on the server, so donations cannot be taken." };
    default:
      return { ...base, mode: "unconfigured", label: "Payment mode unknown",
        detail: "The server's payment mode could not be read. Donations should not be treated as real." };
  }
}

export function payoutMode(config: PublicConfig | null): ModeLabel {
  const base = { key: "payouts", channel: "Payouts" };
  if (!config) return { ...base, mode: "unconfigured", label: "Payout mode unknown", detail: "The server's payout mode could not be read." };
  if (config.payouts.mode === "simulator")
    return { ...base, mode: "simulated", label: "Payouts simulated, no money is sent",
      detail: "Payout requests are reviewed for real, but no transfer to a mobile money account is made. An approved payout stays “being prepared”." };
  if (config.payouts.mode === "live")
    return { ...base, mode: "live", label: "Payouts to mobile money", detail: "Approved payouts are sent to the beneficiary's wallet." };
  return { ...base, mode: "unconfigured", label: "Payouts not configured", detail: "No payout provider is configured, so no money can be sent." };
}

/** All channels the UI mentions, in display order. Anything not "live" is shown as such. */
export function environmentModes(config: PublicConfig | null, status: IntegrationStatus | null): ModeLabel[] {
  const out: ModeLabel[] = [paypalMode(config?.payments.paypal.mode), payoutMode(config)];
  if (status) {
    const ch = channelModes(status, config?.payouts.provider ?? "");
    out.push({ key: "sms", channel: "SMS", ...ch.sms,
      detail: ch.sms.mode === "live"
        ? "Messages are handed to Africa's Talking. Delivery to the handset is not confirmed by FundBridge."
        : "Messages are recorded on the server only. They are not delivered to any phone." });
    out.push({ key: "ussd", channel: "USSD", ...ch.ussd,
      detail: ch.ussd.mode === "live" ? "The USSD code is verified on a live network." : "The USSD menu has not been verified on a live mobile network." });
    out.push({ key: "ai", channel: "AI help", ...ch.ai,
      detail: ch.ai.mode === "live" ? "Suggestions come from an AI model and must be reviewed. AI never approves, pays or changes balances." : "AI suggestions are off; FundBridge uses fixed templates." });
  }
  return out;
}

export function isTestEnvironment(modes: ModeLabel[]): boolean {
  return modes.some((m) => m.mode !== "live");
}
