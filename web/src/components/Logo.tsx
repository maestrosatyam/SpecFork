/** SpecFork glyph: one line of spec forking into three meanings. */
export function LogoGlyph({ size = 34 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden>
      <rect x="0.5" y="0.5" width="39" height="39" rx="11" fill="#0f152a" stroke="rgba(255,255,255,0.12)" />
      <path d="M7 20h8.5" stroke="#e7ecf5" strokeWidth="2.6" strokeLinecap="round" />
      <path d="M15.5 20c4.5 0 5-8 10-8h4" stroke="#56B4E9" strokeWidth="2.6" strokeLinecap="round" fill="none" />
      <path d="M15.5 20h14" stroke="#F5A524" strokeWidth="2.6" strokeLinecap="round" />
      <path d="M15.5 20c4.5 0 5 8 10 8h4" stroke="#2FC79E" strokeWidth="2.6" strokeLinecap="round" fill="none" />
      <circle cx="7" cy="20" r="2.6" fill="#e7ecf5" />
      <circle cx="31" cy="12" r="2.3" fill="#56B4E9" />
      <circle cx="31" cy="20" r="2.3" fill="#F5A524" />
      <circle cx="31" cy="28" r="2.3" fill="#2FC79E" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <span className="font-display text-[22px] font-bold tracking-[-0.02em] text-fog-50">
      Spec<span className="text-fog-400">Fork</span>
    </span>
  );
}
