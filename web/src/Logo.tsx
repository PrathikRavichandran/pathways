// Pathways logo: a rising path terminating in a coral sun.
// Composable mark and wordmark. Both respect dark mode via CSS vars.

type Props = {
  size?: number;
  className?: string;
  withGlow?: boolean;
};

export function LogoMark({ size = 40, className = "", withGlow = true }: Props) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 256 256"
      width={size}
      height={size}
      className={className}
      aria-hidden="true"
      fill="none"
    >
      <defs>
        <linearGradient id="pw-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#0D5C4F" />
          <stop offset="100%" stopColor="#0A4A40" />
        </linearGradient>
      </defs>
      <rect width="256" height="256" rx="56" fill="url(#pw-bg)" />
      {withGlow && (
        <circle cx="200" cy="76" r="48" fill="#E08566" opacity="0.18" />
      )}
      <path
        d="M 44 196 C 82 196, 108 168, 132 140 S 178 88, 200 76"
        stroke="#FAF7F2"
        strokeWidth="22"
        strokeLinecap="round"
      />
      <circle cx="200" cy="76" r="26" fill="#E08566" />
    </svg>
  );
}

export function LogoMarkOnSurface({ size = 40, className = "" }: Props) {
  // Variant rendered on light/dark surfaces (no card background).
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 256 256"
      width={size}
      height={size}
      className={className}
      aria-hidden="true"
      fill="none"
    >
      <circle cx="200" cy="76" r="48" fill="#E08566" opacity="0.16" />
      <path
        d="M 44 196 C 82 196, 108 168, 132 140 S 178 88, 200 76"
        stroke="currentColor"
        strokeWidth="22"
        strokeLinecap="round"
      />
      <circle cx="200" cy="76" r="26" fill="#E08566" />
    </svg>
  );
}

export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span
      className={
        "font-display text-2xl font-semibold tracking-tight " + className
      }
      style={{ letterSpacing: "-0.01em" }}
    >
      Pathways
    </span>
  );
}
