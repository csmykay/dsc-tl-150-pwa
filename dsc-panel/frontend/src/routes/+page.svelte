<script>
  import { onMount } from 'svelte';
  import { fetchStatus, armStay, armAway, disarm, subscribeSSE, fetchZoneNames, saveZoneNames, fetchConfig } from '$lib/api.js';

  /** @type {import('$lib/api.js').Status | null} */
  let status = null;
  /** @type {import('$lib/api.js').ZoneNames} */
  let zoneNames = {};
  let lastUpdated = '';
  let armingInProgress = false;
  /** Wall-clock end of “arming” UI (yellow) while panel still reports disarmed (exit delay). */
  let armingDeadline = 0;
  /** Tick so countdown / arming window react every second. */
  let tick = 0;
  let dateTime = '';
  /** @type {number | null} */
  let editingZone = null;
  /** @type {number | null} */
  let savedZone = null;
  /** @type {number | null} */
  let expandedZone = null;
  let appTitle = 'Home Security';

  /** @type {{ arming_countdown_secs: number; zone_columns: number; default_arm_mode: string }} */
  let cfg = { arming_countdown_secs: 45, zone_columns: 2, default_arm_mode: 'stay' };

  $: zoneLimit = status?.zone_limit ?? 16;
  $: zoneNumbers = status?.zone_numbers ?? Array.from({ length: zoneLimit }, (_, i) => i + 1);
  $: if (status?.app_title) appTitle = status.app_title;

  /** Prefer status (every poll/SSE); avoids stale 2 when /api/config fails or is cached. */
  function clampZoneCols(v) {
    const n = Number(v);
    return Number.isFinite(n) ? Math.min(3, Math.max(1, n)) : 2;
  }
  $: zoneCols = clampZoneCols(status?.zone_columns ?? cfg.zone_columns);

  /**
   * Stay vs away from settings only (same source as the arm API).
   * Used for labels while arming and while armed — not scraped panel arm_mode.
   */
  $: configArmIsStay =
    String(cfg.default_arm_mode || '')
      .toLowerCase()
      .trim() !== 'away';
  $: armModeLabel = configArmIsStay ? 'Stay' : 'Away';

  // `tick` in the expression so this re-runs every second during countdown (Date.now() is not reactive alone).
  // Keep yellow until armingDeadline even if the panel already reports armed (DSC exit delay vs poll).
  $: inArmingCountdown =
    tick >= 0 &&
    armingInProgress &&
    status &&
    armingDeadline > 0 &&
    Date.now() < armingDeadline;

  $: panelState = !status
    ? 'unknown'
    : inArmingCountdown
      ? 'arming'
      : status.armed
        ? configArmIsStay
          ? 'stay'
          : 'armed'
        : status.ready
          ? 'ready'
          : status.trouble
            ? 'not_ready'
            : 'not_ready';

  $: armingSecsLeft =
    tick >= 0 && inArmingCountdown
      ? Math.max(0, Math.ceil((armingDeadline - Date.now()) / 1000))
      : 0;

  // End yellow UI when the settings-based countdown window ends (always clear timers).
  $: if (tick >= 0 && armingDeadline > 0 && Date.now() >= armingDeadline) {
    armingInProgress = false;
    armingDeadline = 0;
  }

  $: openZones = status?.zones?.filter((z) => z.state === 'open') ?? [];
  $: zonesList = (() => {
    const list = [];
    for (const i of zoneNumbers) {
      const z = status?.zones?.find((x) => x.number === i);
      list.push({
        number: i,
        name: zoneNames[i] ?? zoneNames[String(i)] ?? z?.name ?? `Zone ${i}`,
        state: z?.state ?? 'closed',
        last_activity: z?.last_activity ?? ''
      });
    }
    return list;
  })();

  function setLastUpdated() {
    lastUpdated = new Date().toLocaleTimeString();
  }

  function setDateTime() {
    const d = new Date();
    dateTime = d.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
  }

  async function handleArm() {
    if (armingInProgress || (status && status.armed)) return;
    const raw = Number(cfg.arming_countdown_secs);
    const secs = Number.isFinite(raw) ? Math.min(300, Math.max(5, raw)) : 45;
    armingDeadline = Date.now() + secs * 1000;
    armingInProgress = true;
    try {
      if (String(cfg.default_arm_mode || '').toLowerCase().trim() === 'away') {
        await armAway();
      } else {
        await armStay();
      }
    } catch (_) {
      armingInProgress = false;
      armingDeadline = 0;
    }
  }

  async function handleDisarm() {
    if (!status?.armed) return;
    try {
      await disarm();
    } catch (_) {}
  }

  function zoneName(zone) {
    return zoneNames[zone.number] ?? zoneNames[String(zone.number)] ?? zone.name ?? `Zone ${zone.number}`;
  }

  function updateZoneName(zone, value) {
    zoneNames[zone.number] = value;
    zoneNames = { ...zoneNames };
  }

  async function persistZoneNames(zoneNumber) {
    const toSave = {};
    for (const i of zoneNumbers) {
      toSave[String(i)] = zoneNames[i] ?? zoneNames[String(i)] ?? `Zone ${i}`;
    }
    try {
      await saveZoneNames(toSave);
      savedZone = zoneNumber;
      editingZone = null;
      setTimeout(() => { savedZone = null; }, 2000);
    } catch (_) {}
  }

  function startEdit(zone) {
    editingZone = zone.number;
    expandedZone = null;
  }

  function toggleZoneActivity(zoneNumber) {
    expandedZone = expandedZone === zoneNumber ? null : zoneNumber;
  }

  onMount(() => {
    let cleanup;
    const onMsg = (data) => {
      status = data;
      setLastUpdated();
      // Do not clear arming countdown when panel reports armed — keep yellow for full settings window.
      if (data?.app_title) { appTitle = data.app_title; document.title = data.app_title; }
      // Do not merge status zone names into zoneNames: server names lag until save and
      // would overwrite the input while editing. Names come from fetchZoneNames + local edits.
    };
    cleanup = subscribeSSE(onMsg, () => {});
    const sec = setInterval(() => {
      tick += 1;
    }, 1000);
    fetchConfig()
      .then((c) => {
        appTitle = c.app_title;
        document.title = c.app_title;
        cfg = {
          arming_countdown_secs: (() => {
            const n = Number(c.arming_countdown_secs);
            return Number.isFinite(n) ? Math.min(300, Math.max(5, n)) : 45;
          })(),
          zone_columns: clampZoneCols(c.zone_columns ?? 2),
          default_arm_mode:
            String(c.default_arm_mode || '')
              .toLowerCase()
              .trim() === 'away'
              ? 'away'
              : 'stay'
        };
      })
      .catch((e) => {
        console.warn('[dsc-panel] /api/config failed — zone layout may be wrong until status loads:', e);
      });
    fetchStatus().then((s) => { onMsg(s); if (s.app_title) { appTitle = s.app_title; document.title = s.app_title; } }).catch(() => {});
    fetchZoneNames().then((n) => { zoneNames = { ...n }; zoneNames = zoneNames; }).catch(() => {});
    setDateTime();
    const dateInterval = setInterval(setDateTime, 10000);
    return () => {
      cleanup?.();
      clearInterval(dateInterval);
      clearInterval(sec);
    };
  });
