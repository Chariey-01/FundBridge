import { isValidAmount } from "./money.ts";

/** Mirrors the server's create rules (routes.py create_campaign) so mistakes are caught before sending. */
export function validateCampaign(v: { title: string; description: string; category: string }) {
  const title = v.title.trim();
  const description = v.description.trim();
  return {
    title: title.length < 3 || title.length > 160 ? "Use 3 to 160 characters." : null,
    description: description.length < 20 ? `Write at least 20 characters (${description.length} so far).` : null,
    category: !v.category ? "Choose a category." : null,
  };
}

export function validateNewCampaign(v: { title: string; description: string; category: string; slug: string; goal: string; currency: string; beneficiaryId: string }) {
  return {
    ...validateCampaign(v),
    slug: /^[a-z0-9-]{3,180}$/.test(v.slug) ? null : "Use 3 to 180 lowercase letters, numbers or hyphens.",
    goal: isValidAmount(v.goal) ? null : "Enter a goal greater than zero, with at most two decimals.",
    currency: /^[A-Z]{3}$/.test(v.currency) ? null : "Choose a currency.",
    beneficiaryId: v.beneficiaryId.trim() ? null : "Enter the beneficiary reference from the onboarding agent.",
  };
}

export function slugify(title: string): string {
  return title.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80);
}

export const hasErrors = (e: Record<string, string | null>) => Object.values(e).some(Boolean);
