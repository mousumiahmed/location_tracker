// renderer.js
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const consentBtn = document.getElementById('consentBtn');
const status = document.getElementById('status');
const log = document.getElementById('log');
const userIdInput = document.getElementById('userId');
const serverUrlInput = document.getElementById('serverUrl');

let watchId = null;
let incidentId = null;
let authToken = null; // will be a short JWT obtained after consent (demo)

function appendLog(msg) {
  const ts = new Date().toISOString();
  log.value = `[${ts}] ${msg}\n` + log.value;
}

// Demo: register consent -> server returns a JWT token for this user (in real app: login + consent)
consentBtn.onclick = async () => {
  const userId = userIdInput.value.trim();
  const server = serverUrlInput.value.trim();
  if (!userId || !server) { alert('Please set user id and server URL'); return; }

  // Capture consent locally & send to server
  const consentText = 'User consents to emergency location sharing while active. Retention 30 days.';
  appendLog('Sending consent to server...');
  try {
    const resp = await fetch(`${server}/v1/consent/register`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ user_id: userId, consent_text: consentText })
    });
    if (!resp.ok) throw new Error('server error ' + resp.status);
    const data = await resp.json();
    authToken = data.token; // server returns a demo JWT token
    appendLog('Consent registered. Received auth token.');
    status.textContent = 'Consent granted. Ready to share.';
    startBtn.disabled = false;
  } catch (err) {
    appendLog('Failed to register consent: ' + err.message);
    status.textContent = 'Consent registration failed.';
  }
};

startBtn.onclick = async () => {
  if (!authToken) { alert('Please register consent first'); return; }
  const userId = userIdInput.value.trim();
  const server = serverUrlInput.value.trim();

  // Create an incident on server
  incidentId = 'inc-' + Date.now();
  try {
    const resp = await fetch(`${server}/v1/incident/start`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + authToken
      },
      body: JSON.stringify({ user_id: userId, incident_id: incidentId, timestamp: new Date().toISOString() })
    });
    if (!resp.ok) throw new Error('server returned ' + resp.status);
  } catch (err) {
    appendLog('Failed to create incident: ' + err.message);
  }

  // start watching location
  if (!('geolocation' in navigator)) {
    alert('Geolocation not supported by your system.');
    return;
  }

  status.textContent = 'Requesting location permission...';
  watchId = navigator.geolocation.watchPosition(async (pos) => {
    const payload = {
      user_id: userId,
      incident_id: incidentId,
      lat: pos.coords.latitude,
      lon: pos.coords.longitude,
      accuracy: pos.coords.accuracy,
      timestamp: new Date(pos.timestamp).toISOString()
    };
    appendLog(`Sending location ${payload.lat.toFixed(5)},${payload.lon.toFixed(5)} acc:${payload.accuracy}`);
    try {
      await fetch(`${server}/v1/incident/update`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + authToken
        },
        body: JSON.stringify(payload)
      });
      status.textContent = `Sharing: ${payload.lat.toFixed(5)}, ${payload.lon.toFixed(5)} (acc ${payload.accuracy}m)`;
    } catch (err) {
      appendLog('Error sending location: ' + err.message);
      status.textContent = 'Network error while sharing.';
    }
  }, (err) => {
    appendLog('Geolocation error: ' + err.message);
    status.textContent = 'Geolocation error or permission denied.';
  }, { enableHighAccuracy: true, maximumAge: 3000, timeout: 10000 });

  startBtn.disabled = true;
  stopBtn.disabled = false;
  appendLog('Started sharing.');
};

stopBtn.onclick = async () => {
  if (watchId !== null) {
    navigator.geolocation.clearWatch(watchId);
    watchId = null;
  }
  if (!authToken || !incidentId) {
    appendLog('No active incident.');
    status.textContent = 'Stopped sharing.';
    startBtn.disabled = false;
    stopBtn.disabled = true;
    return;
  }
  const server = serverUrlInput.value.trim();
  try {
    await fetch(`${server}/v1/incident/stop`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + authToken
      },
      body: JSON.stringify({ incident_id: incidentId })
    });
    appendLog('Notified server to stop incident.');
  } catch (err) {
    appendLog('Error stopping incident: ' + err.message);
  }
  status.textContent = 'Stopped sharing.';
  startBtn.disabled = false;
  stopBtn.disabled = true;
};