</script>

<div class="app">
  <header>
    <h1>{appTitle}</h1>
    <span class="updated">{dateTime || (status ? lastUpdated : 'Connecting…')}</span>
  </header>

  <div class="status-ring-row">
    <div class="status-ring-wrap">
      <button
        type="button"
        class="status-ring"
        class:clickable={status && (!inArmingCountdown || status.armed)}
        data-state={panelState}
        disabled={!status || (inArmingCountdown && !status.armed)}
        on:click={() => { if (status?.armed) handleDisarm(); else handleArm(); }}
        aria-label={status?.armed ? `Disarm — Armed (${armModeLabel})` : `Arm (${armModeLabel})`}
      >
        <svg viewBox="0 0 100 100" aria-hidden="true">
          <circle class="bg" cx="50" cy="50" r="45" fill="none" stroke="currentColor" stroke-width="8" />
          <circle class="ring" cx="50" cy="50" r="45" fill="none" stroke="currentColor" stroke-width="8"
            stroke-dasharray="283" stroke-dashoffset="0" stroke-linecap="round" />
        </svg>
        <span class="state-label">
          <span class="state-line1">
            {#if panelState === 'arming'}
              Arming ({armModeLabel})…
            {:else}
              {panelState === 'ready' ? 'Ready' : panelState === 'armed' ? 'Armed (Away)' : panelState === 'stay' ? 'Armed (Stay)' : panelState === 'not_ready' ? 'Not Ready' : '…'}
            {/if}
          </span>
          <span class="state-line2">
            {#if panelState === 'armed' || panelState === 'stay'}
              Disarm
            {:else if panelState === 'ready'}
              Arm ({armModeLabel})
            {:else if panelState === 'arming'}
              {armingSecsLeft}s
            {:else}
              &nbsp;
            {/if}
          </span>
        </span>
      </button>
    </div>
    <div class="status-legend" aria-label="Status colors">
      <span class="leg-item"><span class="leg-dot ready"></span> Ready</span>
      <span class="leg-item"><span class="leg-dot arming"></span> Arming</span>
      <span class="leg-item"><span class="leg-dot armed"></span> Armed</span>
      <span class="leg-item"><span class="leg-dot recent"></span> Opened recently</span>
    </div>
  </div>

  {#if openZones.length > 0}
    <div class="open-zones">
      <strong>Open zones:</strong> {openZones.map((z) => zoneName(z)).join(', ')}
    </div>
  {/if}

  <div class="zone-list" style="grid-template-columns: repeat({zoneCols}, 1fr)">
    {#if zonesList.length > 0}
      {#each zonesList as zone (zone.number)}
        <div class="zone-row-wrap">
          <div class="zone-row">
            <button
              type="button"
              class="zone-num"
              on:click={() => toggleZoneActivity(zone.number)}
              title="Last activity"
            >{zone.number}.</button>
            {#if editingZone === zone.number}
              <input
                type="text"
                class="zone-name-input"
                value={zoneName(zone)}
                on:input={(e) => updateZoneName(zone, e.target.value)}
                on:blur={() => persistZoneNames(zone.number)}
                on:keydown={(e) => e.key === 'Enter' && e.target.blur()}
                on:click|stopPropagation
              />
            {:else}
              <button
                type="button"
                class="zone-name-display"
                on:click={() => startEdit(zone)}
              >
                {zoneName(zone)}
              </button>
            {/if}
            {#if savedZone === zone.number}
              <span class="zone-saved">Saved</span>
            {/if}
            <button
              type="button"
              class="zone-state-dot"
              class:open={zone.state === 'open'}
              class:recent={zone.state === 'recent'}
              class:closed={zone.state === 'closed'}
              title={zone.last_activity}
              on:click={() => toggleZoneActivity(zone.number)}
            ></button>
          </div>
          {#if expandedZone === zone.number && zone.last_activity}
            <div class="zone-activity">Last: {zone.last_activity}</div>
          {/if}
        </div>
      {/each}
    {:else}
      <p>Loading zones…</p>
    {/if}
  </div>
</div>

<style>
  :global(body) {
    margin: 0;
    font-family: system-ui, sans-serif;
    background: #0d1117;
    color: #e6edf3;
    min-height: 100vh;
  }
  .app {
    --status-arming-yellow: #e9d85c;
    max-width: 480px;
    margin: 0 auto;
    padding: 1rem;
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
  }
  h1 { font-size: 1.25rem; margin: 0; }
  .updated { font-size: 0.875rem; opacity: 0.8; }
  .status-ring-row {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    gap: 1rem 1.25rem;
    margin-bottom: 1.5rem;
    flex-wrap: wrap;
  }
  .status-ring-wrap {
    display: flex;
    justify-content: center;
    flex-shrink: 0;
  }
  .status-ring {
    position: relative;
    display: block;
    width: 160px;
    height: 160px;
    margin: 0;
    color: #3fb950;
    transition: color 0.3s;
    border: none;
    background: transparent;
    padding: 0;
    cursor: default;
  }
  .status-ring.clickable {
    cursor: pointer;
  }
  .status-ring:disabled {
    cursor: not-allowed;
  }
  .status-ring[data-state="armed"],
  .status-ring[data-state="stay"] { color: #f85149; }
  .status-ring[data-state="arming"] {
    color: var(--status-arming-yellow);
  }
  .status-ring[data-state="arming"] circle {
    stroke: var(--status-arming-yellow);
  }
  .status-ring[data-state="not_ready"] { color: #d29922; }
  .status-ring[data-state="unknown"] { color: #8b949e; }
  .status-ring .bg { opacity: 0.2; }
  .status-ring .ring { transition: stroke-dashoffset 0.3s; }
  .state-label {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    font-weight: 600;
    font-size: 0.9rem;
    pointer-events: none;
  }
  .state-line1 { display: block; }
  .state-line2 { display: block; font-size: 0.75rem; opacity: 0.9; margin-top: 0.15rem; }
  .status-legend {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0.35rem;
    font-size: calc(0.68rem + 3pt);
    color: #8b949e;
    line-height: 1.2;
    min-width: 8.5rem;
  }
  .leg-item {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }
  .leg-dot {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .leg-dot.ready { background: #3fb950; }
  .leg-dot.arming { background: var(--status-arming-yellow); }
  .leg-dot.armed { background: #f85149; }
  .leg-dot.recent { background: #b45309; }
  .open-zones {
    background: #f85149;
    color: #fff;
    padding: 0.5rem 1rem;
    border-radius: 6px;
    margin-bottom: 1rem;
    animation: pulse 1.5s ease-in-out infinite;
  }
  @keyframes pulse { 50% { opacity: 0.9; } }
  .zone-list {
    margin-top: 1rem;
    display: grid;
    gap: 0 1rem;
  }
  .zone-row-wrap {
    border-bottom: 1px solid #21262d;
  }
  .zone-row {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.35rem 0;
  }
  .zone-activity {
    font-size: 0.75rem;
    color: #8b949e;
    padding: 0 0 0.35rem 1.5rem;
  }
  .zone-num {
    flex-shrink: 0;
    width: 1.25rem;
    font-weight: 600;
    font-size: 0.85rem;
    color: #8b949e;
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    text-align: left;
  }
  .zone-num:hover {
    color: #e6edf3;
  }
  .zone-name-display {
    flex: 1;
    min-width: 0;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    color: #e6edf3;
    padding: 0.25rem 0.5rem;
    font-size: 0.85rem;
    text-align: left;
    cursor: pointer;
  }
  .zone-name-display:hover {
    background: #21262d;
    border-color: #30363d;
  }
  .zone-name-input {
    flex: 1;
    min-width: 0;
    background: #0d1117;
    border: 1px solid #58a6ff;
    border-radius: 4px;
    color: #e6edf3;
    padding: 0.25rem 0.5rem;
    font-size: 0.85rem;
  }
  .zone-name-input:focus {
    outline: none;
  }
  .zone-saved {
    flex-shrink: 0;
    font-size: 0.7rem;
    color: #3fb950;
  }
  .zone-state-dot {
    flex-shrink: 0;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    border: none;
    padding: 0;
    cursor: pointer;
  }
  .zone-state-dot.closed { background: #3fb950; }
  .zone-state-dot.open { background: #f85149; }
  .zone-state-dot.recent { background: #b45309; }
</style>
