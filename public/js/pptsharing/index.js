const API = "https://localhost/api/ppt";

let state = {
  role: null, // 'presenter' | 'viewer'
  name: null,
  selectedRole: null, // pending selection before confirm
  currentFile: null,
  currentSlide: 1,
  lastDisplayedSlide: 0, // last slide actually fetched/shown (viewer)
  totalSlides: 0,
  renderPoll: null,
  viewerPoll: null,
  presenterName: null,
};

// ── Toast ──────────────────────────────────────────────────────────────
function toast(msg, type = "info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  const icons = { error: "✕", success: "✓", info: "ℹ" };
  el.innerHTML = `<span>${icons[type] || "ℹ"}</span> ${msg}`;
  document.getElementById("toastContainer").appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ── API helper ────────────────────────────────────────────────────────
async function api(path, options = {}) {
  const res = await fetch(API + path, options);
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("image")) return res.ok ? res.blob() : null;
  const json = await res.json();
  if (!res.ok) throw new Error(json.error || "Request failed");
  return json;
}

// ── Role selection ────────────────────────────────────────────────────
function selectRole(role) {
  state.selectedRole = role;
  document
    .getElementById("cardPresenter")
    .classList.toggle("selected", role === "presenter");
  document
    .getElementById("cardViewer")
    .classList.toggle("selected", role === "viewer");
}

async function confirmRole() {
  const name = document.getElementById("nameInput").value.trim();
  if (!state.selectedRole) {
    toast("Pick a role first", "error");
    return;
  }
  if (!name) {
    toast("Enter your name", "error");
    return;
  }

  state.name = name;
  state.role = state.selectedRole;

  if (state.role === "presenter") {
    try {
      await api("/presenter/join", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
    } catch (e) {
      toast(e.message, "error");
      return;
    }
  }

  // Switch UI: hide role gate, show session sidebar
  document.getElementById("roleGate").classList.add("hidden");
  const sessionSidebar = document.getElementById("sessionSidebar");
  sessionSidebar.classList.remove("hidden");
  sessionSidebar.style.display = "flex";

  if (state.role === "viewer") {
    document.getElementById("uploadSection").classList.add("hidden");
    document.getElementById("viewerNotice").classList.add("show");
    document.getElementById("controls").classList.add("viewer-mode");
    document.getElementById("emptyTitle").textContent =
      "Waiting for presenter…";
    document.getElementById("emptyDesc").textContent =
      "The presenter will load a file and you will follow automatically.";
    startViewerPoll();
  } else {
    document.getElementById("emptyTitle").textContent = "No slide loaded";
    document.getElementById("emptyDesc").textContent =
      "Upload a presentation and select it from the sidebar.";
    initUpload();
  }

  updateRoleBadge();
  updateSessionInfo();
  refreshFiles();
  refreshPresenter();
  toast(`Joined as ${state.role} — ${name}`, "success");

  setInterval(refreshPresenter, 5000);
}

function updateRoleBadge() {
  const dot = document.getElementById("roleDot");
  const label = document.getElementById("roleLabel");
  if (state.role === "presenter") {
    dot.className = "badge-dot presenter";
    label.textContent = `🎤 ${state.name} — Presenter`;
  } else {
    dot.className = "badge-dot viewer";
    label.textContent = `👁 ${state.name} — Viewer`;
  }
}

function updateSessionInfo() {
  const el = document.getElementById("sessionInfo");
  el.textContent =
    state.role === "presenter"
      ? "You control the slides. Viewers follow your navigation."
      : "Slides update automatically when the presenter navigates.";
}

// ── Presenter info polling ───────────────────────────────────────────
async function refreshPresenter() {
  try {
    const res = await api("/presenter");
    const pill = document.getElementById("presenterPill");
    const pname = document.getElementById("presenterName");
    if (res.presenter) {
      state.presenterName = res.presenter;
      pname.textContent = res.presenter;
      pill.classList.add("show");
    } else {
      pill.classList.remove("show");
    }
  } catch {}
}

// ── Upload (presenter only) ──────────────────────────────────────────
function initUpload() {
  const zone = document.getElementById("uploadZone");
  const input = document.getElementById("fileInput");

  zone.addEventListener("dragover", (e) => {
    e.preventDefault();
    zone.classList.add("drag");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("drag");
    if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
  });
  input.addEventListener("change", () => {
    if (input.files[0]) uploadFile(input.files[0]);
  });
}

async function uploadFile(file) {
  const status = document.getElementById("uploadStatus");
  status.classList.add("show");
  status.textContent = `Uploading ${file.name}…`;

  const fd = new FormData();
  fd.append("file", file);

  try {
    const res = await api("/upload", { method: "POST", body: fd });
    status.textContent = `✓ ${res.filename}`;
    toast(`${res.filename} uploaded`, "success");
    refreshFiles();
  } catch (e) {
    status.textContent = "Upload failed.";
    toast(e.message, "error");
  }
}

// ── File list ─────────────────────────────────────────────────────────
async function refreshFiles() {
  try {
    const res = await api("/files");
    const list = document.getElementById("fileList");

    if (!res.files.length) {
      list.innerHTML = '<p class="empty-hint">No files yet.</p>';
      return;
    }

    list.innerHTML = res.files
      .map(
        (f) => `
      <div class="file-item ${state.currentFile === f ? "active" : ""} ${state.role !== "presenter" ? "readonly" : ""}"
           data-filename="${f}">
        <span class="file-icon">${f.endsWith(".pptx") ? "📊" : "📋"}</span>
        <span class="file-name" title="${f}">${f}</span>
        <span class="file-ext">${f.split(".").pop()}</span>
      </div>
    `,
      )
      .join("");

    if (state.role === "presenter") {
      list.querySelectorAll(".file-item").forEach((el) => {
        el.addEventListener("click", () => loadFile(el.dataset.filename));
      });
    }
  } catch {}
}

// ── Load file (presenter only) ───────────────────────────────────────
async function loadFile(filename) {
  if (state.role !== "presenter") return;
  if (state.currentFile === filename) return;

  showSlideLoading(true);
  clearRenderPoll();

  try {
    const res = await api("/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename }),
    });

    state.currentFile = filename;
    state.totalSlides = res.total_slides;
    state.currentSlide = 1;

    refreshFiles();
    updateCounter();
    enableControls(true);
    startRenderPoll();
    toast(`Loaded "${filename}"`, "success");
    fetchSlide(1);
  } catch {
    showSlideLoading(false);
  }
}

