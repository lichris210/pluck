import React, { useState, useRef, useEffect } from 'react';
import { classify, extractSSE } from '../api.js';
import Spinner from '../components/Spinner.jsx';

function FadeIn({ children }) {
  return (
    <div style={{ animation: 'pluckFadeIn 0.45s ease both', width: '100%', height: '100%' }}>
      {children}
    </div>
  );
}

const BASE_STEPS = [
  { id: 'classifying', label: 'classifying site',  status: 'pending' },
  { id: 'fetching',    label: 'fetching page',      status: 'pending' },
  { id: 'extracting', label: 'extracting data',     status: 'pending' },
];

export default function Input({ onResults, theme: t }) {
  const [url, setUrl]           = useState('');
  // idle | classifying | classified | running | error
  const [phase, setPhase]       = useState('idle');
  const [steps, setSteps]       = useState(BASE_STEPS);
  const [schema, setSchema]     = useState(null);
  const [schemaName, setSchemaName] = useState('');
  const [classification, setClassification] = useState(null);
  const [prompt, setPrompt]     = useState('');
  const [classifyError, setClassifyError]   = useState(null);

  // URL parameters popover
  const [paramsOpen, setParamsOpen]   = useState(false);
  const [maxResults, setMaxResults]   = useState(100);
  const [forceApify, setForceApify]   = useState(false);

  const inputRef    = useRef(null);
  const fileRef     = useRef(null);
  const sseRef      = useRef(null);
  const promptRef   = useRef(null);
  const paramsRef   = useRef(null);

  useEffect(() => {
    const timer = setTimeout(() => inputRef.current?.focus(), 150);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!paramsOpen) return;
    const onDocClick = e => {
      if (paramsRef.current && !paramsRef.current.contains(e.target)) setParamsOpen(false);
    };
    const onEsc = e => { if (e.key === 'Escape') setParamsOpen(false); };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onEsc);
    };
  }, [paramsOpen]);

  const patch = (id, updates) =>
    setSteps(prev => prev.map(s => s.id === id ? { ...s, ...updates } : s));

  const resetClassification = () => {
    setClassification(null);
    setClassifyError(null);
    if (phase !== 'idle' && phase !== 'running') setPhase('idle');
  };

  const handleUrlChange = (e) => {
    setUrl(e.target.value);
    // Any edit to the URL invalidates a prior classification.
    if (classification || classifyError) resetClassification();
  };

  const handleClassify = async () => {
    if (!url.trim() || phase === 'classifying' || phase === 'running') return;

    setParamsOpen(false);
    setClassifyError(null);
    setClassification(null);
    setPhase('classifying');

    try {
      const result = await classify(url.trim());
      if (result.error) {
        setClassifyError(result.error);
        setPhase('idle');
        return;
      }
      setClassification(result);
      setPhase('classified');
      setTimeout(() => promptRef.current?.focus(), 100);
    } catch (err) {
      setClassifyError(err.message || 'Classification failed');
      setPhase('idle');
    }
  };

  const handleExtract = () => {
    if (!url.trim() || phase === 'running' || !classification) return;

    setParamsOpen(false);
    setPhase('running');
    setSteps(BASE_STEPS.map(s => ({ ...s, status: 'pending' })));

    const sse = extractSSE(url.trim(), schema, {
      onStep(ev) {
        const { step, status } = ev;

        if (status === 'active') {
          const extra = {};
          if (step === 'fetching'    && ev.fetcher)  extra.label = `fetching — ${ev.fetcher}`;
          if (step === 'extracting'  && ev.fields)   extra.label = `extracting — ${ev.fields} fields`;
          patch(step, { status: 'active', ...extra });
        }

        if (status === 'done') {
          const extra = {};
          if (step === 'classifying' && ev.site_group)
            extra.label = `classified — ${ev.site_group.toLowerCase().replace(/_/g, ' ')}`;
          if (step === 'fetching'    && ev.html_length)
            extra.label = `fetched — ${Math.round(ev.html_length / 1024)} kb`;
          patch(step, { status: 'done', ...extra });
        }
      },

      onDone(result) {
        // Finalize any steps still in flight (e.g. extracting skipped on Apify path)
        setSteps(prev =>
          prev.map(s =>
            s.status === 'active' || s.status === 'pending'
              ? { ...s, status: 'done' }
              : s
          )
        );
        setTimeout(() => {
          onResults(result.items, url.trim(), {
            cost_usd:           result.cost_usd,
            model_used:         result.model_used,
            extraction_time_ms: result.extraction_time_ms,
            total_time_ms:      result.total_time_ms,
            total_rows:         result.total_rows,
            total_columns:      result.total_columns,
            rows_before_curation: result.rows_before_curation,
          });
        }, 350);
      },

      onError(err) {
        setSteps(prev =>
          prev.map(s =>
            s.status === 'active'
              ? { ...s, status: 'error', error: err }
              : s
          )
        );
        setPhase('error');
      },
    }, maxResults, prompt, forceApify);

    sseRef.current = sse;
  };

  const handleRetry = () => {
    sseRef.current?.close();
    // Keep the classification so the user can re-run extract directly.
    setPhase(classification ? 'classified' : 'idle');
    setSteps(BASE_STEPS);
  };

  const handleSchemaFile = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = ev => {
      try {
        setSchema(JSON.parse(ev.target.result));
        setSchemaName(file.name);
      } catch { /* ignore malformed JSON */ }
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  const handleKeyDown = e => {
    if (e.key === 'Enter' && url.trim() && phase === 'idle') handleClassify();
  };

  const handlePromptKeyDown = e => {
    // ⌘/Ctrl+Enter submits the extraction from the prompt box.
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleExtract();
    }
  };

  const running      = phase === 'running';
  const classifying  = phase === 'classifying';
  const hasError     = phase === 'error';
  const canClassify  = url.trim().length > 0 && !classifying && !running;
  const canExtract   = !!classification && !running;

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
          borderBottom: `1px solid ${t.border}`, flexShrink: 0,
        }}>
          <div style={{
            fontFamily: t.fontMono, fontSize: 17, fontWeight: 500,
            color: t.textBright, letterSpacing: '-0.01em',
          }}>
            pluck<span style={{ color: t.accent }}>.</span>ai
          </div>
          <div style={{ display: 'flex', gap: 28, fontFamily: t.fontMono, fontSize: 12 }}>
            <span style={{ color: t.textBright }}>extract</span>
            <span style={{ color: t.textMuted }}>settings</span>
          </div>
        </nav>

        {/* Center */}
        <div style={{
          flex: 1, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', padding: '0 40px',
        }}>
          {/* Headline */}
          <h1 style={{
            fontSize: 40, fontWeight: 700, color: t.textBright,
            textAlign: 'center', marginBottom: 12, marginTop: 0,
            letterSpacing: '-0.035em', lineHeight: 1.15,
          }}>
            Extract structured data<br />from any URL
          </h1>
          <p style={{
            fontSize: 14, color: t.textMuted, fontFamily: t.fontMono,
            marginBottom: 44, marginTop: 0, letterSpacing: '0.01em',
          }}>
            paste a url → get a table
          </p>

          {/* URL bar */}
          <div ref={paramsRef} style={{ position: 'relative', width: '100%', maxWidth: 640 }}>
            <div style={{
              width: '100%', background: t.surface,
              border: `1px solid ${t.border}`, borderRadius: t.radius,
              display: 'flex', alignItems: 'center', padding: '4px 4px 4px 18px',
              boxShadow: `0 0 28px ${t.accentGlow}`,
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
                disabled={running}
                style={{
                  flex: 1, background: 'transparent', border: 'none', outline: 'none',
                  fontFamily: t.fontMono, fontSize: 14, color: t.textBright,
                  padding: '12px 0',
                }}
              />
              <button
                onClick={() => setParamsOpen(o => !o)}
                disabled={running}
                title="Parameters"
                aria-label="Parameters"
                aria-expanded={paramsOpen}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  background: 'transparent', border: 'none',
                  color: paramsOpen ? t.accent : t.textMuted,
                  cursor: running ? 'default' : 'pointer',
                  padding: '8px 10px', marginRight: 2, flexShrink: 0,
                  transition: 'color 0.2s',
                }}
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="4" y1="8" x2="20" y2="8" />
                  <line x1="4" y1="16" x2="20" y2="16" />
                  <circle cx="9" cy="8" r="2.6" fill={t.surface} />
                  <circle cx="15" cy="16" r="2.6" fill={t.surface} />
                </svg>
              </button>
              <button
                onClick={handleClassify}
                disabled={!canClassify}
                style={{
                  background: canClassify ? t.accent : t.elevated,
                  color: canClassify ? t.bg : t.textMuted,
                  fontFamily: t.fontUI, fontWeight: 600, fontSize: 13,
                  padding: '11px 26px', border: 'none',
                  borderRadius: Math.max(t.radius - 1, 2),
                  cursor: canClassify ? 'pointer' : 'default',
                  transition: 'background 0.25s, color 0.25s, box-shadow 0.25s',
                  boxShadow: canClassify ? `0 0 20px ${t.accentGlow}` : 'none',
                  flexShrink: 0,
                }}
              >
                {classifying ? 'Classifying…' : 'Classify'}
              </button>
            </div>

            {/* Parameters popover */}
            {paramsOpen && (
              <div style={{
                position: 'absolute', top: 'calc(100% + 10px)', right: 0, zIndex: 30,
                width: 248, background: t.elevated,
                border: `1px solid ${t.border}`, borderRadius: t.radius,
                padding: 16, boxShadow: '0 10px 30px rgba(0,0,0,0.5)',
                animation: 'pluckFadeIn 0.16s ease both',
              }}>
                <div style={{
                  fontFamily: t.fontMono, fontSize: 10, color: t.textMuted,
                  letterSpacing: '0.08em', textTransform: 'uppercase',
                  marginBottom: 14, opacity: 0.7,
                }}>
                  parameters
                </div>

                {/* max results */}
                <div style={{
                  display: 'flex', alignItems: 'center',
                  justifyContent: 'space-between', marginBottom: 14,
                }}>
                  <label style={{ fontFamily: t.fontMono, fontSize: 12, color: t.text }}>
                    max results
                  </label>
                  <input
                    type="number" min={1} max={1000}
                    value={maxResults}
                    onChange={e => setMaxResults(
                      Math.max(1, Math.min(1000, Number(e.target.value) || 1))
                    )}
                    style={{
                      width: 72, background: t.surface, border: `1px solid ${t.border}`,
                      borderRadius: Math.max(t.radius - 1, 2), color: t.textBright,
                      fontFamily: t.fontMono, fontSize: 13, padding: '6px 8px',
                      outline: 'none', textAlign: 'right',
                    }}
                  />
                </div>

                {/* force apify */}
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                }}>
                  <label style={{ fontFamily: t.fontMono, fontSize: 12, color: t.text }}>
                    force apify
                  </label>
                  <button
                    role="switch"
                    aria-checked={forceApify}
                    onClick={() => setForceApify(v => !v)}
                    style={{
                      width: 38, height: 22, padding: 0, flexShrink: 0,
                      borderRadius: 11, border: `1px solid ${t.border}`,
                      background: forceApify ? t.accent : t.surface,
                      position: 'relative', cursor: 'pointer',
                      transition: 'background 0.2s',
                    }}
                  >
                    <span style={{
                      position: 'absolute', top: 2, left: forceApify ? 18 : 2,
                      width: 16, height: 16, borderRadius: '50%',
                      background: forceApify ? t.bg : t.textMuted,
                      transition: 'left 0.2s, background 0.2s',
                    }} />
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Classify error */}
          {classifyError && (
            <div style={{
              marginTop: 14, fontFamily: t.fontMono, fontSize: 12, color: t.danger || '#e5484d',
              animation: 'pluckFadeIn 0.25s ease both',
            }}>
              {classifyError}
            </div>
          )}

          {/* Classification result → prompt + Extract */}
          {classification && (
            <div style={{
              width: '100%', maxWidth: 640, marginTop: 18,
              animation: 'pluckFadeIn 0.3s ease both',
            }}>
              <div style={{
                fontFamily: t.fontMono, fontSize: 12, color: t.textMuted, marginBottom: 12,
              }}>
                site group:{' '}
                <span style={{ color: t.accent }}>
                  {classification.site_group.toLowerCase().replace(/_/g, ' ')}
                </span>
                <span style={{ opacity: 0.55 }}> · #{classification.site_group_number}</span>
              </div>

              <textarea
                ref={promptRef}
                value={prompt}
                onChange={e => setPrompt(e.target.value)}
                onKeyDown={handlePromptKeyDown}
                placeholder="optional: describe what to extract (e.g. just job titles and companies)"
                disabled={running}
                rows={3}
                style={{
                  width: '100%', boxSizing: 'border-box', resize: 'vertical',
                  background: t.surface, border: `1px solid ${t.border}`,
                  borderRadius: t.radius, color: t.textBright,
                  fontFamily: t.fontMono, fontSize: 14, padding: '12px 14px',
                  outline: 'none',
                }}
              />

              <button
                onClick={handleExtract}
                disabled={!canExtract}
                style={{
                  marginTop: 12, width: '100%',
                  background: canExtract ? t.accent : t.elevated,
                  color: canExtract ? t.bg : t.textMuted,
                  fontFamily: t.fontUI, fontWeight: 600, fontSize: 13,
                  padding: '12px 26px', border: 'none',
                  borderRadius: Math.max(t.radius - 1, 2),
                  cursor: canExtract ? 'pointer' : 'default',
                  transition: 'background 0.25s, color 0.25s, box-shadow 0.25s',
                  boxShadow: canExtract ? `0 0 20px ${t.accentGlow}` : 'none',
                }}
              >
                {running ? 'Extracting…' : 'Extract'}
              </button>
            </div>
          )}

          {/* Schema link */}
          <div style={{
            marginTop: 16, fontSize: 12, color: t.textMuted, fontFamily: t.fontMono,
          }}>
            optional:{' '}
            <span
              onClick={() => fileRef.current?.click()}
              style={{
                color: t.accent, textDecoration: 'underline',
                textUnderlineOffset: 3, cursor: 'pointer',
              }}
            >
              {schemaName || 'upload schema'}
            </span>
            {schemaName && (
              <span
                onClick={() => { setSchema(null); setSchemaName(''); }}
                style={{ color: t.textMuted, marginLeft: 8, cursor: 'pointer', opacity: 0.7 }}
                title="Remove schema"
              >
                ×
              </span>
            )}
          </div>
          <input
            ref={fileRef}
            type="file"
            accept=".json,application/json"
            onChange={handleSchemaFile}
            style={{ display: 'none' }}
          />

          {/* Spinner / error area */}
          <div style={{
            marginTop: 40, minHeight: 80,
            display: 'flex', flexDirection: 'column',
            alignItems: 'center',
          }}>
            {(running || hasError) && (
              <div style={{ animation: 'pluckFadeIn 0.25s ease both' }}>
                <Spinner steps={steps} theme={t} />
                {hasError && (
                  <div style={{ marginTop: 14, fontFamily: t.fontMono, fontSize: 12 }}>
                    <span
                      onClick={handleRetry}
                      style={{
                        color: t.accent, cursor: 'pointer',
                        textDecoration: 'underline', textUnderlineOffset: 3,
                      }}
                    >
                      ↩ retry
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </FadeIn>
  );
}
