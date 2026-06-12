/* ===== CodEdu Core JS ===== */

const API_BASE = '';

// ===== Token Management =====
const Auth = {
  getToken() { return localStorage.getItem('codedu_token'); },
  setToken(token) { localStorage.setItem('codedu_token', token); },
  getUser() { const u = localStorage.getItem('codedu_user'); return u ? JSON.parse(u) : null; },
  setUser(user) { localStorage.setItem('codedu_user', JSON.stringify(user)); },
  logout() { localStorage.removeItem('codedu_token'); localStorage.removeItem('codedu_user'); window.location.href = '/login.html'; },
  isLoggedIn() { return !!this.getToken(); },
  requireAuth() { if (!this.isLoggedIn()) window.location.href = '/login.html'; },
};

// ===== API Client =====
async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json' };
  const token = Auth.getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (options.headers) Object.assign(headers, options.headers);

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  // Read raw text first
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = { raw: text }; }

  if (!res.ok) {
    const msg = data.error || `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

async function apiPost(path, body) {
  return api(path, { method: 'POST', body: JSON.stringify(body) });
}

async function apiPostBinary(path, binaryData) {
  const headers = { 'Content-Type': 'application/octet-stream' };
  const token = Auth.getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST', headers, body: binaryData });
  const text = await res.text();
  try { return JSON.parse(text); } catch { return { raw: text }; }
}

// ===== Toast Notifications =====
function showToast(message, type = 'info') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 3500);
}

// ===== Mobile Navigation =====
function toggleSidebar() {
  document.body.classList.toggle('sidebar-open');
}

function closeSidebar() {
  document.body.classList.remove('sidebar-open');
}

// ===== SSE Manager =====
class SSEConnection {
  constructor(url) {
    this.url = url;
    this.handlers = {};
    this.source = null;
    this.retryCount = 0;
  }

  connect() {
    const token = Auth.getToken();
    // SSE doesn't support custom headers, pass token as query param
    const sep = this.url.includes('?') ? '&' : '?';
    this.source = new EventSource(`${API_BASE}${this.url}${sep}token=${token}`);

    this.source.onopen = () => { this.retryCount = 0; console.log(`[SSE] Connected: ${this.url}`); };
    this.source.onerror = (e) => {
      console.warn(`[SSE] Error on ${this.url}`, e);
      this.source.close();
      if (this.retryCount < 5) { this.retryCount++; setTimeout(() => this.connect(), 2000 * this.retryCount); }
    };

    // Register all event listeners
    for (const [event, handler] of Object.entries(this.handlers)) {
      this.source.addEventListener(event, (e) => {
        try {
          const data = JSON.parse(e.data);
          handler(data);
        } catch { handler(e.data); }
      });
    }
  }

  on(event, handler) {
    this.handlers[event] = handler;
    if (this.source && this.source.readyState !== 2) {
      this.source.addEventListener(event, (e) => {
        try { handler(JSON.parse(e.data)); } catch { handler(e.data); }
      });
    }
    return this;
  }

  close() { if (this.source) { this.source.close(); this.source = null; } }
}

// ===== Screen Capture =====
class ScreenCapture {
  constructor(classroomId) {
    this.classroomId = classroomId;
    this.stream = null;
    this.capturing = false;
    this.canvas = document.createElement('canvas');
    this.ctx = this.canvas.getContext('2d');
    this.video = document.createElement('video');
    this.fps = 5; // 5 frames per second
  }

  async start() {
    try {
      this.stream = await navigator.mediaDevices.getDisplayMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 5 } }
      });
      this.video.srcObject = this.stream;
      await this.video.play();
      this.canvas.width = 1280;
      this.canvas.height = 720;
      this.capturing = true;
      this._captureLoop();
      showToast('Screen sharing started', 'success');

      // Handle stream end (user clicks "Stop sharing" in browser UI)
      this.stream.getVideoTracks()[0].onended = () => this.stop();
    } catch (e) {
      showToast('Failed to start screen sharing: ' + e.message, 'error');
      throw e;
    }
  }

  async _captureLoop() {
    if (!this.capturing) return;
    this.ctx.drawImage(this.video, 0, 0, 1280, 720);
    this.canvas.toBlob(async (blob) => {
      if (blob && this.capturing) {
        const buf = await blob.arrayBuffer();
        await apiPostBinary(`/api/classroom/${this.classroomId}/screen/frame`, buf);
      }
      if (this.capturing) setTimeout(() => this._captureLoop(), 1000 / this.fps);
    }, 'image/jpeg', 0.6);
  }

  async stop() {
    this.capturing = false;
    if (this.stream) { this.stream.getTracks().forEach(t => t.stop()); this.stream = null; }
    await apiPost(`/api/classroom/${this.classroomId}/screen/stop`, {});
    showToast('Screen sharing stopped', 'info');
  }
}

// ===== Utility =====
function formatDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  const now = new Date();
  const diff = now - d;
  if (diff < 60000) return 'just now';
  if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
  if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
