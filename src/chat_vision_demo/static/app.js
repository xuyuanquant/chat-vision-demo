let state = null;
const $ = (id) => document.getElementById(id);
const isMobileView = document.body.classList.contains("mobile-view");

function post(path) {
  return fetch(path, {method: "POST"}).then(async (r) => {
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.error?.message || r.statusText);
    return body;
  }).catch((err) => alert(err.message));
}

document.querySelectorAll("[data-action]").forEach((btn) => {
  btn.addEventListener("click", () => post(btn.dataset.action));
});

if ($("newDemo")) $("newDemo").addEventListener("click", () => post("/api/new-demo"));
if ($("copyUrl")) $("copyUrl").addEventListener("click", () => navigator.clipboard.writeText(location.href));
if ($("downloadJson")) $("downloadJson").addEventListener("click", () => { location.href = "/api/download"; });
if ($("toLatest")) $("toLatest").addEventListener("click", () => scrollLatest(true));
if ($("imageOverlay")) {
  $("imageOverlay").addEventListener("click", (ev) => {
    if (ev.target === $("imageOverlay")) closeImageOverlay();
  });
  $("closeOverlay").addEventListener("click", closeImageOverlay);
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") closeImageOverlay();
  });
}
if ($("pauseResume")) {
  $("pauseResume").addEventListener("click", () => {
    if (state && state.capture_status === "paused") {
      post("/api/resume");
    } else {
      post("/api/pause");
    }
  });
}

function render(next) {
  state = next;
  $("ready").textContent = `Ready: ${state.api.ready?.ok ?? "unknown"}`;
  $("sessionStatus").textContent = `Session: ${state.session.status}`;
  renderMessages();
  if (isMobileView) return;

  $("driver").textContent = `Driver: ${state.driver}`;
  $("mode").textContent = `Mode: ${state.input_mode}`;
  $("stats").innerHTML = [
    `Session ID: ${state.session.session_id || "-"}`,
    `Created: ${state.session.created_at || "-"}`,
    `Expires: ${state.session.expires_at || "-"}`,
    `Screenshots: ${state.counters.screenshots}`,
    `Skipped unchanged: ${state.counters.skipped_unchanged}`,
    `Pushed: ${state.counters.pushed}`,
    `Last capture: ${state.last_capture_at || "-"}`,
    `Remote control: ${state.remote_control ? "enabled" : "read-only on LAN"}`
  ].join("<br>");
  $("phoneUrl").textContent = mobileUrl(state.viewer_urls);
  renderWindow(next.window);

  const prBtn = $("pauseResume");
  if (state.capture_status === "paused") {
    prBtn.textContent = "▶ Resume";
    prBtn.classList.remove("pause");
    prBtn.classList.add("resume");
    prBtn.disabled = false;
  } else if (state.capture_status === "running") {
    prBtn.textContent = "⏸ Pause";
    prBtn.classList.remove("resume");
    prBtn.classList.add("pause");
    prBtn.disabled = false;
  } else {
    prBtn.textContent = "⏸ Pause";
    prBtn.classList.remove("resume");
    prBtn.classList.add("pause");
    prBtn.disabled = true;
  }

  renderApiCalls();
  renderStructured();
}

function renderMessages() {
  const box = $("messages");
  const nearBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 60;
  box.innerHTML = "";
  for (const msg of state.messages.messages) {
    const div = document.createElement("div");
    const role = ["self", "peer"].includes(msg.role) ? msg.role : (msg.message_type === "system" ? "system" : "unknown");
    div.className = `bubble ${role} ${msg.partial ? "partial" : ""}`;
    div.innerHTML = `<span class="tag">${msg.role || "unknown"} · ${msg.message_type || "unknown"} · rev ${msg.revision}</span><br>${escapeHtml(msg.text || "")}`;
    box.appendChild(div);
  }
  $("toLatest").hidden = nearBottom;
  if (nearBottom) scrollLatest(false);
}

