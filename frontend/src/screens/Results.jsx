import React, { useState } from 'react';
import Table from '../components/Table.jsx';

function FadeIn({ children }) {
  return (
    <div style={{ animation: 'pluckFadeIn 0.45s ease both', width: '100%', height: '100%' }}>
      {children}
    </div>
  );
}

function GhostBtn({ children, onClick, theme: t }) {
  const [hovered, setHovered] = useState(false);
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: t.surface,
        border: `1px solid ${hovered ? t.accent : t.border}`,
        borderRadius: t.radius, padding: '7px 16px', fontSize: 12,
        fontFamily: t.fontMono, color: hovered ? t.textBright : t.text,
        cursor: 'pointer', transition: 'border-color 0.15s, color 0.15s',
      }}
    >
      {children}
    </button>
  );
}

function toCSV(items) {
  if (!items.length) return '';
  const keys = [...new Set(items.flatMap(r => Object.keys(r || {})))];

  const esc = v => {
    if (v === null || v === undefined) return '';
    const s = typeof v === 'object' ? JSON.stringify(v) : String(v);
    return (s.includes(',') || s.includes('"') || s.includes('\n'))
      ? '"' + s.replace(/"/g, '""') + '"'
      : s;
  };

  const header = keys.map(esc).join(',');
  const rows   = items.map(row => keys.map(k => esc(row?.[k])).join(','));
  return [header, ...rows].join('\n');
}

function triggerDownload(content, filename, mime) {
  const blob = new Blob([content], { type: mime });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function Results({ items, sourceUrl, extractionMeta, onBack, theme: t }) {
  const meta = extractionMeta || {};

  let domain = sourceUrl;
  try { domain = new URL(sourceUrl).hostname; } catch { /* keep as-is */ }

  const timeMs = meta.total_time_ms != null ? meta.total_time_ms : meta.extraction_time_ms;
  const timeStr = timeMs != null
    ? `${(timeMs / 1000).toFixed(1)}s`
    : '—';
  const costStr = meta.cost_usd != null
    ? `$${meta.cost_usd.toFixed(4)}`
    : '—';

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
          <GhostBtn onClick={onBack} theme={t}>← new extraction</GhostBtn>
        </nav>

        {/* Header row */}
        <div style={{
          padding: '24px 40px 18px', display: 'flex',
          justifyContent: 'space-between', alignItems: 'flex-end', flexShrink: 0,
        }}>
          <div>
            <h2 style={{
              fontSize: 22, fontWeight: 700, color: t.textBright,
              letterSpacing: '-0.025em', margin: 0,
            }}>
              Extraction Results
            </h2>
            <p style={{
              fontSize: 12, color: t.textMuted, fontFamily: t.fontMono,
              marginTop: 6, marginBottom: 0,
            }}>
              {domain} · {items.length} rows · {meta.total_columns ?? 0} columns
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <GhostBtn theme={t} onClick={() => triggerDownload(JSON.stringify(items, null, 2), 'pluck_export.json', 'application/json')}>
              ↓ JSON
            </GhostBtn>
            <GhostBtn theme={t} onClick={() => triggerDownload(toCSV(items), 'pluck_export.csv', 'text/csv')}>
              ↓ CSV
            </GhostBtn>
          </div>
        </div>

        {/* Table — fills remaining height */}
        <div style={{ flex: 1, overflow: 'hidden', padding: '0 40px', display: 'flex', flexDirection: 'column' }}>
          <Table items={items} theme={t} />
        </div>

        {/* Metadata footer */}
        <div style={{
          padding: '14px 40px', borderTop: `1px solid ${t.border}`,
          display: 'flex', gap: 36, fontFamily: t.fontMono, fontSize: 11,
          color: t.textMuted, flexShrink: 0, flexWrap: 'wrap',
        }}>
          {meta.model_used && meta.model_used !== 'none' && (
            <span>model: <span style={{ color: t.text }}>{meta.model_used}</span></span>
          )}
          <span>cost: <span style={{ color: t.text }}>{costStr}</span></span>
          <span>time: <span style={{ color: t.text }}>{timeStr}</span></span>
          <span>rows: <span style={{ color: t.text }}>{items.length}</span></span>
          {meta.rows_before_curation != null && (
            <span>
              raw: <span style={{ color: t.text }}>{meta.rows_before_curation}</span>
              {' → '}kept: <span style={{ color: t.text }}>{items.length}</span>
            </span>
          )}
        </div>
      </div>
    </FadeIn>
  );
}
