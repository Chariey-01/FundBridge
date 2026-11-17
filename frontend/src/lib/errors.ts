import { ApiError } from "../api/client.ts";

export interface ErrorView { title: string; message: string; requestId: string | null; retryAfter: number | null; code: string }

const MESSAGES: Record<string, [string, string]> = {
  INVALID_CREDENTIALS: ["Sign-in failed", "The email or password is incorrect."],
  ACCOUNT_ALREADY_EXISTS: ["Account exists", "An account with this email already exists. Sign in instead."],
  AUTH_REQUIRED: ["Sign in required", "Please sign in to continue."],
  TOKEN_EXPIRED: ["Session ended", "Your session expired. Please sign in again."],
  INVALID_TOKEN: ["Session ended", "Please sign in again."],
  ACCOUNT_INACTIVE: ["Account inactive", "This account is no longer active."],
  FORBIDDEN: ["Not allowed", "Your account does not have permission for this action."],
  NOT_FOUND: ["Not found", "This item does not exist or is not visible to you."],
  RATE_LIMITED: ["Too many attempts", "Please wait before trying again."],
  VALIDATION_ERROR: ["Check the form", "Some details were rejected by the server. Check each field and try again."],
  SLUG_ALREADY_EXISTS: ["Web address taken", "Another campaign already uses this web address. Choose a different one."],
  BENEFICIARY_NOT_FOUND: ["Beneficiary not found", "No beneficiary profile matches this reference."],
  BENEFICIARY_NOT_VERIFIED: ["Not verified yet", "Payouts are available only after a reviewer verifies the beneficiary."],
  BENEFICIARY_ACCOUNT_NOT_ELIGIBLE: ["Account not eligible", "The linked account must be active and have the beneficiary role."],
  BENEFICIARY_PROFILE_EXISTS: ["Already onboarded", "That account already has a beneficiary profile."],
  PAYOUT_DESTINATION_UNVERIFIED: ["No payout destination", "A payout destination must be on file before a payout can be requested."],
  INSUFFICIENT_AVAILABLE_FUNDS: ["Not enough available funds", "The amount is more than this campaign's available balance."],
  IDEMPOTENCY_KEY_REUSED: ["Request changed", "This request changed while being retried. Start again."],
  CAMPAIGN_NOT_AVAILABLE: ["Campaign unavailable", "This campaign is not accepting donations."],
  PAYMENT_PROVIDER_UNCONFIGURED: ["Donations unavailable", "No payment provider is configured on the server. Nothing was charged."],
  PROVIDER_UNAVAILABLE: ["PayPal is not responding", "Nothing has been confirmed. Try again in a moment; retrying will not create a second donation."],
  PROVIDER_REQUEST_REJECTED: ["PayPal declined the request", "Nothing has been confirmed."],
  SELF_REVIEW_FORBIDDEN: ["Not allowed", "You cannot review a campaign you created."],
  SELF_APPROVAL_FORBIDDEN: ["Not allowed", "You cannot approve a payout you requested."],
  SELF_VERIFICATION_FORBIDDEN: ["Not allowed", "You cannot verify your own beneficiary profile."],
  SELF_ROLE_CHANGE_FORBIDDEN: ["Not allowed", "You cannot change your own role."],
  PROFILE_CHANGED: ["Profile changed", "This profile changed after you opened it. It has been reloaded; review it again."],
  INVALID_CAMPAIGN_TRANSITION: ["Already decided", "This campaign is no longer waiting for review. The list has been refreshed."],
  INVALID_PAYOUT_TRANSITION: ["Already decided", "This payout is no longer waiting for review. The list has been refreshed."],
  INVALID_DONATION_TRANSITION: ["Cannot continue", "This donation cannot be confirmed from its current state."],
  INTERNAL_ERROR: ["Something went wrong", "The server hit an error. Nothing was confirmed."],
};

export function describeError(error: unknown): ErrorView {
  if (error instanceof ApiError) {
    const known = MESSAGES[error.code];
    const requestId = error.requestId ?? (typeof error.details["request_id"] === "string" ? (error.details["request_id"] as string) : null);
    if (known) return { title: known[0], message: known[1], requestId, retryAfter: error.retryAfterSeconds, code: error.code };
    if (error.status >= 500)
      return { title: "Something went wrong", message: "The server could not complete this request. Nothing was confirmed.", requestId, retryAfter: null, code: error.code };
    return { title: "Request not completed", message: error.message || "The server rejected this request.", requestId, retryAfter: error.retryAfterSeconds, code: error.code };
  }
  return { title: "Connection problem", message: "The FundBridge server could not be reached. Nothing was confirmed.", requestId: null, retryAfter: null, code: "NETWORK" };
}
