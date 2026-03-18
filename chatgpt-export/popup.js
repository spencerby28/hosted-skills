const $ = (id) => document.getElementById(id);

const ui = {
  openChat: $('openChat'),
  captureBtn: $('captureBtn'),
  exportJson: $('exportJson'),
  exportMd: $('exportMd'),
  statusMessage: $('statusMessage'),
  statusIcon: $('statusIcon'),
  statusBar: $('statusBar'),
  lastExport: $('lastExport'),
  lastCount: $('lastCount')
};

// ── Load saved state ─────────────────────────────────────────────────────

async function init() {
  const data = await chrome.storage.local.get([
    'capturedHeaders', 'lastExportAt', 'lastExportCount'
  ]);

  // Check if an export is already running (popup was closed and reopened)
  try {
    const status = await chrome.runtime.sendMessage({ type: 'GET_STATUS' });
    if (status?.exportRunning) {
      setStatus('working', 'Export in progress... keep this tab open.');
      enableExport(false);
      return;
    }
  } catch {}

  if (data.capturedHeaders?.authorization) {
    setStatus('ready', 'Session captured. Ready to export!');
    enableExport(true);
  }

  if (data.lastExportAt) {
    ui.lastExport.textContent = new Date(data.lastExportAt).toLocaleString();
    ui.lastCount.textContent = String(data.lastExportCount || 0);
  }
}

// ── Button Handlers ──────────────────────────────────────────────────────

ui.openChat.addEventListener('click', () => {
  chrome.tabs.create({ url: 'https://chatgpt.com/' });
});

ui.captureBtn.addEventListener('click', async () => {
  try {
    await chrome.runtime.sendMessage({ type: 'ARM_CAPTURE' });
  } catch {
    setStatus('error', 'Extension error. Try reloading the extension.');
    return;
  }
  setStatus('waiting', 'Armed! Now reload your ChatGPT tab (Ctrl+R or Cmd+R).');
  ui.captureBtn.textContent = 'Waiting for reload...';
  ui.captureBtn.disabled = true;

  // Re-enable after 30 seconds in case they missed it
  setTimeout(() => {
    ui.captureBtn.textContent = 'Capture Session';
    ui.captureBtn.disabled = false;
  }, 30000);
});

ui.exportJson.addEventListener('click', () => startExport('json'));
ui.exportMd.addEventListener('click', () => startExport('markdown'));

async function startExport(format) {
  enableExport(false);
  setStatus('working', 'Starting export...');
  try {
    const resp = await chrome.runtime.sendMessage({ type: 'START_EXPORT', format });
    if (resp?.error) {
      setStatus('error', resp.error);
      enableExport(true);
    }
  } catch {
    setStatus('error', 'Extension error. Try reloading the extension.');
    enableExport(true);
  }
}

// ── Progress Listener ────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type !== 'PROGRESS') return;

  switch (msg.status) {
    case 'ready':
      setStatus('ready', msg.message);
      enableExport(true);
      ui.captureBtn.textContent = 'Capture Session';
      ui.captureBtn.disabled = false;
      break;

    case 'listing':
    case 'fetching':
    case 'building':
    case 'waiting':
      setStatus('working', msg.message);
      break;

    case 'done':
      setStatus('done', msg.message);
      enableExport(true);
      chrome.storage.local.get(['lastExportAt', 'lastExportCount'], (data) => {
        ui.lastExport.textContent = new Date(data.lastExportAt).toLocaleString();
        ui.lastCount.textContent = String(data.lastExportCount || 0);
      });
      break;

    case 'error':
      setStatus('error', msg.message);
      enableExport(true);
      break;
  }
});

// ── UI Helpers ───────────────────────────────────────────────────────────

function setStatus(level, message) {
  ui.statusMessage.textContent = message;
  ui.statusBar.className = 'status-bar ' + level;
}

function enableExport(enabled) {
  ui.exportJson.disabled = !enabled;
  ui.exportMd.disabled = !enabled;
}

init();