// ── Viewer polling (live follow) ─────────────────────────────────────
function startViewerPoll() {
  state.viewerPoll = setInterval(async () => {
    try {
      const res = await api("/slides/current");
      if (!res) return;

      // Discover total slides once we know a presentation is loaded
      if (!state.totalSlides) {
        const count = await api("/slides/count");
        if (count && count.total_slides) {
          state.totalSlides = count.total_slides;
          state.currentFile = state.currentFile || "remote";
          enableControls(false); // viewer controls stay disabled
          updateCounter();
        }
      }

      // Only fetch if the slide actually changed since we last displayed one
      if (res.slide !== state.lastDisplayedSlide) {
        state.currentSlide = res.slide;
        state.lastDisplayedSlide = res.slide; // mark as seen immediately
        state.currentFile = state.currentFile || "remote";
        updateCounter();
        fetchSlide(state.currentSlide);
      }
    } catch {}
  }, 1500);
}

// ── Render progress polling ──────────────────────────────────────────
function startRenderPoll() {
  const wrap = document.getElementById("progressWrap");
  const bar = document.getElementById("progressBar");
  const rs = document.getElementById("renderStatus");
  const dot = document.getElementById("renderDot");
  const txt = document.getElementById("renderText");

  wrap.classList.add("show");
  rs.classList.add("show");
  dot.classList.remove("done");

  state.renderPoll = setInterval(async () => {
    try {
      const res = await api("/slides/count");
      const total = res.total_slides || state.totalSlides;
      const rendered = res.rendered ?? total;
      const pct = total > 0 ? Math.round((rendered / total) * 100) : 0;

      bar.style.width = pct + "%";
      txt.textContent = `Rendering… ${rendered}/${total} slides ready`;

      if (res.ready || pct >= 100) {
        clearRenderPoll();
        bar.style.width = "100%";
        dot.classList.add("done");
        txt.textContent = `All ${total} slides ready`;
        setTimeout(() => {
          wrap.classList.remove("show");
          rs.classList.remove("show");
        }, 3000);
      }
    } catch {
      clearRenderPoll();
    }
  }, 1500);
}

function clearRenderPoll() {
  if (state.renderPoll) {
    clearInterval(state.renderPoll);
    state.renderPoll = null;
  }
}

// ── Slide display ──────────────────────────────────────────────────────
function showSlideLoading(show) {
  document.getElementById("slideLoading").classList.toggle("show", show);
  document
    .getElementById("slideCanvas")
    .classList.toggle("show", !show && !!state.currentFile);
  document.getElementById("emptyState").style.display =
    state.currentFile || show ? "none" : "block";
}

