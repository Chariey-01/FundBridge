/**
 * The single entry point to the backend. The typed client in ../contracts is the API contract shared
 * with the backend's live client tests; this file only adapts it to the browser.
 */
export {
  ApiError,
  FundBridgeClient,
  channelModes,
  presentDonation,
  presentPayout,
} from "../../../contracts/fundbridge-client.ts";
export type {
  AccountSummary,
  BeneficiaryProfile,
  Campaign,
  CampaignFunds,
  CampaignInput,
  CampaignStatus,
  ChannelLabel,
  ChannelMode,
  Donation,
  DonationOrder,
  PayPalReturnOutcome,
  Payout,
  Role,
  StatusPresentation,
  Tone,
  VerificationStatus,
} from "../../../contracts/fundbridge-client.ts";
export type { DonationStatus, IntegrationStatus, PayoutStatus } from "../../../contracts/ai-messaging.types.ts";

/** Same origin by default: the dev/preview servers proxy /api to the Flask backend. */
export function apiBaseUrl(): string {
  const configured = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
  return configured ? configured.replace(/\/$/, "") : window.location.origin;
}
