(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const els = {
    formCard: $("form-card"), form: $("job-form"), url: $("url"), file: $("file"),
    drop: $("drop"), dropTitle: $("drop-title"), dropHint: $("drop-hint"),
    model: $("model"), modelNote: $("model-note"), vocals: $("want_vocals"),
    go: $("go"), formError: $("form-error"), limits: $("limits"),
    statusCard: $("status-card"), statusTitle: $("status-title"), statusSub: $("status-sub"),
    pct: $("pct"), fill: $("fill"),
    resultCard: $("result-card"), resultTitle: $("result-title"), player: $("player"),
    downloads: $("downloads"), again: $("again"),
    errorCard: $("error-card"), errorText: $("error-text"), retry: $("retry"),
  };

  const STORAGE_KEY = "sursplit:lastJob";
  const store = {
    get() { try { return localStorage.getItem(STORAGE_KEY); } catch { return null; } },
    set(v) { try { localStorage.setItem(STORAGE_KEY, v); } catch { /* ignore */ } },
    clear() { try { localStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ } },
  };

  let config = null;
  let activeTab = "youtube";
  let pollTimer = null;
  let models = [];

  // ---------- helpers ----------
  const show = (el) => el.classList.remove("hidden");
  const hide = (el) => el.classList.add("hidden");
  const fmtMin = (s) => `${Math.round(s / 60)} min`;
  const fmtBytes = (b) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.round(b / 1024)} KB`);

  function formError(msg) {
    if (!msg) { hide(els.formError); return; }
    els.formError.textContent = msg;
    show(els.formError);
  }

  function setView(view) {
    const views = { form: els.formCard, status: els.statusCard, result: els.resultCard, error: els.errorCard };
    Object.values(views).forEach(hide);
    if (views[view]) show(views[view]);
  }

  function selectTab(name) {
    activeTab = name;
    document.querySelectorAll(".tab").forEach((t) => {
      const on = t.dataset.tab === name;
      t.classList.toggle("active", on);
      t.setAttribute("aria-selected", String(on));
    });
    document.querySelectorAll(".pane").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== name));
    // The helper tab is just instructions, so hide the upload/quality/submit form there.
    els.form.classList.toggle("hidden", name === "helper");
    formError("");
  }

  // ---------- "From YouTube" helper (when the server can't download YouTube itself) ----------
  function setupHelper(siteUrl) {
    let site = "downloader";
    try { site = new URL(siteUrl).hostname.replace(/^www\./, ""); } catch { /* keep default */ }
    $("helper-site").textContent = site;
    const msg = $("helper-msg");

    $("helper-open").addEventListener("click", async () => {
      const link = $("helper-url").value.trim();
      if (link && !/(youtube\.com|youtu\.be)\//i.test(link)) {
        msg.textContent = "That doesn't look like a YouTube link.";
        return;
      }
      // Start the copy while this tab still has focus, then open the site in the same click
      // (opening synchronously keeps pop-up blockers happy).
      const copied = link && navigator.clipboard
        ? navigator.clipboard.writeText(link).then(() => true, () => false)
        : Promise.resolve(false);
      window.open(siteUrl, "_blank", "noopener");
      if (!link) { msg.textContent = `Opened ${site}. Paste your YouTube link there.`; return; }
      msg.textContent = (await copied)
        ? `Link copied. Paste it on ${site}.`
        : `Opened ${site}. Copy your link and paste it there.`;
    });

    $("helper-next").addEventListener("click", () => selectTab("upload"));
  }

  // ---------- config ----------
  async function loadConfig() {
    const res = await fetch("/api/config");
    config = await res.json();
    models = config.models;

    els.model.innerHTML = "";
    for (const m of models) {
      const opt = document.createElement("option");
      opt.value = m.key; opt.textContent = m.label;
      if (m.key === config.default_model) opt.selected = true;
      els.model.appendChild(opt);
    }
    updateModelNote();

    const helper = !config.youtube && config.upload && config.youtube_helper_url;
    if (!config.youtube) { hide($("tab-youtube")); selectTab("upload"); }
    if (!config.upload) { hide($("tab-upload")); selectTab("youtube"); }
    if (helper) {
      show($("tab-helper"));
      setupHelper(config.youtube_helper_url);
      els.dropHint.textContent = "MP3, WAV, FLAC, M4A, OGG… or use the From YouTube tab";
    } else if (!config.youtube || !config.upload) {
      document.querySelector(".tabs").classList.add("hidden");
    }

    const bits = [];
    if (config.max_duration_seconds) bits.push(`Songs up to ${fmtMin(config.max_duration_seconds)}`);
    if (config.upload) bits.push(`uploads up to ${config.max_upload_mb} MB`);
    if (config.file_ttl_minutes) bits.push(`files auto-delete after ${Math.round(config.file_ttl_minutes / 60) || 1} h`);
    els.limits.textContent = bits.join(" · ");
  }

  function updateModelNote() {
    const m = models.find((x) => x.key === els.model.value);
    els.modelNote.textContent = m ? m.note : "";
  }

  // ---------- file picking ----------
  function setFile(file) {
    if (!file) return;
    const dt = new DataTransfer();
    dt.items.add(file);
    els.file.files = dt.files;
    els.dropTitle.textContent = file.name;
    els.dropHint.textContent = fmtBytes(file.size);
    formError("");
  }

  els.file.addEventListener("change", () => setFile(els.file.files[0]));
  ["dragenter", "dragover"].forEach((ev) => els.drop.addEventListener(ev, (e) => {
    e.preventDefault(); els.drop.classList.add("over");
  }));
  ["dragleave", "drop"].forEach((ev) => els.drop.addEventListener(ev, (e) => {
    e.preventDefault(); els.drop.classList.remove("over");
  }));
  els.drop.addEventListener("drop", (e) => setFile(e.dataTransfer.files[0]));

  // ---------- submit ----------
  els.form.addEventListener("submit", async (e) => {
    e.preventDefault();
    formError("");

    const body = new FormData();
    body.append("model", els.model.value);
    body.append("want_vocals", els.vocals.checked ? "true" : "false");

    if (activeTab === "youtube") {
      const url = els.url.value.trim();
      if (!url) return formError("Paste a YouTube link first.");
      if (!/(youtube\.com|youtu\.be)\//i.test(url)) return formError("That doesn't look like a YouTube link.");
      body.append("url", url);
    } else {
      const file = els.file.files[0];
      if (!file) return formError("Choose an audio file first.");
      if (config && file.size > config.max_upload_mb * 1048576) {
        return formError(`That file is over ${config.max_upload_mb} MB.`);
      }
      body.append("file", file);
    }

    els.go.disabled = true;
    els.go.querySelector("span").textContent = activeTab === "upload" ? "Uploading…" : "Starting…";
    try {
      const res = await fetch("/api/jobs", { method: "POST", body });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
      store.set(data.id);
      startPolling(data.id, data);
    } catch (err) {
      formError(err.message || "Could not start the job.");
    } finally {
      els.go.disabled = false;
      els.go.querySelector("span").textContent = "Remove vocals";
    }
  });

  // ---------- polling ----------
  function renderStatus(job) {
    setView("status");
    let title = job.stage_label;
    if (job.status === "queued" && job.queue_position > 1) title = `In queue — position ${job.queue_position}`;
    els.statusTitle.textContent = title + "…";
    els.statusSub.textContent = job.title || "";
    const p = Math.max(1, Math.min(100, Math.round(job.progress)));
    els.pct.textContent = `${p}%`;
    els.fill.style.width = `${p}%`;
    document.title = `${p}% · SurSplit`;
  }

  function renderResult(job) {
    setView("result");
    document.title = "Done · SurSplit";
    els.resultTitle.textContent = job.title || "Your instrumental";
    els.player.src = `${job.files.instrumental_mp3}?inline=true`;

    const items = [
      ["instrumental_mp3", "Instrumental", "MP3 · 320 kbps"],
      ["instrumental_flac", "Instrumental", "FLAC · lossless 24-bit"],
      ["vocals_mp3", "Vocals", "MP3 · 320 kbps"],
      ["vocals_flac", "Vocals", "FLAC · lossless 24-bit"],
    ];
    els.downloads.innerHTML = "";
    for (const [key, name, fmt] of items) {
      if (!job.files[key]) continue;
      const a = document.createElement("a");
      a.className = "dl"; a.href = job.files[key]; a.setAttribute("download", "");
      a.innerHTML = `<span><b></b><small></small></span>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11m0 0 4-4m-4 4-4-4M5 20h14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
      a.querySelector("b").textContent = name;
      a.querySelector("small").textContent = fmt;
      els.downloads.appendChild(a);
    }
  }

  function renderError(msg) {
    setView("error");
    document.title = "SurSplit — Free AI Vocal Remover";
    els.errorText.textContent = msg;
  }

  function stopPolling() { if (pollTimer) clearTimeout(pollTimer); pollTimer = null; }

  function startPolling(id, initial) {
    stopPolling();
    if (initial) renderStatus(initial);
    let failures = 0;

    const tick = async () => {
      try {
        const res = await fetch(`/api/jobs/${id}`);
        if (res.status === 404) { store.clear(); return renderError("This job has expired. Please start again."); }
        const job = await res.json();
        failures = 0;
        if (job.status === "done") { stopPolling(); return renderResult(job); }
        if (job.status === "error") { stopPolling(); store.clear(); return renderError(job.error || "Processing failed."); }
        renderStatus(job);
      } catch {
        if (++failures > 10) return renderError("Lost connection to the server.");
      }
      pollTimer = setTimeout(tick, 1500);
    };
    tick();
  }

  // ---------- reset ----------
  function reset() {
    stopPolling();
    store.clear();
    els.player.pause(); els.player.removeAttribute("src");
    els.url.value = "";
    els.file.value = "";
    els.dropTitle.innerHTML = "Drop a song here or <u>browse</u>";
    els.dropHint.textContent = config && !config.youtube && config.youtube_helper_url
      ? "MP3, WAV, FLAC, M4A, OGG… or use the From YouTube tab" : "MP3, WAV, FLAC, M4A, OGG…";
    document.title = "SurSplit — Free AI Vocal Remover";
    setView("form");
  }

  els.again.addEventListener("click", reset);
  els.retry.addEventListener("click", reset);
  els.model.addEventListener("change", updateModelNote);
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => selectTab(t.dataset.tab)));

  // ---------- boot ----------
  loadConfig()
    .then(() => {
      const last = store.get();
      if (last) startPolling(last);
    })
    .catch(() => formError("Can't reach the server. Is it running?"));
})();
