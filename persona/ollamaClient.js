/**
 * Lucy ↔ Ollama client
 * =====================
 * Talks to the local Ollama instance (http://localhost:11434).
 * Falls back gracefully if Ollama isn't running.
 *
 * Preferred models (in order):
 *   llama3.2, llama3, mistral, llama2, tinyllama, phi3, gemma2
 */

const OLLAMA_BASE = process.env.OLLAMA_HOST || 'http://127.0.0.1:11434';

// Which model to use — override with env var LUCY_MODEL
const PREFERRED_MODELS = [
  'llama3.2', 'llama3.2:latest',
  'llama3', 'llama3:latest',
  'mistral', 'mistral:latest',
  'llama2', 'llama2:latest',
  'phi3', 'phi3:latest',
  'gemma2', 'gemma2:latest',
  'tinyllama', 'tinyllama:latest',
];

let _cachedModel = null;
let _ollamaAvailable = null;  // null = unchecked, true/false = checked

/**
 * Check if Ollama is running and find the best available model.
 * Returns { available: bool, model: string|null, models: string[] }
 */
export async function checkOllama() {
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 3000);
    const res = await fetch(`${OLLAMA_BASE}/api/tags`, { signal: ctrl.signal });
    clearTimeout(timer);

    if (!res.ok) {
      _ollamaAvailable = false;
      return { available: false, model: null, models: [] };
    }

    const data = await res.json();
    const installed = (data.models || []).map(m => m.name);

    // Find the best model from our preference list
    let best = process.env.LUCY_MODEL || null;
    if (!best) {
      for (const preferred of PREFERRED_MODELS) {
        if (installed.some(m => m === preferred || m.startsWith(preferred.split(':')[0] + ':'))) {
          best = installed.find(m => m === preferred || m.startsWith(preferred.split(':')[0] + ':'));
          break;
        }
      }
    }
    // Fallback: just use the first installed model
    if (!best && installed.length > 0) best = installed[0];

    _ollamaAvailable = true;
    _cachedModel = best;
    return { available: true, model: best, models: installed };
  } catch {
    _ollamaAvailable = false;
    return { available: false, model: null, models: [] };
  }
}

/**
 * Send a message to Ollama and get a streamed/complete response.
 *
 * @param {string} systemPrompt - Lucy's identity + context
 * @param {Array<{role:string, content:string}>} history - conversation history
 * @param {string} userMessage - the new user message
 * @param {string|null} modelOverride - force a specific model
 * @returns {Promise<{ok: boolean, text: string, model: string|null, error: string|null}>}
 */
export async function chatWithOllama(systemPrompt, history, userMessage, modelOverride = null) {
  // Check availability (cached after first call)
  if (_ollamaAvailable === false) {
    return { ok: false, text: null, model: null, error: 'Ollama not running' };
  }
  if (_ollamaAvailable === null) {
    const check = await checkOllama();
    if (!check.available || !check.model) {
      return { ok: false, text: null, model: null, error: 'Ollama not available or no models installed' };
    }
  }

  const model = modelOverride || _cachedModel;
  if (!model) {
    return { ok: false, text: null, model: null, error: 'No Ollama model available' };
  }

  // Build messages array for Ollama /api/chat
  const messages = [
    { role: 'system', content: systemPrompt },
    ...history.map(m => ({ role: m.role === 'lucy' ? 'assistant' : m.role, content: m.text || m.content || '' })),
    { role: 'user', content: userMessage },
  ];

  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 60000);  // 60s timeout

    const res = await fetch(`${OLLAMA_BASE}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: ctrl.signal,
      body: JSON.stringify({
        model,
        messages,
        stream: false,
        options: {
          temperature: 0.7,
          num_predict: 512,
        },
      }),
    });

    clearTimeout(timer);

    if (!res.ok) {
      const errText = await res.text().catch(() => res.statusText);
      return { ok: false, text: null, model, error: `Ollama error ${res.status}: ${errText}` };
    }

    const data = await res.json();
    const text = data?.message?.content || data?.response || '';

    return { ok: true, text: text.trim(), model, error: null };

  } catch (err) {
    _ollamaAvailable = false;  // Mark as unavailable to avoid repeated failures
    return { ok: false, text: null, model, error: err.name === 'AbortError' ? 'Ollama timeout (60s)' : err.message };
  }
}

/**
 * Get current Ollama status for the /health endpoint.
 */
export async function getOllamaStatus() {
  const check = await checkOllama();
  return {
    available:  check.available,
    model:      check.model,
    models:     check.models,
    host:       OLLAMA_BASE,
  };
}