<script>
  import { onMount } from 'svelte';
  import { fetchStatus, arm, disarm, subscribeSSE, fetchZoneNames, saveZoneNames, fetchConfig } from '$lib/api.js';

  /** @type {import('$lib/api.js').Status | null} */
  let status = null;
  /** @type {import('$lib/api.js').ZoneNames} */
  let zoneNames = {};
  let lastUpdated = '';
  let armingInProgress = false;
  let dateTime = '';
  /** @type {number | null} */
  let editingZone = null;
  /** @type {number | null} */
  let savedZone = null;
  /** @type {number | null} */
  let expandedZone = null;
  let appTitle = 'Home Security';

  $: zoneLimit = status?.zone_limit ?? 16;
  $: if (status?.app_title) appTitle = status.app_title;

  $: panelState = !status ? 'unknown'
    : armingInProgress ? 'arming'
    : status.armed ? (status.arm_mode === 'stay' ? 'stay' : 'armed')
    : status.ready ? 'ready'
    : status.trouble ? 'not_ready'
    : 'not_ready';

  $: openZones = status?.zones?.filter((z) => z.state === 'open') ?? [];
  $: zonesList = (() => {
    const list = [];
    for (let i = 1; i <= zoneLimit; i++) {
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
    armingInProgress = true;
    try {
      await arm();
    } catch (_) {
      armingInProgress = false;
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
    for (let i = 1; i <= zoneLimit; i++) {
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
      if (data?.armed) armingInProgress = false;
      if (data?.app_title) { appTitle = data.app_title; document.title = data.app_title; }
    };
    cleanup = subscribeSSE(onMsg, () => {});
    fetchConfig().then((c) => { appTitle = c.app_title; document.title = c.app_title; }).catch(() => {});
    fetchStatus().then((s) => { onMsg(s); if (s.app_title) { appTitle = s.app_title; document.title = s.app_title; } }).catch(() => {});
    fetchZoneNames().then((n) => { zoneNames = { ...n }; zoneNames = zoneNames; }).catch(() => {});
    setDateTime();
    const dateInterval = setInterval(setDateTime, 10000);
    return () => {
      cleanup?.();
      clearInterval(dateInterval);
    };
  });
</script>

<div class="app">
  <header>
    <h1>{appTitle}</h1>
    <span class="updated">{dateTime || (status ? lastUpdated : 'Connecting…')}</span>
  </header>

  <div class="status-ring-wrap">
  <button
    type="button"
    class="status-ring"
    class:clickable={status && !armingInProgress}
    data-state={panelState}
    disabled={!status || armingInProgress}
    on:click={() => { if (status?.armed) handleDisarm(); else handleArm(); }}
    aria-label={status?.armed ? 'Disarm' : 'Arm'}
  >
    <svg viewBox="0 0 100 100" aria-hidden="true">
      <circle class="bg" cx="50" cy="50" r="45" fill="none" stroke="currentColor" stroke-width="8" />
      <circle class="ring" cx="50" cy="50" r="45" fill="none" stroke="currentColor" stroke-width="8"
        stroke-dasharray="283" stroke-dashoffset="0" stroke-linecap="round" />
    </svg>
    <span class="state-label">
      <span class="state-line1">
        {#if panelState === 'arming'}
          Arming<span class="arming-dots"><span class="dot">.</span><span class="dot">.</span><span class="dot">.</span></span>
        {:else}
          {panelState === 'ready' ? 'Ready' : panelState === 'armed' || panelState === 'stay' ? 'Armed' : panelState === 'not_ready' ? 'Not Ready' : '…'}
        {/if}
      </span>
      <span class="state-line2">
        {#if panelState === 'armed' || panelState === 'stay'}
          Disarm
        {:else if panelState === 'ready'}
          Arm
        {:else}
          &nbsp;
        {/if}
      </span>
    </span>
  </button>
  </div>

  {#if openZones.length > 0}
    <div class="open-zones">
      <strong>Open zones:</strong> {openZones.map((z) => zoneName(z)).join(', ')}
    </div>
  {/if}

  <div class="zone-list">
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
              class:closed={zone.state === 'closed' || zone.state === 'recent'}
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
  .status-ring-wrap {
    display: flex;
    justify-content: center;
    margin-bottom: 1.5rem;
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
  .status-ring[data-state="arming"],
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
  .arming-dots { display: inline; }
  .arming-dots .dot {
    animation: arming-blink 0.6s ease-in-out infinite;
  }
  .arming-dots .dot:nth-child(1) { animation-delay: 0s; }
  .arming-dots .dot:nth-child(2) { animation-delay: 0.2s; }
  .arming-dots .dot:nth-child(3) { animation-delay: 0.4s; }
  @keyframes arming-blink {
    0%, 100% { opacity: 0.3; }
    50% { opacity: 1; }
  }
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
    grid-template-columns: 1fr 1fr;
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
</style>
