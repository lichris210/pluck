import React, { useState } from 'react';
import { theme } from './theme.js';
import Login from './screens/Login.jsx';
import Input from './screens/Input.jsx';
import Results from './screens/Results.jsx';

export default function App() {
  const [screen, setScreen]               = useState('login');
  const [items, setItems]                 = useState([]);
  const [extractionMeta, setExtractionMeta] = useState(null);
  const [sourceUrl, setSourceUrl]         = useState('');

  const handleLogin = () => setScreen('input');

  const handleResults = (newItems, url, meta) => {
    setItems(newItems);
    setSourceUrl(url);
    setExtractionMeta(meta);
    setScreen('results');
  };

  const handleBack = () => {
    setItems([]);
    setExtractionMeta(null);
    setSourceUrl('');
    setScreen('input');
  };

  return (
    <div style={{ width: '100vw', height: '100vh', background: theme.bg, overflow: 'hidden' }}>
      {screen === 'login' && (
        <Login onLogin={handleLogin} theme={theme} />
      )}
      {screen === 'input' && (
        <Input onResults={handleResults} theme={theme} />
      )}
      {screen === 'results' && (
        <Results
          items={items}
          sourceUrl={sourceUrl}
          extractionMeta={extractionMeta}
          onBack={handleBack}
          theme={theme}
        />
      )}
    </div>
  );
}
