// theme.jsx — Pluck.ai design tokens and shared components

// ── Color themes ──
function getTheme(accent, mode) {
  accent = accent || '#22c55e';
  mode = mode || 'dark';

  const glows = {
    '#22c55e': { glow: 'rgba(34,197,94,0.10)', hover: '#2dd665' },
    '#8b5cf6': { glow: 'rgba(139,92,246,0.10)', hover: '#9d74f7' },
    '#06b6d4': { glow: 'rgba(6,182,212,0.10)', hover: '#22d3ee' },
    '#3b82f6': { glow: 'rgba(59,130,246,0.10)', hover: '#60a5fa' },
  };
  const a = glows[accent] || glows['#22c55e'];

  const shared = {
    accent, accentGlow: a.glow, accentHover: a.hover,
    fontUI: "'Space Grotesk', sans-serif",
    fontMono: "'JetBrains Mono', monospace",
    radius: 4,
    success: '#22c55e', successBg: 'rgba(34,197,94,0.1)',
    error: '#ef4444', errorBg: 'rgba(239,68,68,0.1)',
  };

  if (mode === 'light') {
    return {
      ...shared,
      bg: '#f0ede6', surface: '#faf8f4', elevated: '#ffffff',
      border: '#d0ccbe', textMuted: '#8a8678', text: '#5a5848', textBright: '#1c1b18',
      success: '#16a34a', successBg: 'rgba(22,163,74,0.08)',
      error: '#dc2626', errorBg: 'rgba(220,38,38,0.08)',
    };
  }
  return {
    ...shared,
    bg: '#080c08', surface: '#0f170f', elevated: '#162016',
    border: '#1c2c1c', textMuted: '#5a845a', text: '#8aaa8a', textBright: '#d0e4d0',
  };
}

// ── Transition wrapper ──
function FadeIn({ children, delay }) {
  return (
    <div style={{
      animation: `pluckFadeIn 0.45s ease ${delay || 0}ms both`,
      width: '100%', height: '100%',
    }}>
      {children}
    </div>
  );
}

Object.assign(window, { getTheme, FadeIn });
