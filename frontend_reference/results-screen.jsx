// results-screen.jsx — Sortable data table, downloads, metadata

const MOCK_RESULTS = [
  { id: 1, name: 'Wireless Headphones Pro', price: 79.99, rating: 4.5, stock: true, category: 'Audio' },
  { id: 2, name: 'USB-C Hub 7-in-1', price: 34.99, rating: 4.2, stock: true, category: 'Accessories' },
  { id: 3, name: 'Mechanical Keyboard RGB', price: 149.99, rating: 4.8, stock: false, category: 'Peripherals' },
  { id: 4, name: 'Webcam HD 1080p', price: 59.99, rating: 3.9, stock: true, category: 'Video' },
  { id: 5, name: '27" 4K Monitor', price: 399.99, rating: 4.6, stock: true, category: 'Displays' },
  { id: 6, name: 'Wireless Mouse Ergonomic', price: 44.99, rating: 4.1, stock: true, category: 'Peripherals' },
  { id: 7, name: 'Portable SSD 1TB', price: 89.99, rating: 4.7, stock: false, category: 'Storage' },
  { id: 8, name: 'Noise Cancelling Earbuds', price: 129.99, rating: 4.4, stock: true, category: 'Audio' },
];

const COLUMNS = [
  { key: 'name', label: 'Product', align: 'left', flex: 2.2 },
  { key: 'price', label: 'Price', align: 'right', flex: 0.8, mono: true },
  { key: 'rating', label: 'Rating', align: 'center', flex: 0.7, mono: true },
  { key: 'stock', label: 'In Stock', align: 'center', flex: 0.8 },
  { key: 'category', label: 'Category', align: 'left', flex: 1 },
];

function ResultsScreen({ onBack, theme: t }) {
  const [sortCol, setSortCol] = React.useState(null);
  const [sortDir, setSortDir] = React.useState('asc');
  const [appeared, setAppeared] = React.useState(false);

  React.useEffect(() => {
    const timer = setTimeout(() => setAppeared(true), 100);
    return () => clearTimeout(timer);
  }, []);

  const data = React.useMemo(() => {
    if (!sortCol) return MOCK_RESULTS;
    return [...MOCK_RESULTS].sort((a, b) => {
      const av = a[sortCol], bv = b[sortCol];
      if (av < bv) return sortDir === 'asc' ? -1 : 1;
      if (av > bv) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
  }, [sortCol, sortDir]);

  const handleSort = (col) => {
    if (sortCol === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortCol(col);
      setSortDir('asc');
    }
  };

  const SortArrow = ({ col }) => {
    if (sortCol !== col) return <span style={{ opacity: 0.3, marginLeft: 4 }}>↕</span>;
    return <span style={{ color: t.accent, marginLeft: 4 }}>{sortDir === 'asc' ? '↑' : '↓'}</span>;
  };

  const GhostBtn = ({ children, onClick }) => (
    <button onClick={onClick} style={{
      background: t.surface, border: `1px solid ${t.border}`,
      borderRadius: t.radius, padding: '7px 16px', fontSize: 12,
      fontFamily: t.fontMono, color: t.text, cursor: 'pointer',
      transition: 'border-color 0.15s, color 0.15s',
    }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = t.accent; e.currentTarget.style.color = t.textBright; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.text; }}
    >
      {children}
    </button>
  );

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
          <GhostBtn onClick={onBack}>← new extraction</GhostBtn>
        </nav>

        {/* Results header */}
        <div style={{
          padding: '24px 40px 18px', display: 'flex',
          justifyContent: 'space-between', alignItems: 'flex-end',
          flexShrink: 0,
        }}>
          <div>
            <h2 style={{
              fontSize: 22, fontWeight: 700, color: t.textBright,
              letterSpacing: '-0.025em',
            }}>
              Extraction Results
            </h2>
            <p style={{
              fontSize: 12, color: t.textMuted, fontFamily: t.fontMono, marginTop: 6,
            }}>
              example.com/products · {data.length} rows · {COLUMNS.length} columns
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <GhostBtn>↓ JSON</GhostBtn>
            <GhostBtn>↓ CSV</GhostBtn>
          </div>
        </div>

        {/* Table */}
        <div style={{ flex: 1, overflow: 'auto', padding: '0 40px' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                {COLUMNS.map(col => (
                  <th
                    key={col.key}
                    onClick={() => handleSort(col.key)}
                    style={{
                      padding: '13px 18px', textAlign: col.align,
                      fontSize: 11, fontFamily: t.fontMono, fontWeight: 500,
                      color: t.textMuted, borderBottom: `1px solid ${t.border}`,
                      cursor: 'pointer', userSelect: 'none',
                      textTransform: 'uppercase', letterSpacing: '0.07em',
                      position: 'sticky', top: 0, background: t.bg, zIndex: 2,
                    }}
                  >
                    {col.label}<SortArrow col={col.key} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((row, i) => (
                <tr
                  key={row.id}
                  style={{
                    transition: 'background 0.12s',
                    opacity: appeared ? 1 : 0,
                    animation: appeared ? `pluckFadeIn 0.3s ease ${i * 50}ms both` : 'none',
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = t.surface}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <td style={{ padding: '16px 18px', fontSize: 15, color: t.textBright, borderBottom: `1px solid ${t.border}`, fontWeight: 500 }}>
                    {row.name}
                  </td>
                  <td style={{ padding: '16px 18px', fontSize: 14, fontFamily: t.fontMono, color: t.textBright, textAlign: 'right', borderBottom: `1px solid ${t.border}` }}>
                    ${row.price.toFixed(2)}
                  </td>
                  <td style={{ padding: '16px 18px', fontSize: 14, fontFamily: t.fontMono, color: t.text, textAlign: 'center', borderBottom: `1px solid ${t.border}` }}>
                    {row.rating}
                  </td>
                  <td style={{ padding: '16px 18px', textAlign: 'center', borderBottom: `1px solid ${t.border}` }}>
                    <span style={{
                      display: 'inline-block', padding: '3px 12px',
                      borderRadius: t.radius, fontSize: 12, fontWeight: 500,
                      fontFamily: t.fontMono,
                      background: row.stock ? t.successBg : t.errorBg,
                      color: row.stock ? t.success : t.error,
                    }}>
                      {row.stock ? 'true' : 'false'}
                    </span>
                  </td>
                  <td style={{ padding: '16px 18px', fontSize: 14, color: t.text, borderBottom: `1px solid ${t.border}` }}>
                    {row.category}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Metadata footer */}
        <div style={{
          padding: '14px 40px', borderTop: `1px solid ${t.border}`,
          display: 'flex', gap: 36, fontFamily: t.fontMono, fontSize: 11,
          color: t.textMuted, flexShrink: 0,
        }}>
          <span>model: <span style={{ color: t.text }}>gpt-4o</span></span>
          <span>cost: <span style={{ color: t.text }}>$0.023</span></span>
          <span>time: <span style={{ color: t.text }}>3.2s</span></span>
          <span>tokens: <span style={{ color: t.text }}>1,847</span></span>
        </div>
      </div>
    </FadeIn>
  );
}

Object.assign(window, { ResultsScreen });
