// directions.jsx — 4 visual directions for Pluck.ai

const SAMPLE_ROWS = [
  { name: 'Wireless Headphones Pro', price: '$79.99', stock: true },
  { name: 'USB-C Hub 7-in-1', price: '$34.99', stock: true },
  { name: 'Mechanical Keyboard RGB', price: '$149.99', stock: false },
];

/* ── Shared palette strip ── */
function PaletteStrip({ colors, fontLabel, borderColor, textColor }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '20px 36px', borderTop: `1px solid ${borderColor}` }}>
      <div style={{ display: 'flex', gap: 8 }}>
        {colors.map((c, i) => (
          <div key={i} style={{ width: 26, height: 26, background: c, border: `1px solid ${borderColor}`, borderRadius: 3 }} />
        ))}
      </div>
      <div style={{ fontSize: 11, color: textColor, fontFamily: 'inherit', letterSpacing: '0.02em' }}>
        {fontLabel}
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════
   DIRECTION 1 — TERMINAL
   Hacker-minimal. Green on black. Monospace.
   ════════════════════════════════════════════ */
function TerminalDirection() {
  const c = { bg: '#060a06', surface: '#0c140c', border: '#182818', text: '#6a946a', bright: '#c8e0c8', accent: '#22c55e' };

  const cellStyle = { padding: '9px 14px', fontSize: 12, fontFamily: "'JetBrains Mono', monospace", borderBottom: `1px solid ${c.border}` };

  return (
    <div style={{ background: c.bg, color: c.bright, fontFamily: "'Space Grotesk', sans-serif", width: 880, height: 880, display: 'flex', flexDirection: 'column' }}>
      {/* Label */}
      <div style={{ padding: '24px 36px 0', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ fontSize: 11, fontFamily: "'JetBrains Mono'", color: c.text, letterSpacing: '0.1em', textTransform: 'uppercase' }}>Direction 01</div>
        <div style={{ fontSize: 11, fontFamily: "'JetBrains Mono'", color: c.text }}>Hacker-minimal · Monospace precision</div>
      </div>

      {/* Nav */}
      <div style={{ margin: '16px 36px 0', padding: '14px 0', borderBottom: `1px solid ${c.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontFamily: "'JetBrains Mono'", fontSize: 17, fontWeight: 500, letterSpacing: '-0.01em' }}>
          pluck<span style={{ color: c.accent }}>.</span>ai
        </div>
        <div style={{ display: 'flex', gap: 24, fontFamily: "'JetBrains Mono'", fontSize: 12, color: c.text }}>
          <span style={{ color: c.bright }}>extract</span>
          <span>history</span>
          <span>settings</span>
        </div>
      </div>

      {/* Main */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '0 60px', marginTop: -20 }}>
        <h1 style={{ fontSize: 30, fontWeight: 600, textAlign: 'center', marginBottom: 8, lineHeight: 1.35, letterSpacing: '-0.02em' }}>
          Extract structured data<br />from any URL
        </h1>
        <p style={{ fontSize: 14, color: c.text, marginBottom: 36, fontFamily: "'JetBrains Mono'", textAlign: 'center' }}>
          paste a url → get a table
        </p>

        {/* URL Input */}
        <div style={{ width: '100%', maxWidth: 620, background: c.surface, border: `1px solid ${c.border}`, display: 'flex', alignItems: 'center', padding: '4px 4px 4px 18px' }}>
          <span style={{ fontFamily: "'JetBrains Mono'", color: c.accent, fontSize: 15, marginRight: 10 }}>›</span>
          <div style={{ flex: 1, fontFamily: "'JetBrains Mono'", fontSize: 14, color: c.bright, padding: '11px 0' }}>
            https://example.com/products
          </div>
          <button style={{ background: c.accent, color: c.bg, fontFamily: "'Space Grotesk'", fontWeight: 600, fontSize: 13, padding: '11px 24px', border: 'none', cursor: 'pointer', letterSpacing: '0.01em' }}>
            Extract
          </button>
        </div>

        <div style={{ marginTop: 14, fontSize: 12, color: c.text, fontFamily: "'JetBrains Mono'" }}>
          optional: <span style={{ color: c.accent, textDecoration: 'underline', textUnderlineOffset: 3 }}>upload schema</span>
        </div>

        {/* Classification */}
        <div style={{ marginTop: 36, background: c.surface, border: `1px solid ${c.border}`, padding: '12px 20px', fontFamily: "'JetBrains Mono'", fontSize: 12, color: c.text, display: 'flex', gap: 14, alignItems: 'center' }}>
          <span style={{ color: c.accent }}>■</span>
          <span>e-commerce</span>
          <span style={{ color: c.border }}>│</span>
          <span>product_listing</span>
          <span style={{ color: c.border }}>│</span>
          <span>~24 fields detected</span>
        </div>

        {/* Mini table */}
        <div style={{ marginTop: 28, width: '100%', maxWidth: 620, border: `1px solid ${c.border}` }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: c.surface }}>
                <th style={{ ...cellStyle, color: c.text, fontWeight: 500, textAlign: 'left' }}>name</th>
                <th style={{ ...cellStyle, color: c.text, fontWeight: 500, textAlign: 'right' }}>price</th>
                <th style={{ ...cellStyle, color: c.text, fontWeight: 500, textAlign: 'center' }}>in_stock</th>
              </tr>
            </thead>
            <tbody>
              {SAMPLE_ROWS.map((r, i) => (
                <tr key={i}>
                  <td style={{ ...cellStyle, color: c.bright, textAlign: 'left' }}>{r.name}</td>
                  <td style={{ ...cellStyle, color: c.accent, textAlign: 'right' }}>{r.price}</td>
                  <td style={{ ...cellStyle, color: r.stock ? c.text : '#6b3030', textAlign: 'center' }}>{r.stock ? 'true' : 'false'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <PaletteStrip
        colors={[c.bg, c.surface, c.border, c.text, c.bright, c.accent]}
        fontLabel="Space Grotesk · JetBrains Mono"
        borderColor={c.border}
        textColor={c.text}
      />
    </div>
  );
}


/* ════════════════════════════════════════════
   DIRECTION 2 — OBSIDIAN
   Premium dark SaaS. Warm amber accent.
   ════════════════════════════════════════════ */
function ObsidianDirection() {
  const c = { bg: '#101012', surface: '#1a1a1e', surfaceAlt: '#1f1f24', border: '#2a2a30', text: '#8a8a96', bright: '#ededf2', accent: '#e8834a', accentHover: '#f0955e' };

  const cellStyle = { padding: '10px 14px', fontSize: 13, fontFamily: "'Outfit', sans-serif", borderBottom: `1px solid ${c.border}` };

  return (
    <div style={{ background: c.bg, color: c.bright, fontFamily: "'Outfit', sans-serif", width: 880, height: 880, display: 'flex', flexDirection: 'column' }}>
      {/* Label */}
      <div style={{ padding: '24px 36px 0', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ fontSize: 11, fontFamily: "'Fira Code'", color: c.text, letterSpacing: '0.1em', textTransform: 'uppercase' }}>Direction 02</div>
        <div style={{ fontSize: 11, fontFamily: "'Fira Code'", color: c.text }}>Premium dark SaaS · Warm amber</div>
      </div>

      {/* Nav */}
      <div style={{ margin: '16px 36px 0', padding: '14px 0', borderBottom: `1px solid ${c.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: '-0.03em' }}>
          pluck<span style={{ color: c.accent }}>.</span>ai
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {['Extract', 'History', 'Settings'].map((t, i) => (
            <span key={i} style={{ padding: '6px 14px', fontSize: 13, color: i === 0 ? c.bright : c.text, background: i === 0 ? c.surface : 'transparent', borderRadius: 8, fontWeight: 500 }}>{t}</span>
          ))}
        </div>
      </div>

      {/* Main */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '0 60px', marginTop: -16 }}>
        <h1 style={{ fontSize: 32, fontWeight: 700, textAlign: 'center', marginBottom: 10, lineHeight: 1.3, letterSpacing: '-0.03em' }}>
          Extract structured data<br />from any URL
        </h1>
        <p style={{ fontSize: 15, color: c.text, marginBottom: 36, textAlign: 'center' }}>
          Paste a link, get clean data in seconds
        </p>

        {/* URL Input */}
        <div style={{ width: '100%', maxWidth: 620, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 14, display: 'flex', alignItems: 'center', padding: '5px 5px 5px 20px', boxShadow: '0 4px 24px rgba(0,0,0,0.3)' }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={c.text} strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
          <div style={{ flex: 1, fontSize: 14, color: c.bright, padding: '12px 14px', fontFamily: "'Fira Code'", fontSize: 13.5 }}>
            https://example.com/products
          </div>
          <button style={{ background: `linear-gradient(135deg, ${c.accent}, ${c.accentHover})`, color: '#fff', fontFamily: "'Outfit'", fontWeight: 600, fontSize: 14, padding: '12px 28px', border: 'none', borderRadius: 10, cursor: 'pointer', letterSpacing: '-0.01em' }}>
            Extract
          </button>
        </div>

        <div style={{ marginTop: 14, fontSize: 13, color: c.text }}>
          or <span style={{ color: c.accent, fontWeight: 500, cursor: 'pointer' }}>upload a schema</span> to define fields
        </div>

        {/* Classification */}
        <div style={{ marginTop: 32, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 10, padding: '14px 22px', fontSize: 13, color: c.text, display: 'flex', gap: 10, alignItems: 'center' }}>
          <div style={{ width: 8, height: 8, borderRadius: 4, background: c.accent }} />
          <span style={{ fontWeight: 600, color: c.bright }}>E-commerce</span>
          <span style={{ color: c.border }}>·</span>
          <span>Product Listing</span>
          <span style={{ color: c.border }}>·</span>
          <span>~24 fields detected</span>
        </div>

        {/* Mini table */}
        <div style={{ marginTop: 24, width: '100%', maxWidth: 620, borderRadius: 10, border: `1px solid ${c.border}`, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: c.surfaceAlt }}>
                <th style={{ ...cellStyle, color: c.text, fontWeight: 600, textAlign: 'left' }}>Product</th>
                <th style={{ ...cellStyle, color: c.text, fontWeight: 600, textAlign: 'right' }}>Price</th>
                <th style={{ ...cellStyle, color: c.text, fontWeight: 600, textAlign: 'center' }}>In Stock</th>
              </tr>
            </thead>
            <tbody>
              {SAMPLE_ROWS.map((r, i) => (
                <tr key={i} style={{ background: i % 2 === 0 ? c.surface : 'transparent' }}>
                  <td style={{ ...cellStyle, color: c.bright, textAlign: 'left' }}>{r.name}</td>
                  <td style={{ ...cellStyle, color: c.bright, textAlign: 'right', fontFamily: "'Fira Code'" }}>{r.price}</td>
                  <td style={{ ...cellStyle, textAlign: 'center' }}>
                    <span style={{ display: 'inline-block', padding: '2px 10px', borderRadius: 6, fontSize: 12, fontWeight: 500, background: r.stock ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)', color: r.stock ? '#4ade80' : '#f87171' }}>
                      {r.stock ? 'Yes' : 'No'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <PaletteStrip
        colors={[c.bg, c.surface, c.border, c.text, c.bright, c.accent]}
        fontLabel="Outfit · Fira Code"
        borderColor={c.border}
        textColor={c.text}
      />
    </div>
  );
}


/* ════════════════════════════════════════════
   DIRECTION 3 — NEWSPRINT
   Editorial light. Serif headlines. Ink blue.
   ════════════════════════════════════════════ */
function NewsprintDirection() {
  const c = { bg: '#f3f0e8', surface: '#faf8f4', border: '#d4d0c4', text: '#7a7668', bright: '#1c1b18', accent: '#2852cc', accentLight: '#e8edf8' };

  const cellStyle = { padding: '10px 14px', fontSize: 13, fontFamily: "'Source Sans 3', sans-serif", borderBottom: `1px solid ${c.border}` };

  return (
    <div style={{ background: c.bg, color: c.bright, fontFamily: "'Source Sans 3', sans-serif", width: 880, height: 880, display: 'flex', flexDirection: 'column' }}>
      {/* Label */}
      <div style={{ padding: '24px 36px 0', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ fontSize: 11, fontFamily: "'JetBrains Mono'", color: c.text, letterSpacing: '0.1em', textTransform: 'uppercase' }}>Direction 03</div>
        <div style={{ fontSize: 11, fontFamily: "'JetBrains Mono'", color: c.text }}>Editorial elegance · Ink blue accent</div>
      </div>

      {/* Nav */}
      <div style={{ margin: '16px 36px 0', padding: '14px 0', borderBottom: `2px solid ${c.bright}`, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: 22, fontStyle: 'italic', letterSpacing: '-0.01em' }}>
          pluck.ai
        </div>
        <div style={{ display: 'flex', gap: 28, fontSize: 14, color: c.text }}>
          <span style={{ color: c.bright, fontWeight: 600 }}>Extract</span>
          <span>History</span>
          <span>Settings</span>
        </div>
      </div>

      {/* Main */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '0 60px', marginTop: -16 }}>
        <h1 style={{ fontFamily: "'Instrument Serif', serif", fontSize: 38, fontWeight: 400, textAlign: 'center', marginBottom: 10, lineHeight: 1.25, letterSpacing: '-0.02em' }}>
          Extract structured data<br />from any URL
        </h1>
        <p style={{ fontSize: 16, color: c.text, marginBottom: 36, textAlign: 'center', maxWidth: 380 }}>
          Paste a link below to scrape, classify, and tabulate its contents.
        </p>

        {/* URL Input */}
        <div style={{ width: '100%', maxWidth: 620, background: c.surface, border: `2px solid ${c.bright}`, borderRadius: 4, display: 'flex', alignItems: 'center', padding: '4px 4px 4px 18px' }}>
          <div style={{ flex: 1, fontSize: 14, color: c.bright, padding: '11px 0', fontFamily: "'JetBrains Mono', monospace", fontSize: 13.5 }}>
            https://example.com/products
          </div>
          <button style={{ background: c.accent, color: '#fff', fontFamily: "'Source Sans 3'", fontWeight: 600, fontSize: 14, padding: '11px 28px', border: 'none', borderRadius: 2, cursor: 'pointer' }}>
            Extract
          </button>
        </div>

        <div style={{ marginTop: 14, fontSize: 13, color: c.text }}>
          Optional — <span style={{ color: c.accent, fontWeight: 500, textDecoration: 'underline', textUnderlineOffset: 3, cursor: 'pointer' }}>upload a schema</span>
        </div>

        {/* Classification */}
        <div style={{ marginTop: 32, background: c.accentLight, borderLeft: `3px solid ${c.accent}`, padding: '13px 20px', fontSize: 14, color: c.bright, display: 'flex', gap: 10, alignItems: 'center', borderRadius: '0 4px 4px 0' }}>
          <span style={{ fontWeight: 600 }}>E-commerce</span>
          <span style={{ color: c.text }}>—</span>
          <span style={{ color: c.text }}>Product Listing · ~24 fields detected</span>
        </div>

        {/* Mini table */}
        <div style={{ marginTop: 24, width: '100%', maxWidth: 620, border: `1px solid ${c.border}`, borderRadius: 4, overflow: 'hidden', background: c.surface }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={{ ...cellStyle, color: c.text, fontWeight: 600, textAlign: 'left', borderBottom: `2px solid ${c.bright}`, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Product</th>
                <th style={{ ...cellStyle, color: c.text, fontWeight: 600, textAlign: 'right', borderBottom: `2px solid ${c.bright}`, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Price</th>
                <th style={{ ...cellStyle, color: c.text, fontWeight: 600, textAlign: 'center', borderBottom: `2px solid ${c.bright}`, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.06em' }}>In Stock</th>
              </tr>
            </thead>
            <tbody>
              {SAMPLE_ROWS.map((r, i) => (
                <tr key={i}>
                  <td style={{ ...cellStyle, color: c.bright, textAlign: 'left' }}>{r.name}</td>
                  <td style={{ ...cellStyle, color: c.bright, textAlign: 'right', fontFamily: "'JetBrains Mono'", fontSize: 12 }}>{r.price}</td>
                  <td style={{ ...cellStyle, textAlign: 'center', color: r.stock ? '#1a7a3a' : '#b83030', fontWeight: 500 }}>
                    {r.stock ? 'Yes' : 'No'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <PaletteStrip
        colors={[c.bg, c.surface, c.border, c.text, c.bright, c.accent]}
        fontLabel="Instrument Serif · Source Sans 3 · JetBrains Mono"
        borderColor={c.border}
        textColor={c.text}
      />
    </div>
  );
}


/* ════════════════════════════════════════════
   DIRECTION 4 — VOID
   Maximum drama. Electric violet on black.
   ════════════════════════════════════════════ */
function VoidDirection() {
  const c = { bg: '#07070c', surface: '#0f0f18', border: '#1e1e34', text: '#7878a0', bright: '#e8e8f8', accent: '#8b5cf6', accentGlow: 'rgba(139,92,246,0.25)' };

  const cellStyle = { padding: '10px 14px', fontSize: 13, fontFamily: "'Sora', sans-serif", borderBottom: `1px solid ${c.border}` };

  return (
    <div style={{ background: c.bg, color: c.bright, fontFamily: "'Sora', sans-serif", width: 880, height: 880, display: 'flex', flexDirection: 'column', position: 'relative', overflow: 'hidden' }}>
      {/* Subtle radial glow */}
      <div style={{ position: 'absolute', top: '30%', left: '50%', transform: 'translate(-50%, -50%)', width: 700, height: 400, background: `radial-gradient(ellipse, ${c.accentGlow} 0%, transparent 70%)`, pointerEvents: 'none' }} />

      {/* Label */}
      <div style={{ padding: '24px 36px 0', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', position: 'relative', zIndex: 1 }}>
        <div style={{ fontSize: 11, fontFamily: "'IBM Plex Mono'", color: c.text, letterSpacing: '0.1em', textTransform: 'uppercase' }}>Direction 04</div>
        <div style={{ fontSize: 11, fontFamily: "'IBM Plex Mono'", color: c.text }}>Maximum drama · Electric violet</div>
      </div>

      {/* Nav */}
      <div style={{ margin: '16px 36px 0', padding: '14px 0', borderBottom: `1px solid ${c.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center', position: 'relative', zIndex: 1 }}>
        <div style={{ fontSize: 20, fontWeight: 800, letterSpacing: '-0.04em' }}>
          pluck<span style={{ color: c.accent }}>.</span>ai
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {['Extract', 'History', 'Settings'].map((t, i) => (
            <span key={i} style={{ padding: '6px 16px', fontSize: 13, fontWeight: 500, color: i === 0 ? c.bright : c.text, background: i === 0 ? c.surface : 'transparent', border: i === 0 ? `1px solid ${c.border}` : 'none', borderRadius: 8 }}>{t}</span>
          ))}
        </div>
      </div>

      {/* Main */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '0 60px', marginTop: -16, position: 'relative', zIndex: 1 }}>
        <h1 style={{ fontSize: 36, fontWeight: 800, textAlign: 'center', marginBottom: 10, lineHeight: 1.25, letterSpacing: '-0.04em' }}>
          Extract structured data<br />from any URL
        </h1>
        <p style={{ fontSize: 15, color: c.text, marginBottom: 40, textAlign: 'center', lineHeight: 1.5 }}>
          Paste a link, get clean data in seconds
        </p>

        {/* URL Input */}
        <div style={{ width: '100%', maxWidth: 640, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 16, display: 'flex', alignItems: 'center', padding: '5px 5px 5px 20px', boxShadow: `0 0 40px ${c.accentGlow}, 0 4px 20px rgba(0,0,0,0.4)` }}>
          <div style={{ flex: 1, fontSize: 13.5, color: c.bright, padding: '12px 10px', fontFamily: "'IBM Plex Mono', monospace" }}>
            https://example.com/products
          </div>
          <button style={{ background: c.accent, color: '#fff', fontFamily: "'Sora'", fontWeight: 700, fontSize: 14, padding: '12px 30px', border: 'none', borderRadius: 12, cursor: 'pointer', boxShadow: `0 4px 20px ${c.accentGlow}`, letterSpacing: '-0.01em' }}>
            Extract
          </button>
        </div>

        <div style={{ marginTop: 14, fontSize: 13, color: c.text }}>
          or <span style={{ color: c.accent, fontWeight: 600, cursor: 'pointer' }}>upload a schema</span>
        </div>

        {/* Classification */}
        <div style={{ marginTop: 32, background: c.surface, border: `1px solid ${c.border}`, borderRadius: 12, padding: '14px 22px', fontSize: 13, color: c.text, display: 'flex', gap: 10, alignItems: 'center' }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: c.accent, boxShadow: `0 0 8px ${c.accent}` }} />
          <span style={{ fontWeight: 700, color: c.bright }}>E-commerce</span>
          <span style={{ color: c.border }}>·</span>
          <span>Product Listing</span>
          <span style={{ color: c.border }}>·</span>
          <span>~24 fields detected</span>
        </div>

        {/* Mini table */}
        <div style={{ marginTop: 24, width: '100%', maxWidth: 640, border: `1px solid ${c.border}`, borderRadius: 12, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: c.surface }}>
                <th style={{ ...cellStyle, color: c.text, fontWeight: 600, textAlign: 'left' }}>Product</th>
                <th style={{ ...cellStyle, color: c.text, fontWeight: 600, textAlign: 'right' }}>Price</th>
                <th style={{ ...cellStyle, color: c.text, fontWeight: 600, textAlign: 'center' }}>In Stock</th>
              </tr>
            </thead>
            <tbody>
              {SAMPLE_ROWS.map((r, i) => (
                <tr key={i}>
                  <td style={{ ...cellStyle, color: c.bright, textAlign: 'left' }}>{r.name}</td>
                  <td style={{ ...cellStyle, color: c.bright, textAlign: 'right', fontFamily: "'IBM Plex Mono'" }}>{r.price}</td>
                  <td style={{ ...cellStyle, textAlign: 'center' }}>
                    <span style={{ display: 'inline-block', padding: '2px 10px', borderRadius: 6, fontSize: 12, fontWeight: 600, background: r.stock ? 'rgba(139,92,246,0.15)' : 'rgba(239,68,68,0.12)', color: r.stock ? c.accent : '#f87171' }}>
                      {r.stock ? 'Yes' : 'No'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <PaletteStrip
        colors={[c.bg, c.surface, c.border, c.text, c.bright, c.accent]}
        fontLabel="Sora · IBM Plex Mono"
        borderColor={c.border}
        textColor={c.text}
      />
    </div>
  );
}

// Export all
Object.assign(window, { TerminalDirection, ObsidianDirection, NewsprintDirection, VoidDirection });
