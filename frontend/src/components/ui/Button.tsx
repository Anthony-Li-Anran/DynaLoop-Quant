import type { ButtonHTMLAttributes } from "react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
  size?: "default" | "sm";
};

const variants = {
  primary: "border-accent bg-accent text-canvas hover:bg-amber-200",
  secondary: "border-line bg-elevated text-ink hover:border-muted",
  ghost: "border-transparent bg-transparent text-muted hover:bg-elevated hover:text-ink",
};

export function Button({
  variant = "secondary",
  size = "default",
  className = "",
  ...props
}: ButtonProps) {
  const sizing = size === "sm" ? "min-h-8 px-3 text-xs" : "min-h-10 px-4 text-sm";
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-md border font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50 ${sizing} ${variants[variant]} ${className}`}
      {...props}
    />
  );
}
