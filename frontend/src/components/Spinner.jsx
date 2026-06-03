import React, { useState, useEffect } from 'react';

const BRAILLE = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

function SpinnerChar({ color }) {
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setIdx(i => (i + 1) % BRAILLE.length), 80);
    return () => clearInterval(id);
  }, []);

  return <span style={{ color }}>{BRAILLE[idx]}</span>;
}

/**
 * Claude Code-style step list.
 * steps: Array<{ id, label, status: 'pending'|'active'|'done'|'error', error? }>
 */
export default function Spinner({ steps, theme: t }) {
  return (
    <div style={{ fontFamily: t.fontMono, fontSize: 13, lineHeight: '2' }}>
      {steps.map(step => {
        const isPending = step.status === 'pending';
        const isActive  = step.status === 'active';
        const isDone    = step.status === 'done';
        const isError   = step.status === 'error';

        return (
          <div
            key={step.id}
            style={{
              display: 'flex',
              alignItems: 'baseline',
              gap: 10,
              animation: isActive ? 'pluckFadeIn 0.2s ease both' : 'none',
            }}
          >
            {/* Icon column — fixed width so labels align */}
            <span style={{ width: 14, flexShrink: 0, display: 'inline-flex', alignItems: 'center' }}>
              {isActive  && <SpinnerChar color={t.accent} />}
              {isDone    && <span style={{ color: t.accent }}>✓</span>}
              {isPending && <span style={{ color: t.textMuted }}>·</span>}
              {isError   && <span style={{ color: t.error }}>✗</span>}
            </span>

            {/* Label */}
            <span style={{
              color: isActive ? t.textBright : isDone ? t.textMuted : isError ? t.error : t.textMuted,
              opacity: isPending ? 0.5 : 1,
            }}>
              {step.label}
              {isError && step.error && (
                <span style={{ color: t.error, marginLeft: 8, opacity: 0.85 }}>
                  — {step.error}
                </span>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}
