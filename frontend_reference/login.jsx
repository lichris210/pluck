// login.jsx — Ultra-minimal login screen for Pluck.ai

function LoginScreen({ onLogin, theme: t }) {
  const [password, setPassword] = React.useState('');
  const [error, setError] = React.useState(false);
  const [shake, setShake] = React.useState(false);
  const inputRef = React.useRef(null);

  React.useEffect(() => {
    const timer = setTimeout(() => inputRef.current?.focus(), 100);
    return () => clearTimeout(timer);
  }, []);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (password.toLowerCase().trim() === 'pluck') {
      onLogin();
    } else {
      setError(true);
      setShake(true);
      setTimeout(() => setShake(false), 500);
    }
  };

  return (
    <FadeIn>
      <div style={{
        width: '100%', height: '100%', background: t.bg,
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', fontFamily: t.fontUI,
      }}>
        {/* Wordmark */}
        <div style={{
          fontFamily: t.fontMono, fontSize: 22, fontWeight: 500,
          color: t.textBright, marginBottom: 52, letterSpacing: '-0.02em',
        }}>
          pluck<span style={{ color: t.accent }}>.</span>ai
        </div>

        {/* Password input */}
        <form onSubmit={handleSubmit} style={{
          display: 'flex', alignItems: 'center',
          background: t.surface,
          border: `1px solid ${error ? t.error : t.border}`,
          borderRadius: t.radius, padding: '4px 4px 4px 18px',
          width: 380, transition: 'border-color 0.2s, box-shadow 0.3s',
          animation: shake ? 'pluckShake 0.4s ease' : 'none',
          boxShadow: error
            ? `0 0 20px ${t.errorBg}`
            : `0 0 20px ${t.accentGlow}`,
        }}>
          <span style={{
            fontFamily: t.fontMono, color: t.accent,
            fontSize: 15, marginRight: 10, flexShrink: 0,
          }}>›</span>
          <input
            ref={inputRef}
            type="password"
            value={password}
            onChange={(e) => { setPassword(e.target.value); setError(false); }}
            placeholder="password"
            autoComplete="off"
            style={{
              flex: 1, background: 'transparent', border: 'none', outline: 'none',
              fontFamily: t.fontMono, fontSize: 14, color: t.textBright,
              padding: '12px 0',
            }}
          />
          <button type="submit" style={{
            background: t.accent, color: t.bg,
            fontFamily: t.fontUI, fontWeight: 600, fontSize: 13,
            padding: '11px 22px', border: 'none',
            borderRadius: Math.max(t.radius - 1, 2),
            cursor: 'pointer', flexShrink: 0,
          }}>
            Enter
          </button>
        </form>

        {/* Error message */}
        <div style={{
          marginTop: 18, fontSize: 12, fontFamily: t.fontMono,
          color: t.error, height: 16,
          opacity: error ? 1 : 0, transition: 'opacity 0.2s',
        }}>
          incorrect password
        </div>

        {/* Hint */}
        <div style={{
          position: 'absolute', bottom: 32, fontSize: 11,
          fontFamily: t.fontMono, color: t.textMuted, opacity: 0.5,
        }}>
          hint: try "pluck"
        </div>
      </div>
    </FadeIn>
  );
}

Object.assign(window, { LoginScreen });
