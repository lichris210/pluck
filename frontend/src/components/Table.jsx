import React, { useState, useRef, useMemo } from 'react';
import { createPortal } from 'react-dom';

const TRUNCATE = 60;

function CellTooltip({ full, display, theme: t }) {
  const [tip, setTip] = useState(null);
  const ref = useRef(null);

  const handleEnter = () => {
    const rect = ref.current.getBoundingClientRect();
    // Show above unless cell is too close to the top of the viewport
    const above = rect.top > 120;
    // Center horizontally on the cell, clamped to viewport edges
    const x = Math.min(
      Math.max(rect.left + rect.width / 2, 210),
      window.innerWidth - 210
    );
    setTip({ x, y: above ? rect.top : rect.bottom, above });
  };

  return (
    <span ref={ref} onMouseEnter={handleEnter} onMouseLeave={() => setTip(null)}
      style={{ cursor: 'default' }}>
      {display}
      {tip && createPortal(
        <div style={{
          position: 'fixed',
          left: tip.x,
          ...(tip.above
            ? { bottom: window.innerHeight - tip.y + 8 }
            : { top: tip.y + 8 }),
          transform: 'translateX(-50%)',
          maxWidth: 420,
          background: t.surface,
          border: `1px solid ${t.accent}`,
          borderRadius: t.radius,
          padding: '8px 12px',
          fontFamily: t.fontMono,
          fontSize: 12,
          color: t.textBright,
          lineHeight: 1.6,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          boxShadow: `0 0 20px ${t.accentGlow}, 0 4px 12px rgba(0,0,0,0.5)`,
          zIndex: 9999,
          pointerEvents: 'none',
        }}>
          {full}
        </div>,
        document.body
      )}
    </span>
  );
}

function renderCell(val, t) {
  if (val === null || val === undefined) {
    return <span style={{ color: t.textMuted, fontFamily: t.fontMono }}>—</span>;
  }
  if (typeof val === 'boolean') {
    return (
      <span style={{ fontFamily: t.fontMono, color: val ? t.success : t.textMuted }}>
        {val ? 'true' : 'false'}
      </span>
    );
  }

  // Stringify objects; leave numbers to be rendered by the td directly
  if (typeof val === 'number') return val;

  const str = typeof val === 'object' ? JSON.stringify(val) : String(val);
  const spanStyle = typeof val === 'object'
    ? { color: t.textMuted, fontFamily: t.fontMono, fontSize: 11 }
    : {};

  if (str.length > TRUNCATE) {
    return (
      <span style={spanStyle}>
        <CellTooltip full={str} display={str.slice(0, TRUNCATE) + '…'} theme={t} />
      </span>
    );
  }
  return str.length ? <span style={spanStyle}>{str}</span> : str;
}

export default function Table({ items, theme: t }) {
  const [sortCol, setSortCol] = useState(null);
  const [sortDir, setSortDir] = useState('asc');

  const columns = useMemo(() => {
    const seen = new Set();
    for (const row of items) {
      if (row && typeof row === 'object') {
        for (const k of Object.keys(row)) seen.add(k);
      }
    }
    return [...seen];
  }, [items]);

  const sorted = useMemo(() => {
    if (!sortCol) return items;
    return [...items].sort((a, b) => {
      const av = a?.[sortCol];
      const bv = b?.[sortCol];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [items, sortCol, sortDir]);

  const handleSort = (col) => {
    if (sortCol === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortCol(col);
      setSortDir('asc');
    }
  };

  if (!items.length) {
    return (
      <div style={{ color: t.textMuted, fontFamily: t.fontMono, fontSize: 13, padding: '20px 0' }}>
        No data returned.
      </div>
    );
  }

  return (
    <div style={{ overflow: 'auto', flex: 1 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 'max-content' }}>
        <thead>
          <tr>
            {columns.map(col => (
              <th
                key={col}
                onClick={() => handleSort(col)}
                style={{
                  padding: '13px 18px',
                  textAlign: 'left',
                  fontSize: 11,
                  fontFamily: t.fontMono,
                  fontWeight: 500,
                  color: sortCol === col ? t.accent : t.textMuted,
                  borderBottom: `1px solid ${t.border}`,
                  cursor: 'pointer',
                  userSelect: 'none',
                  textTransform: 'uppercase',
                  letterSpacing: '0.07em',
                  position: 'sticky',
                  top: 0,
                  background: t.bg,
                  zIndex: 2,
                  whiteSpace: 'nowrap',
                }}
              >
                {col}
                <span style={{ marginLeft: 4, opacity: sortCol === col ? 1 : 0.3, color: t.accent }}>
                  {sortCol === col ? (sortDir === 'asc' ? '↑' : '↓') : '↕'}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr
              key={i}
              style={{ transition: 'background 0.1s' }}
              onMouseEnter={e => { e.currentTarget.style.background = t.surface; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
            >
              {columns.map(col => {
                const val = row?.[col];
                const isNum = typeof val === 'number';
                return (
                  <td
                    key={col}
                    style={{
                      padding: '14px 18px',
                      fontSize: 13,
                      color: t.textBright,
                      borderBottom: `1px solid ${t.border}`,
                      textAlign: isNum ? 'right' : 'left',
                      fontFamily: isNum ? t.fontMono : t.fontUI,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {renderCell(val, t)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
