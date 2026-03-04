/** @typedef {{ number: number; name?: string; state: string; last_activity: string }} Zone */
/** @typedef {{ app_title?: string; armed: boolean; arm_mode: string|null; ready: boolean; trouble: boolean; raw_system_color: string; zone_limit?: number; zone_numbers?: number[]; zones: Zone[] }} Status */
/** @typedef {{ app_title: string; zone_limit: number; zone_numbers?: number[] }} AppConfig */

/**
 * @returns {Promise<AppConfig>}
 */
export async function fetchConfig() {
  const r = await fetch('/api/config');
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
/** @typedef {Record<string, string>} ZoneNames */

/**
 * @returns {Promise<ZoneNames>}
 */
export async function fetchZoneNames() {
  const r = await fetch('/api/zone-names');
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/**
 * @param {ZoneNames} names
 * @returns {Promise<{ ok: boolean }>}
 */
export async function saveZoneNames(names) {
  const r = await fetch('/api/zone-names', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(names)
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/**
 * @returns {Promise<Status>}
 */
export async function fetchStatus() {
  const r = await fetch('/api/status');
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/**
 * @returns {Promise<{ ok: boolean; action: string }>}
 */
export async function arm() {
  const r = await fetch('/api/arm/away', { method: 'POST' });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/**
 * @returns {Promise<{ ok: boolean; action: string }>}
 */
export async function disarm() {
  const r = await fetch('/api/disarm', { method: 'POST' });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/**
 * @param {(data: Status) => void} onMessage
 * @param {(err: Event) => void} [onError]
 * @returns {() => void} cleanup
 */
export function subscribeSSE(onMessage, onError) {
  const es = new EventSource('/api/events');
  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      onMessage(data);
    } catch (_) {}
  };
  es.onerror = (err) => onError?.(err);
  return () => es.close();
}
