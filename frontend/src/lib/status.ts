import type { Campaign, StatusPresentation, VerificationStatus } from "../api/client.ts";

export function presentCampaign(c: Pick<Campaign, "status" | "review_status">): StatusPresentation {
  if (c.status === "published") return { label: "Live, accepting donations", tone: "success", final: false };
  if (c.status === "submitted") return { label: "In review", tone: "pending", final: false };
  if (c.status === "closed") return { label: "Closed", tone: "neutral", final: true };
  if (c.review_status === "rejected") return { label: "Sent back by reviewer", tone: "failure", final: false };
  return { label: "Draft, not visible to donors", tone: "neutral", final: false };
}

const VERIFICATION: Record<VerificationStatus, StatusPresentation> = {
  unverified: { label: "Waiting for verification", tone: "pending", final: false },
  verified: { label: "Verified", tone: "success", final: true },
  reverification_required: { label: "Re-verification needed", tone: "pending", final: false },
  rejected: { label: "Verification declined", tone: "failure", final: true },
};

export function presentVerification(status: string): StatusPresentation {
  return VERIFICATION[status as VerificationStatus] ?? { label: `Unknown status (${status})`, tone: "neutral", final: false };
}

export const CATEGORIES: Record<string, string> = {
  medical: "Medical",
  education: "Education",
  emergency: "Emergency",
  community: "Community",
  agriculture: "Agriculture",
  small_business: "Small business",
  housing: "Housing",
  water_sanitation: "Water & sanitation",
  other: "Other",
};

export function categoryLabel(value: string): string {
  return CATEGORIES[value] ?? value.replace(/_/g, " ");
}
