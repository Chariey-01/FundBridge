/**
 * Shared types for FundBridge AI, feature-phone and integration-status endpoints.
 * Source of truth: backend/app/api/v1/ai.py, backend/app/api/v1/messaging.py,
 * backend/app/services/ai/schemas.py. See docs/integration/ai-messaging-api.md.
 * Money is always a decimal string, never a JS number.
 */

export interface Money { amount: string; currency: string }

export interface ApiSuccess<T, M = Record<string, unknown>> { data: T; meta: M }
export interface ApiError {
  error: { code: ErrorCode | string; message: string; details: Record<string, string[] | number> };
}
export type ErrorCode =
  | "VALIDATION_ERROR" | "AUTH_REQUIRED" | "INVALID_TOKEN" | "TOKEN_EXPIRED" | "ACCOUNT_INACTIVE"
  | "FORBIDDEN" | "NOT_FOUND" | "PAYLOAD_TOO_LARGE"
  | "RATE_LIMITED" | "AI_UNAVAILABLE" | "INVALID_CALLBACK" | "MESSAGING_NOT_CONFIGURED";

export type LanguageCode = "en" | "sw" | "fr" | "ar" | "es" | "pt" | "am" | "so" | "ha" | "yo" | "lg" | "rw" | "zu";
export type CampaignCategory =
  | "medical" | "education" | "emergency" | "community" | "agriculture"
  | "small_business" | "housing" | "water_sanitation" | "other";
export type AssistantAction =
  | "view_campaign_status" | "view_payout_status" | "contact_community_agent" | "edit_campaign_draft"
  | "verify_phone_number" | "learn_about_fees" | "learn_about_payouts" | "learn_about_donating";

/** Shared payout state machine (core backend PayoutStatus). Only "succeeded" means money arrived. */
export type PayoutStatus =
  | "requested" | "under_review" | "rejected" | "approved_for_submission"
  | "submitted" | "pending_confirmation" | "failed" | "succeeded";
/** Core backend DonationStatus. Only "completed" may be shown as a successful donation. */
export type DonationStatus =
  | "created" | "pending" | "completed" | "failed" | "cancelled" | "refunded" | "partially_refunded";

export interface AIMeta {
  provider: "openai" | "fallback" | "none" | string;
  model: string | null;
  ai_generated: boolean;
  /** true when a configured provider failed and a deterministic fallback answered */
  degraded: boolean;
  fallback_reason?: string;
  output_replaced_by_guardrail?: boolean;
}

// POST /api/v1/ai/campaign-draft (auth)
export interface CampaignDraftRequest {
  story_notes: string; // 20-3000 chars
  category?: CampaignCategory | null;
  beneficiary_first_name?: string | null;
  location?: string | null;
  goal?: Money | null;
  language?: LanguageCode;
}
export interface CampaignDraft {
  title: string; summary: string; story: string;
  suggested_category: CampaignCategory;
  missing_information: string[];
  warnings: string[];
  language: LanguageCode;
  requires_human_review: true;
  disclaimer: string;
}

// POST /api/v1/ai/translate (public; 503 AI_UNAVAILABLE without a model)
export interface TranslateRequest { text: string; target_language: LanguageCode; source_language?: LanguageCode | null }
export interface Translation {
  translated_text: string; source_language: LanguageCode | null; target_language: LanguageCode;
  machine_translation: boolean; notice: string | null; warnings?: string[];
}

// POST /api/v1/ai/beneficiary-assistant (auth)
export interface AssistantRequest {
  message: string; // ≤1000 chars
  language?: LanguageCode;
  topic?: "general" | "payouts" | "campaign" | "account" | "donations";
}
export interface AssistantReply {
  reply: string; language: LanguageCode; suggested_actions: AssistantAction[];
  escalate_to_human: boolean; notice: string;
}

// POST /api/v1/ai/campaign-search (public)
export interface CampaignSearchRequest { query: string; language?: LanguageCode; limit?: number }
export interface PublicCampaignSummary {
  id: string; slug: string; title: string; summary: string; category: string;
  country_code: string | null; goal: Money; raised: Money;
}
export interface CampaignSearchResult {
  interpreted_filters: { keywords: string[]; category: CampaignCategory | null; country_code: string | null };
  filters_relaxed: boolean;
  results: PublicCampaignSummary[];
}

// GET /api/v1/integrations/status (public)
export interface AIStatus {
  provider: string; model: string | null; mode: "live" | "fallback_only";
  features: Record<"campaign_draft" | "translate" | "beneficiary_assistant" | "campaign_search", string>;
  supported_languages: Record<LanguageCode, string>;
  /** true only after a real provider call succeeded in this server process; "live" alone means configured */
  model_verified: boolean;
  last_success_at: string | null;
  last_error: { code: string; feature: string; at: string } | null;
}
export interface MessagingStatus {
  sms: { provider: string; mode: "simulated" | "africastalking_sandbox" | "africastalking_live"; delivery_confirmed: false };
  ussd: { service_code: string; callback_configured: boolean; live_shortcode_verified: boolean };
  simulator_enabled: boolean; notifications_enabled: boolean; sms_assistant: "ai" | "rule_based";
}
export interface IntegrationStatus { ai: AIStatus; messaging: MessagingStatus }

// Simulator (MESSAGING_SIMULATOR_ENABLED=true only); meta.simulated is always true.
export interface SimulatorMeta { simulated: true; notice: string }
export interface SimulatorUssdRequest { phone_number: string; text: string; session_id?: string }
export interface SimulatorUssdReply { response: string; text: string; session_ended: boolean }
export interface SimulatorSmsReply { replies: string[]; to: string }
export interface SimulatedSms { id: string; to: string; message: string; status: "simulated"; created_at: string }

// Staff
export interface SupportRequest {
  id: string; reference: string; phone_number: string; beneficiary_id: string | null;
  channel: "ussd" | "sms" | "web"; topic: "callback" | "problem" | "sim_change";
  priority: "normal" | "high"; status: string; created_at: string;
}

/** English labels shared with the USSD/SMS channel (backend/app/services/messaging/i18n.py). */
export const PAYOUT_STATUS_LABEL_EN: Record<PayoutStatus, string> = {
  requested: "Requested, waiting for review",
  under_review: "Under review",
  rejected: "Not approved. Contact your agent",
  approved_for_submission: "Approved, being prepared",
  submitted: "Sent to the mobile money provider, awaiting confirmation",
  pending_confirmation: "Awaiting confirmation. Do not request again",
  succeeded: "Paid to your mobile money account",
  failed: "Not completed. Your agent will help you",
};
