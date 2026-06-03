import React, { useState, useEffect, useRef } from 'react';
import { login, getStoredToken } from '../api.js';

function FadeIn({ children }) {
  return (
    <div style={{ animation: 'pluckFadeIn 0.45s ease both', width: '100%', height: '100%' }}>
      {children}
    </div>
  );
}

export default function Login({ onLogin, theme: t }) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState(false);
  const [shake, setShake] = useState(false);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef(null);

  // Skip login if a token is already stored
  useEffect(() => {
    if (getStoredToken()) onLogin();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const t = setTimeout(() => inputRef.current?.focus(), 100);
    return () => clearTimeout(t);
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!password || loading) return;
    setLoading(true);
    try {
      await login(password);
      onLogin();
    } catch {
      setError(true);
      setShake(true);
      setTimeout(() => setShake(false), 500);
    } finally {
      setLoading(false);
    }
  };

  return (
    <FadeIn>
      <div style={{
        width: '100%', height: '100%', background: t.bg,
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', fontFamily: t.fontUI, position: 'relative',
      }}>
        {/* Wordmark */}
        <div style={{
          fontFamily: t.fontMono, fontSize: 22, fontWeight: 500,
          color: t.textBright, marginBottom: 52, letterSpacing: '-0.02em',
        }}>
          pluck<span style={{ color: t.accent }}>.</span>ai
        </div>

        {/* Password form */}
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
            onChange={e => { setPassword(e.target.value); setError(false); }}
            placeholder="password"
            autoComplete="off"
            disabled={loading}
            style={{
              flex: 1, background: 'transparent', border: 'none', outline: 'none',
              fontFamily: t.fontMono, fontSize: 14, color: t.textBright,
              padding: '12px 0',
            }}
          />
          <button type="submit" disabled={loading} style={{
            background: t.accent, color: t.bg,
            fontFamily: t.fontUI, fontWeight: 600, fontSize: 13,
            padding: '11px 22px', border: 'none',
            borderRadius: Math.max(t.radius - 1, 2),
            cursor: loading ? 'default' : 'pointer',
            flexShrink: 0, opacity: loading ? 0.7 : 1,
            transition: 'opacity 0.15s',
          }}>
            {loading ? '…' : 'Enter'}
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
