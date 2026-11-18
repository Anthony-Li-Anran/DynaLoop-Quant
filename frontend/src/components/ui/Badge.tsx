import type { HTMLAttributes } from "react";

type BadgeProps = HTMLAttributes<HTMLSpanElement> & {
  tone?: "neutral" | "cyan" | "green" | "amber" | "red";
};

const tones = {
  neutral: "border-line bg-elevated text-muted",
  cyan: "border-blue-400/10 bg-blue-400/10 text-blue-300",
  green: "border-emerald-500/25 bg-emerald-500/10 text-emerald-300",
  amber: "border-amber-500/25 bg-amber-500/10 text-amber-300",
  red: "border-rose-500/25 bg-rose-500/10 text-rose-300",
};

export function Badge({ tone = "neutral", className = "", ...props }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium tracking-wide ${tones[tone]} ${className}`}
      {...props}
    />
  );
}
