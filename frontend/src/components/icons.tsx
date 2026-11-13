import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement>;
const base = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true } as const;

export const CheckIcon = (p: P) => <svg {...base} {...p}><circle cx="12" cy="12" r="9" /><path d="m8 12.5 2.6 2.6L16 9.6" /></svg>;
export const ClockIcon = (p: P) => <svg {...base} {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>;
export const AlertIcon = (p: P) => <svg {...base} {...p}><path d="M12 3 2 20h20L12 3Z" /><path d="M12 10v4M12 17h.01" /></svg>;
export const InfoIcon = (p: P) => <svg {...base} {...p}><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></svg>;
export const MinusIcon = (p: P) => <svg {...base} {...p}><circle cx="12" cy="12" r="9" /><path d="M8 12h8" /></svg>;
export const ArrowIcon = (p: P) => <svg {...base} {...p}><path d="M5 12h14M13 6l6 6-6 6" /></svg>;
export const MenuIcon = (p: P) => <svg {...base} {...p}><path d="M4 7h16M4 12h16M4 17h16" /></svg>;

export function BrandMark(p: P) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" {...p}>
      <rect width="32" height="32" rx="7" fill="#1A2940" />
      <path d="M5 21c4-7 18-7 22 0" fill="none" stroke="#E7B86A" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M5 23.5h22" stroke="#F7F5EF" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M10 23.5v-4.2M16 23.5v-6.5M22 23.5v-4.2" stroke="#16856B" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}