function renderApiCalls() {
  $("apiCalls").innerHTML = state.frames.slice().reverse().map((f) => {
    const params = f.request_params || {};
    return `
      <div class="api-call">
        <div class="api-thumb">
          ${f.thumbnail_url ? `<button class="thumb-button" data-preview="${escapeAttr(f.thumbnail_url)}"><img src="${escapeAttr(f.thumbnail_url)}" alt=""></button>` : ""}
        </div>
        <div class="api-main">
          <div class="api-head">
            <strong>${escapeHtml(f.api_method || "POST")} ${escapeHtml(f.api_path || "/v1/sessions/{session_id}/frames")}</strong>
            <span class="status ${escapeAttr(f.status)}">${escapeHtml(f.status)}</span>
          </div>
          <div class="api-meta">
            frame_id ${escapeHtml(f.frame_id)} · req ${escapeHtml(f.request_id || "-")}
          </div>
          <div class="api-params">
            session ${escapeHtml(shortId(params.session_id))} · captured_at ${escapeHtml(params.captured_at || "-")} · file ${escapeHtml(params.file || f.source)}
          </div>
          <div class="api-result">
            new ${f.summary?.new_messages ?? 0}, updated ${f.summary?.updated_messages ?? 0}, total ${f.summary?.total_messages ?? "-"}
            ${f.error_code ? ` · ${escapeHtml(f.error_code)}: ${escapeHtml(f.error_message || "")}` : ""}
          </div>
        </div>
      </div>`;
  }).join("");
  document.querySelectorAll("[data-preview]").forEach((btn) => {
    btn.addEventListener("click", () => openImageOverlay(btn.dataset.preview));
  });
}

function renderStructured() {
  $("structured").textContent = JSON.stringify({
    session: state.session,
    messages: state.messages.messages,
    last_event: state.messages.last_event,
    last_frame_response: state.last_frame_response,
    cursor_error: state.messages.cursor_error,
    viewer_urls: state.viewer_urls
  }, null, 2);
}

function renderWindow(win) {
  const box = $("windowRect");
  if (!box) return;
  if (!win) {
    box.textContent = "Not detected";
    return;
  }
  const rect = win.capture_rect || [];
  box.innerHTML = [
    `<strong>${escapeHtml(win.title || "Window")}</strong>`,
    `x ${rect[0] ?? "-"}, y ${rect[1] ?? "-"}, w ${rect[2] ?? "-"}, h ${rect[3] ?? "-"}`,
    `${escapeHtml(win.process_path || "")}`,
    `Foreground before capture: ${win.foreground_enabled ? "yes" : "no"}`,
    `Foreground success: ${win.foreground_success === null || win.foreground_success === undefined ? "unknown" : (win.foreground_success ? "yes" : "no")}`
  ].join("<br>");
}

function scrollLatest(smooth) {
  const box = $("messages");
  box.scrollTo({top: box.scrollHeight, behavior: smooth ? "smooth" : "auto"});
}

function openImageOverlay(src) {
  if (!$("imageOverlay") || !src) return;
  $("overlayImage").src = src;
  $("imageOverlay").hidden = false;
}

function closeImageOverlay() {
  if (!$("imageOverlay")) return;
  $("imageOverlay").hidden = true;
  $("overlayImage").removeAttribute("src");
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;', "'":'&#39;'}[c]));
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

function shortId(value) {
  if (!value) return "-";
  const text = String(value);
  return text.length > 18 ? `${text.slice(0, 10)}...${text.slice(-6)}` : text;
}

function mobileUrl(urls) {
  const base = urls.public || (urls.lan || [])[0] || urls.local || "";
  return base ? `${base.replace(/\/$/, "")}/mobile` : "";
}

function connect() {
  const events = new EventSource("/api/events");
  events.addEventListener("state", (ev) => render(JSON.parse(ev.data)));
  events.onerror = () => {
    events.close();
    setTimeout(connect, 1500);
  };
}
fetch("/api/state").then((r) => r.json()).then(render);
connect();
