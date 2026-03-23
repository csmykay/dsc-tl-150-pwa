/** @typedef {{ number: number; name?: string; state: string; last_activity: string }} Zone */
/** @typedef {{ app_title?: string; armed: boolean; arm_mode: string|null; ready: boolean; trouble: boolean; raw_system_color: string; zone_limit?: number; zone_numbers?: number[]; zone_columns?: number; zones: Zone[] }} Status */
/** @typedef {{ app_title: string; zone_limit: number; zone_numbers?: number[]; arming_countdown_secs?: number; zone_columns?: number; default_arm_mode?: string }} AppConfig */

/**
 * @returns {Promise<AppConfig>}
 */
export async function fetchConfig() {
  const r = await fetch('/api/config', { cache: 'no-store' });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
/** @typedef {Record<string, string>} ZoneNames */

/**
 * @returns {Promise<ZoneNames>}
 */
export async function fetchZoneNames() {
  const r = await fetch('/api/zone-names', { cache: 'no-store' });
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
  const r = await fetch('/api/status', { cache: 'no-store' });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/**
 * @returns {Promise<{ ok: boolean; action: string }>}
 */
export async function armStay() {
  const r = await fetch('/api/arm/stay', { method: 'POST' });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/**
 * @returns {Promise<{ ok: boolean; action: string }>}
 */
export async function armAway() {
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
