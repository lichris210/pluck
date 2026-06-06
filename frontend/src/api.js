export function getStoredToken() {
  return localStorage.getItem('pluck_token');
}

export function setStoredToken(token) {
  localStorage.setItem('pluck_token', token);
}

export function clearToken() {
  localStorage.removeItem('pluck_token');
}

export async function login(password) {
  const res = await fetch('/api/auth', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) throw new Error('Invalid password');
  const data = await res.json();
  setStoredToken(data.token);
  return data.token;
}

export async function classify(url) {
  const token = getStoredToken();
  const res = await fetch('/api/classify', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) throw new Error('Classification failed');
  return res.json();
}

/**
 * Open an SSE stream to /api/extract.
 * Returns { close } to cancel early.
 */
export function extractSSE(url, schema, callbacks, maxItems = 100, prompt = null, forceApify = false) {
  const token = getStoredToken();
  const params = new URLSearchParams({ url, token, max_items: String(maxItems) });
  if (schema) params.set('schema', JSON.stringify(schema));
  if (prompt && prompt.trim()) params.set('prompt', prompt.trim());
  if (forceApify) params.set('force_apify', 'true');

  const evtSource = new EventSource(`/api/extract?${params}`);

  evtSource.onmessage = (e) => {
    let payload;
    try {
      payload = JSON.parse(e.data);
    } catch {
      return;
    }

    if (payload.step === 'done' && payload.status === 'done') {
      evtSource.close();
      callbacks.onDone?.(payload);
    } else if (payload.status === 'error') {
      evtSource.close();
      callbacks.onError?.(payload.error || 'Unknown error');
    } else if (payload.step === 'discovery') {
      // Discovery is backend telemetry: the event is still parsed and received,
      // but kept out of the visible UI. Log it for DevTools debugging only.
      console.info('[pluck] discovery event', payload);
    } else {
      callbacks.onStep?.(payload);
    }
  };

  evtSource.onerror = () => {
    evtSource.close();
    callbacks.onError?.('Connection lost');
  };

  return { close: () => evtSource.close() };
}
