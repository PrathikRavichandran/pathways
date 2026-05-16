// Pathways logo: a young sprout (stem + two leaves + marigold bud) rising
// from a baseline. Says "growth from where you are" without being saccharine.
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
          <stop offset="0%" stopColor="#1F4A2C" />
          <stop offset="100%" stopColor="#133018" />
        </linearGradient>
      </defs>
      <rect width="256" height="256" rx="56" fill="url(#pw-bg)" />
      {withGlow && (
        <circle cx="128" cy="84" r="38" fill="#ECB13B" opacity="0.18" />
      )}
      {/* Soil line */}
      <line
        x1="56"
        y1="206"
        x2="200"
        y2="206"
        stroke="#FAF6E8"
        strokeWidth="4"
        strokeLinecap="round"
        opacity="0.45"
      />
      {/* Stem */}
      <path
        d="M 128 206 L 128 92"
        stroke="#FAF6E8"
        strokeWidth="8"
        strokeLinecap="round"
      />
      {/* Left leaf */}
      <path
        d="M 128 156 C 100 152, 76 132, 70 100 C 100 110, 124 128, 128 156 Z"
        fill="#FAF6E8"
      />
      {/* Right leaf */}
      <path
        d="M 128 140 C 156 136, 180 116, 186 84 C 156 94, 132 112, 128 140 Z"
        fill="#FAF6E8"
      />
      {/* Marigold bud */}
      <circle cx="128" cy="84" r="14" fill="#ECB13B" />
    </svg>
  );
}

export function LogoMarkOnSurface({ size = 40, className = "" }: Props) {
  // Variant rendered on light/dark surfaces (no card background).
  // Stem + leaves use currentColor so they inherit the surrounding text color.
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
      <circle cx="128" cy="84" r="38" fill="#ECB13B" opacity="0.16" />
      <line
        x1="56"
        y1="206"
        x2="200"
        y2="206"
        stroke="currentColor"
        strokeWidth="4"
        strokeLinecap="round"
        opacity="0.35"
      />
      <path
        d="M 128 206 L 128 92"
        stroke="currentColor"
        strokeWidth="8"
        strokeLinecap="round"
      />
      <path
        d="M 128 156 C 100 152, 76 132, 70 100 C 100 110, 124 128, 128 156 Z"
        fill="currentColor"
      />
      <path
        d="M 128 140 C 156 136, 180 116, 186 84 C 156 94, 132 112, 128 140 Z"
        fill="currentColor"
      />
      <circle cx="128" cy="84" r="14" fill="#ECB13B" />
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