async function fetchSlide(num) {
  showSlideLoading(true);
  try {
    const blob = await api(`/slides/${num}/image`);
    if (!blob) {
      showSlideLoading(false);
      return;
    }

    const img = document.getElementById("slideCanvas");
    const url = URL.createObjectURL(blob);
    img.onload = () => showSlideLoading(false);
    img.src = url;
    img.classList.add("show");

    document.getElementById("emptyState").style.display = "none";
    updateCounter();
  } catch {
    showSlideLoading(false);
  }
}

function fetchCurrentSlide() {
  fetchSlide(state.currentSlide);
}

// ── Navigation (presenter only) ─────────────────────────────────────────
async function nextSlide() {
  if (state.role !== "presenter") return;
  if (state.currentSlide >= state.totalSlides) return;

  await api("/slides/next", { method: "POST" });
  state.currentSlide++;
  fetchCurrentSlide();
}

async function prevSlide() {
  if (state.role !== "presenter") return;
  if (state.currentSlide <= 1) return;

  await api("/slides/prev", { method: "POST" });
  state.currentSlide--;
  fetchCurrentSlide();
}

async function gotoSlide() {
  if (state.role !== "presenter") return;

  const n = parseInt(document.getElementById("gotoInput").value);
  if (!n || n < 1 || n > state.totalSlides) {
    toast(`Enter 1–${state.totalSlides}`, "error");
    return;
  }

  await api("/slides/goto", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slide: n }),
  });

  state.currentSlide = n;
  document.getElementById("gotoInput").value = "";
  fetchCurrentSlide();
}

// ── Counter / controls ────────────────────────────────────────────────
function updateCounter() {
  document.getElementById("slideCounter").textContent = state.totalSlides
    ? `${state.currentSlide} / ${state.totalSlides}`
    : "— / —";

  if (state.role === "presenter") {
    document.getElementById("btnPrev").disabled = state.currentSlide <= 1;
    document.getElementById("btnNext").disabled =
      state.currentSlide >= state.totalSlides;
  }
}

function enableControls(on) {
  if (state.role !== "presenter") return;
  document.getElementById("btnGoto").disabled = !on;
  document.getElementById("btnPrev").disabled = !on || state.currentSlide <= 1;
  document.getElementById("btnNext").disabled =
    !on || state.currentSlide >= state.totalSlides;
}

// ── Event wiring (DOM ready) ───────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  resetState();
  // Role cards
  document
    .getElementById("cardPresenter")
    .addEventListener("click", () => selectRole("presenter"));
  document
    .getElementById("cardViewer")
    .addEventListener("click", () => selectRole("viewer"));

  // Join button
  document.getElementById("btnJoin").addEventListener("click", confirmRole);

  // Navigation buttons
  document.getElementById("btnPrev").addEventListener("click", prevSlide);
  document.getElementById("btnNext").addEventListener("click", nextSlide);
  document.getElementById("btnGoto").addEventListener("click", gotoSlide);

  // Refresh files button
  document
    .getElementById("btnRefreshFiles")
    .addEventListener("click", refreshFiles);

  // Allow Enter key in name input to confirm role
  document.getElementById("nameInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") confirmRole();
  });

  // Allow Enter key in goto input
  document.getElementById("gotoInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") gotoSlide();
  });

  // Keyboard navigation (presenter only)
  document.addEventListener("keydown", (e) => {
    if (state.role !== "presenter" || !state.currentFile) return;
    if (e.target.tagName === "INPUT") return;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") nextSlide();
    if (e.key === "ArrowLeft" || e.key === "ArrowUp") prevSlide();
  });
});

window.addEventListener("beforeunload", () => {
  notifyLeave();
  resetState();
});

// Also handle bfcache restores (back/forward navigation)
window.addEventListener("pageshow", (e) => {
  if (e.persisted) {
    location.reload(); // simplest: force a clean reload from bfcache
  }
});

// ── State reset ──────────────────────────────────────────────────────
function resetState() {
  clearRenderPoll();
  if (state.viewerPoll) {
    clearInterval(state.viewerPoll);
    state.viewerPoll = null;
  }

  state.role = null;
  state.name = null;
  state.selectedRole = null;
  state.currentFile = null;
  state.currentSlide = 1;
  state.lastDisplayedSlide = 0;
  state.totalSlides = 0;
  state.renderPoll = null;
  state.viewerPoll = null;
  state.presenterName = null;
}

// Optional: notify server that this client left (presenter releases role, etc.)
async function notifyLeave() {
  if (state.role === "presenter") {
    try {
      // best-effort, fire-and-forget — use sendBeacon since the page is closing
      navigator.sendBeacon(
        `${API}/presenter/leave`,
        JSON.stringify({ name: state.name }),
      );
    } catch {}
  }
}
