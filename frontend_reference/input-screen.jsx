// input-screen.jsx — URL input, classification, extract trigger

function InputScreen({ onExtract, theme: t }) {
  const [url, setUrl] = React.useState('');
  const [phase, setPhase] = React.useState('idle');
  // idle → classifying → classified → extracting
  const [classification, setClassification] = React.useState(null);
  const inputRef = React.useRef(null);

  React.useEffect(() => {
    const timer = setTimeout(() => inputRef.current?.focus(), 200);
    return () => clearTimeout(timer);
  }, []);

  // Auto-classify after URL input settles
  React.useEffect(() => {
    if (url.length > 12 && phase === 'idle') {
      const timer = setTimeout(() => {
        setPhase('classifying');
        setTimeout(() => {
          setClassification({
            type: 'E-commerce', subtype: 'Product Listing',
            fields: 24, confidence: 94,
          });
          setPhase('classified');
        }, 1400);
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [url, phase]);

  const handleExtract = () => {
    if (phase !== 'classified') return;
    setPhase('extracting');
    setTimeout(() => onExtract(), 2200);
  };

  const handleUrlChange = (e) => {
    setUrl(e.target.value);
    if (phase !== 'idle') { setPhase('idle'); setClassification(null); }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && phase === 'classified') handleExtract();
  };

  const extractReady = phase === 'classified';
  const extracting = phase === 'extracting';

  return (
    <FadeIn>
      <div style={{
        width: '100%', height: '100%', background: t.bg,
        display: 'flex', flexDirection: 'column', fontFamily: t.fontUI,
      }}>
        {/* Nav */}
        <nav style={{
          padding: '0 40px', height: 56, display: 'flex',
          alignItems: 'center', justifyContent: 'space-between',
          borderBottom: `1px solid ${t.border}`,
        }}>
          <div style={{
            fontFamily: t.fontMono, fontSize: 17, fontWeight: 500,
            color: t.textBright, letterSpacing: '-0.01em',
          }}>
            pluck<span style={{ color: t.accent }}>.</span>ai
          </div>
          <div style={{ display: 'flex', gap: 28, fontFamily: t.fontMono, fontSize: 12 }}>
            <span style={{ color: t.textBright }}>extract</span>
            <span style={{ color: t.textMuted, cursor: 'pointer' }}>history</span>
            <span style={{ color: t.textMuted, cursor: 'pointer' }}>settings</span>
          </div>
        </nav>

        {/* Center content */}
        <div style={{
          flex: 1, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', padding: '0 40px',
        }}>
          {/* Headline — Void-scale drama */}
          <h1 style={{
            fontSize: 40, fontWeight: 700, color: t.textBright,
            textAlign: 'center', marginBottom: 12,
            letterSpacing: '-0.035em', lineHeight: 1.15,
          }}>
            Extract structured data<br />from any URL
          </h1>
          <p style={{
            fontSize: 14, color: t.textMuted, fontFamily: t.fontMono,
            marginBottom: 44, letterSpacing: '0.01em',
          }}>
            paste a url → get a table
          </p>

          {/* URL input bar */}
          <div style={{
            width: '100%', maxWidth: 640, background: t.surface,
            border: `1px solid ${t.border}`, borderRadius: t.radius,
            display: 'flex', alignItems: 'center', padding: '4px 4px 4px 18px',
            boxShadow: `0 0 28px ${t.accentGlow}`,
            transition: 'box-shadow 0.4s, border-color 0.3s',
          }}>
            <span style={{
              fontFamily: t.fontMono, color: t.accent,
              fontSize: 16, marginRight: 10, flexShrink: 0,
            }}>›</span>
            <input
              ref={inputRef}
              value={url}
              onChange={handleUrlChange}
              onKeyDown={handleKeyDown}
              placeholder="https://example.com/products"
              style={{
                flex: 1, background: 'transparent', border: 'none', outline: 'none',
                fontFamily: t.fontMono, fontSize: 14, color: t.textBright,
                padding: '12px 0',
              }}
            />
            <button
              onClick={handleExtract}
              disabled={!extractReady}
              style={{
                background: extractReady ? t.accent : t.elevated,
                color: extractReady ? t.bg : t.textMuted,
                fontFamily: t.fontUI, fontWeight: 600, fontSize: 13,
                padding: '11px 26px', border: 'none',
                borderRadius: Math.max(t.radius - 1, 2),
                cursor: extractReady ? 'pointer' : 'default',
                transition: 'all 0.35s ease',
                boxShadow: extractReady ? `0 0 20px ${t.accentGlow}` : 'none',
                flexShrink: 0,
              }}
            >
              {extracting ? 'Extracting…' : 'Extract'}
            </button>
          </div>

          {/* Schema link */}
          <div style={{
            marginTop: 16, fontSize: 12, color: t.textMuted,
            fontFamily: t.fontMono,
          }}>
            optional:{' '}
            <span style={{
              color: t.accent, textDecoration: 'underline',
              textUnderlineOffset: 3, cursor: 'pointer',
            }}>upload schema</span>
          </div>

          {/* Classification card */}
          <div style={{
            marginTop: 40, minHeight: 46,
            display: 'flex', justifyContent: 'center',
          }}>
            {phase === 'classifying' && (
              <div style={{
                background: t.surface, border: `1px solid ${t.border}`,
                borderRadius: t.radius, padding: '13px 24px',
                fontFamily: t.fontMono, fontSize: 12, color: t.textMuted,
                display: 'flex', gap: 10, alignItems: 'center',
                animation: 'pluckFadeIn 0.3s ease',
              }}>
                <span style={{ color: t.accent, animation: 'pluckPulse 1s ease infinite' }}>●</span>
                <span>classifying site…</span>
              </div>
            )}
            {classification && phase !== 'classifying' && (
              <div style={{
                background: t.surface, border: `1px solid ${t.border}`,
                borderRadius: t.radius, padding: '13px 24px',
                fontFamily: t.fontMono, fontSize: 12, color: t.textMuted,
                display: 'flex', gap: 14, alignItems: 'center',
                animation: 'pluckFadeIn 0.35s ease',
              }}>
                <span style={{ color: t.accent }}>■</span>
                <span style={{ color: t.textBright, fontWeight: 500 }}>{classification.type}</span>
                <span style={{ color: t.border }}>│</span>
                <span>{classification.subtype}</span>
                <span style={{ color: t.border }}>│</span>
                <span>~{classification.fields} fields</span>
                <span style={{ color: t.border }}>│</span>
                <span>{classification.confidence}% conf</span>
              </div>
            )}
          </div>

          {/* Extraction progress bar */}
          {extracting && (
            <div style={{
              marginTop: 20, width: '100%', maxWidth: 640,
              animation: 'pluckFadeIn 0.2s ease',
            }}>
              <div style={{
                height: 2, background: t.border, borderRadius: 1,
                overflow: 'hidden',
              }}>
                <div style={{
                  height: '100%', background: t.accent, borderRadius: 1,
                  animation: 'pluckProgress 2s ease forwards',
                  boxShadow: `0 0 8px ${t.accentGlow}`,
                }} />
              </div>
              <div style={{
                marginTop: 10, textAlign: 'center', fontFamily: t.fontMono,
                fontSize: 11, color: t.textMuted,
              }}>
                extracting {classification?.fields || 24} fields…
              </div>
            </div>
          )}
        </div>
      </div>
    </FadeIn>
  );
}

Object.assign(window, { InputScreen });
