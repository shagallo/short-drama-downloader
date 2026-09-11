const $ = (id) => document.getElementById(id);

const state = {
  page: 1,
  rows: [],
  activeDrama: null,
  selectedEpisodes: new Set(),
  expandedTasks: new Set(),
  downloads: [],
  paused: false,
  configured: false,
  downloadDir: "",
  detailRequest: 0,
};

const STATUS_LABELS = {
  queued: "等待中",
  pending: "等待",
  downloading: "下载中",
  completed: "已完成",
  failed: "失败",
  paused: "已暂停",
  waiting_config: "等待配置",
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[char]);
}

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 3000);
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.error) {
    throw new Error(data.error || `请求失败 (${response.status})`);
  }
  return data;
}

function showPage(name) {
  document.querySelectorAll(".page").forEach((page) => {
    page.classList.toggle("active", page.id === `${name}Page`);
  });
  document.querySelectorAll("[data-page]").forEach((button) => {
    button.classList.toggle("active", button.dataset.page === name);
  });
  if (name === "downloads") loadDownloads();
  if (name === "settings") Promise.all([loadDownloadSettings(), loadConfig()]);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function normalizeDrama(item) {
  const episodeIds = Array.isArray(item.episode_ids)
    ? item.episode_ids.filter(Boolean).map(String)
    : [];
  return {
    title: item.title || item.name || "未命名短剧",
    seriesId: String(item.drama_id || item.id || ""),
    episodes: item.episodes || (episodeIds.length ? `全${episodeIds.length}集` : "集数未知"),
    episodeIds,
    category: item.category || item.source || "短剧",
    source: item.source || "公开来源",
    sourceUrl: item.source_url || item.url || "",
    coverUrl: item.cover_url || item.pic || "",
    intro: item.desc || "暂无剧情简介。",
    author: item.author || "",
    downloadable: item.downloadable !== false && episodeIds.length > 0,
  };
}

function coverMarkup(drama, className = "") {
  const title = escapeHtml(drama.title);
  if (!drama.coverUrl) {
    return `<div class="poster-placeholder ${className}">${title}</div>`;
  }
  return `<img class="${className}" src="${escapeHtml(drama.coverUrl)}" alt="${title}" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">`;
}

function renderLoading() {
  const cards = Array.from({ length: 10 }, () => '<div class="skeleton"></div>').join("");
  $("dramaGrid").innerHTML = `<div class="loading-grid">${cards}</div>`;
}

function renderDramas() {
  const grid = $("dramaGrid");
  if (!state.rows.length) {
    grid.innerHTML = '<div class="empty-state"><strong>没有找到相关短剧</strong><span>换个关键词或选择“全部”再试试。</span></div>';
    return;
  }

  grid.innerHTML = state.rows.map((drama, index) => {
    const category = drama.category.split("/").map((item) => item.trim()).filter(Boolean)[0] || "短剧";
    return `
      <article class="drama-card" data-drama-index="${index}" tabindex="0">
        <div class="poster">
          ${coverMarkup(drama)}
          <span class="poster-badge">${escapeHtml(drama.episodes)}</span>
          <span class="poster-action">查看详情与选集</span>
        </div>
        <div class="card-body">
          <div class="card-title" title="${escapeHtml(drama.title)}">${escapeHtml(drama.title)}</div>
          <div class="card-meta"><span>${escapeHtml(category)}</span><strong>${drama.downloadable ? "可选集" : "查看详情"}</strong></div>
        </div>
      </article>`;
  }).join("");

  grid.querySelectorAll("[data-drama-index]").forEach((card) => {
    const open = () => openDrama(Number(card.dataset.dramaIndex));
    card.addEventListener("click", open);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") open();
    });
  });
}

async function searchDramas() {
  const button = $("searchBtn");
  button.disabled = true;
  button.textContent = "搜索中";
  renderLoading();
  const keyword = $("keyword").value.trim();
  $("resultTitle").textContent = keyword ? `“${keyword}”相关短剧` : "热门短剧";
  $("searchStatus").textContent = "正在获取剧目...";
  try {
    const data = await api("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        keyword,
        page: state.page,
        source: $("source").value,
        category_filter: "",
      }),
    });
    state.rows = (data.items || []).map(normalizeDrama);
    $("searchStatus").textContent = `找到 ${state.rows.length} 部 · 第 ${state.page} 页`;
    $("pageNumber").textContent = state.page;
    $("previousPage").disabled = state.page <= 1;
    $("nextPage").disabled = !data.has_more;
    renderDramas();
  } catch (error) {
    state.rows = [];
    renderDramas();
    $("searchStatus").textContent = "搜索失败";
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "搜索";
  }
}

function renderDramaDetail(drama) {
  $("detailTitle").textContent = drama.title;
  $("detailSource").textContent = drama.source;
  $("detailIntro").textContent = drama.intro;
  $("detailCover").innerHTML = coverMarkup(drama);
  $("detailSourceLink").href = drama.sourceUrl || "#";
  $("detailSourceLink").style.display = drama.sourceUrl ? "inline-block" : "none";

  const tags = drama.category.split("/").map((item) => item.trim()).filter(Boolean).slice(0, 6);
  $("detailMeta").innerHTML = [drama.episodes, ...tags].map((item) => `<span>${escapeHtml(item)}</span>`).join("");
  renderEpisodePicker();
}

async function openDrama(index) {
  const initialDrama = state.rows[index];
  if (!initialDrama) return;
  const requestId = ++state.detailRequest;
  state.activeDrama = initialDrama;
  state.selectedEpisodes = new Set();
  renderDramaDetail(initialDrama);
  $("detailModal").classList.add("open");
  $("detailModal").setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";

  if (!initialDrama.seriesId || !initialDrama.source.includes("红果")) return;
  $("episodeGrid").innerHTML = '<div class="empty-state"><strong>正在读取完整分集</strong><span>请稍候...</span></div>';
  $("episodeSelection").textContent = "正在校对总集数";
  $("detailNotice").textContent = "正在从剧目详情加载全部分集";
  $("addSelectedEpisodes").disabled = true;
  try {
    const data = await api(`/api/dramas/${encodeURIComponent(initialDrama.seriesId)}`);
    if (requestId !== state.detailRequest) return;
    const completeDrama = normalizeDrama(data.item || {});
    state.rows[index] = completeDrama;
    state.activeDrama = completeDrama;
    state.selectedEpisodes = new Set();
    renderDramaDetail(completeDrama);
  } catch (error) {
    if (requestId !== state.detailRequest) return;
    state.activeDrama = initialDrama;
    renderDramaDetail(initialDrama);
    $("detailNotice").textContent = initialDrama.episodeIds.length
      ? `完整分集加载失败，当前仅可选择 ${initialDrama.episodeIds.length} 集`
      : `完整分集加载失败：${error.message}`;
  }
}

function closeDrama() {
  state.detailRequest += 1;
  $("detailModal").classList.remove("open");
  $("detailModal").setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
}

function renderEpisodePicker() {
  const drama = state.activeDrama;
  const grid = $("episodeGrid");
  const addButton = $("addSelectedEpisodes");
  if (!drama || !drama.episodeIds.length) {
    grid.innerHTML = '<div class="empty-state"><strong>该来源暂无分集数据</strong><span>可以打开来源页继续查看。</span></div>';
    $("episodeSelection").textContent = "暂无可下载分集";
    $("detailNotice").textContent = "只有包含分集视频 ID 的来源可加入下载";
    addButton.disabled = true;
    return;
  }

  grid.innerHTML = drama.episodeIds.map((vid, index) => {
    const selected = state.selectedEpisodes.has(index + 1);
    return `<button class="episode-button ${selected ? "selected" : ""}" type="button" data-episode="${index + 1}" title="视频 ID：${escapeHtml(vid)}">${index + 1}</button>`;
  }).join("");
  grid.querySelectorAll("[data-episode]").forEach((button) => {
    button.addEventListener("click", () => {
      const number = Number(button.dataset.episode);
      if (state.selectedEpisodes.has(number)) state.selectedEpisodes.delete(number);
      else state.selectedEpisodes.add(number);
      renderEpisodePicker();
    });
  });
  const count = state.selectedEpisodes.size;
  $("episodeSelection").textContent = `共 ${drama.episodeIds.length} 集 · 已选择 ${count} 集`;
  $("detailNotice").textContent = count ? `将下载 ${count} 集到当前保存目录` : "请选择需要下载的分集";
  addButton.disabled = count === 0;
}

async function addSelectedEpisodes() {
  const drama = state.activeDrama;
  if (!drama || !state.selectedEpisodes.size) return;
  const waitingForConfig = !state.configured;
  const episodes = [...state.selectedEpisodes].sort((a, b) => a - b).map((number) => ({
    number,
    vid: drama.episodeIds[number - 1],
  }));
  const button = $("addSelectedEpisodes");
  button.disabled = true;
  button.textContent = "正在加入...";
  try {
    await api("/api/downloads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        series_id: drama.seriesId,
        title: drama.title,
        cover_url: drama.coverUrl,
        source: drama.source,
        episodes,
      }),
    });
    closeDrama();
    showPage("downloads");
    showToast(waitingForConfig ? `已加入 ${episodes.length} 集，保存设备配置后会自动下载` : `已加入 ${episodes.length} 集`);
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "加入下载列表";
  }
}

async function loadDownloads() {
  try {
    const data = await api("/api/downloads");
    state.downloads = data.tasks || [];
    state.paused = Boolean(data.paused);
    state.downloadDir = data.download_dir || state.downloadDir;
    renderDownloads();
  } catch (error) {
    showToast(error.message);
  }
}

function taskCoverMarkup(task) {
  if (task.cover_url) {
    return `<img src="${escapeHtml(task.cover_url)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">`;
  }
  return escapeHtml((task.title || "剧").slice(0, 3));
}

function renderDownloads() {
  const tasks = state.downloads;
  const running = tasks.filter((task) => task.status === "downloading").length;
  const queued = tasks.filter((task) => ["queued", "paused", "waiting_config"].includes(task.status)).length;
  const completed = tasks.filter((task) => task.status === "completed").length;
  $("summaryRunning").textContent = running;
  $("summaryQueued").textContent = queued;
  $("summaryCompleted").textContent = completed;
  $("downloadBadge").textContent = tasks.filter((task) => task.status !== "completed").length;
  $("downloadPathSummary").textContent = state.downloadDir || "默认下载目录";
  $("queueStatus").textContent = tasks.length ? `共 ${tasks.length} 部短剧${state.paused ? " · 队列已暂停" : ""}` : "暂无任务";
  $("pauseAll").disabled = state.paused || !tasks.length;
  $("resumeAll").disabled = !state.paused;

  const list = $("downloadList");
  if (!tasks.length) {
    list.innerHTML = '<div class="empty-state"><strong>下载列表还是空的</strong><span>去“发现短剧”中打开剧目并选择分集。</span></div>';
    return;
  }

  list.innerHTML = tasks.map((task) => {
    const expanded = state.expandedTasks.has(task.id);
    const done = task.episodes.filter((episode) => episode.status === "completed").length;
    const failed = task.episodes.filter((episode) => episode.status === "failed").length;
    const episodeRows = task.episodes.map((episode) => `
      <div class="episode-row">
        <strong>第 ${episode.number} 集</strong>
        <span class="episode-message" title="${escapeHtml(episode.message)}">${escapeHtml(episode.message || "等待下载")}</span>
        <span class="episode-state ${escapeHtml(episode.status)}">${escapeHtml(STATUS_LABELS[episode.status] || episode.status)}</span>
      </div>`).join("");
    return `
      <article class="download-task ${expanded ? "expanded" : ""}" data-task-id="${escapeHtml(task.id)}">
        <div class="task-main">
          <button class="task-toggle" type="button" data-action="toggle" aria-label="展开或收起">›</button>
          <div class="task-cover">${taskCoverMarkup(task)}</div>
          <div class="task-info">
            <h3 title="${escapeHtml(task.title)}">${escapeHtml(task.title)}</h3>
            <p>${task.episodes.length} 集 · 已完成 ${done} 集${failed ? ` · 失败 ${failed} 集` : ""}</p>
            <span class="status-pill ${escapeHtml(task.status)}">${escapeHtml(STATUS_LABELS[task.status] || task.status)}</span>
          </div>
          <div class="task-progress">
            <div class="task-progress-head"><span>${escapeHtml(task.message || "")}</span><strong>${Number(task.progress || 0)}%</strong></div>
            <div class="progress-track"><i style="width:${Math.max(0, Math.min(100, Number(task.progress || 0)))}%"></i></div>
          </div>
          <div class="task-actions">
            ${task.status === "failed" ? '<button type="button" data-action="retry">重试失败项</button>' : ""}
            ${task.folder_path ? '<button type="button" data-action="open">打开文件夹</button>' : ""}
            <button class="delete-task" type="button" data-action="delete">删除任务</button>
          </div>
        </div>
        <div class="episode-list">${episodeRows}</div>
      </article>`;
  }).join("");

  list.querySelectorAll("[data-task-id]").forEach((card) => {
    card.querySelectorAll("[data-action]").forEach((button) => {
      button.addEventListener("click", () => handleTaskAction(card.dataset.taskId, button.dataset.action));
    });
  });
}

async function handleTaskAction(taskId, action) {
  if (action === "toggle") {
    if (state.expandedTasks.has(taskId)) state.expandedTasks.delete(taskId);
    else state.expandedTasks.add(taskId);
    renderDownloads();
    return;
  }
  try {
    if (action === "delete") {
      const task = state.downloads.find((item) => item.id === taskId);
      const warning = task?.status === "downloading" ? "该任务正在下载。删除后，当前分集处理完成时会被丢弃，确定继续吗？" : "删除任务记录不会删除已经下载的文件，确定继续吗？";
      if (!window.confirm(warning)) return;
      await api(`/api/downloads/${encodeURIComponent(taskId)}`, { method: "DELETE" });
      state.expandedTasks.delete(taskId);
      showToast("任务已删除");
    } else if (action === "retry") {
      await api(`/api/downloads/${encodeURIComponent(taskId)}/retry`, { method: "POST" });
      showToast("失败分集已重新加入队列");
    } else if (action === "open") {
      const data = await api(`/api/downloads/${encodeURIComponent(taskId)}/open`, { method: "POST" });
      showToast(`已请求打开：${data.path || "任务目录"}`);
    }
    await loadDownloads();
  } catch (error) {
    showToast(error.message);
  }
}

async function controlDownloads(action) {
  try {
    await api("/api/downloads/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    await loadDownloads();
    showToast(action === "pause" ? "队列将在当前分集完成后暂停" : "下载队列已继续");
  } catch (error) {
    showToast(error.message);
  }
}

async function clearTasks(scope) {
  const message = scope === "all" ? "确定清空全部下载任务吗？已下载文件会保留。" : "确定清除所有已完成记录吗？已下载文件会保留。";
  if (!window.confirm(message)) return;
  try {
    const data = await api(`/api/downloads?scope=${scope}`, { method: "DELETE" });
    await loadDownloads();
    showToast(`已清除 ${data.removed || 0} 条记录`);
  } catch (error) {
    showToast(error.message);
  }
}

async function loadDownloadSettings() {
  try {
    const data = await api("/api/download-settings");
    state.downloadDir = data.download_dir || "";
    $("downloadDir").value = state.downloadDir;
    $("downloadDirStatus").textContent = data.error_message || data.notice || (data.writable ? "目录可写" : "目录不可用");
    $("downloadDir").placeholder = data.default_download_dir || "请输入本机目录";
    $("downloadPathSummary").textContent = state.downloadDir || "默认下载目录";
  } catch (error) {
    $("downloadDirStatus").textContent = error.message;
  }
}

async function saveDownloadSettings() {
  const downloadDir = $("downloadDir").value.trim();
  if (!downloadDir) {
    showToast("请输入完整的下载路径");
    return;
  }
  const button = $("saveDownloadDir");
  button.disabled = true;
  try {
    const data = await api("/api/download-settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ download_dir: downloadDir }),
    });
    state.downloadDir = data.download_dir;
    $("downloadDir").value = state.downloadDir;
    $("downloadDirStatus").textContent = "已保存并验证目录";
    $("downloadPathSummary").textContent = state.downloadDir;
    showToast("下载目录已更新");
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
}

async function openDownloadFolder() {
  try {
    const data = await api("/api/download-folder/open", { method: "POST" });
    showToast(`已请求打开：${data.path || state.downloadDir}`);
  } catch (error) {
    showToast(error.message);
  }
}

async function restoreDownloadDirectory() {
  try {
    const data = await api("/api/download-settings");
    $("downloadDir").value = data.default_download_dir;
    await saveDownloadSettings();
  } catch (error) {
    showToast(error.message);
  }
}

async function loadConfig(prefill = false) {
  try {
    const data = await api("/api/config");
    state.configured = Boolean(data.configured);
    $("platform").value = data.platform || "android";
    if (prefill) {
      $("deviceId").value = data.device_id || "";
      $("installId").value = data.install_id || "";
    }
    $("configStatus").textContent = state.configured
      ? `已配置：device ${data.device_id_masked || "-"} · install ${data.install_id_masked || "-"}`
      : "尚未配置。下载分集前需要填写 device_id 和 install_id。";
    const sourceLabels = {
      generated: "原项目工具自动生成",
      manual: "手动保存",
      local: "本机 config.json",
      none: "尚未保存",
    };
    $("configDetail").textContent = data.environment_override
      ? "当前由环境变量覆盖，本机表单无法替换环境变量。"
      : `配置来源：${sourceLabels[data.source] || data.source}`;
  } catch (error) {
    $("configStatus").textContent = `读取失败：${error.message}`;
  }
}

async function saveConfig() {
  const deviceId = $("deviceId").value.trim();
  const installId = $("installId").value.trim();
  if (!deviceId || !installId) {
    showToast("请填写 device_id 和 install_id");
    return;
  }
  const button = $("saveConfig");
  button.disabled = true;
  try {
    await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: deviceId, install_id: installId, platform: $("platform").value }),
    });
    await loadConfig(true);
    await loadDownloads();
    showToast("设备配置已更新，等待任务会自动开始");
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
}

async function generateConfig() {
  if (state.configured && !window.confirm("确定生成并替换当前设备配置吗？未完成任务会使用新配置重试。")) return;
  const button = $("generateConfig");
  button.disabled = true;
  button.textContent = "正在生成...";
  try {
    const data = await api("/api/config/generate", { method: "POST" });
    await loadConfig(true);
    await loadDownloads();
    showToast(data.activation_warning
      ? "新配置已生成，等待任务已开始；辅助激活检查未完成"
      : "新配置已生成，等待任务已自动开始");
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "生成新配置";
  }
}

async function clearConfig() {
  if (!window.confirm("确定清除本机保存的设备配置吗？未完成任务将等待新配置。")) return;
  try {
    const data = await api("/api/config", { method: "DELETE" });
    $("deviceId").value = "";
    $("installId").value = "";
    await loadConfig(true);
    await loadDownloads();
    showToast(data.environment_override ? "本机配置已清除，但环境变量仍在生效" : "本机设备配置已清除");
  } catch (error) {
    showToast(error.message);
  }
}

function toggleConfigVisibility() {
  const showing = $("deviceId").type === "text";
  $("deviceId").type = showing ? "password" : "text";
  $("installId").type = showing ? "password" : "text";
  $("toggleConfig").textContent = showing ? "显示参数" : "隐藏参数";
}

function bindEvents() {
  document.querySelectorAll("[data-page]").forEach((button) => {
    button.addEventListener("click", () => showPage(button.dataset.page));
  });
  $("searchBtn").addEventListener("click", () => {
    state.page = 1;
    searchDramas();
  });
  $("keyword").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      state.page = 1;
      searchDramas();
    }
  });
  $("previousPage").addEventListener("click", () => {
    if (state.page <= 1) return;
    state.page -= 1;
    searchDramas();
  });
  $("nextPage").addEventListener("click", () => {
    state.page += 1;
    searchDramas();
  });
  $("quickFilters").querySelectorAll("[data-keyword]").forEach((button) => {
    button.addEventListener("click", () => {
      $("quickFilters").querySelectorAll("[data-keyword]").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      $("keyword").value = button.dataset.keyword;
      state.page = 1;
      searchDramas();
    });
  });

  $("closeDetail").addEventListener("click", closeDrama);
  $("detailModal").addEventListener("click", (event) => {
    if (event.target === $("detailModal")) closeDrama();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeDrama();
  });
  $("selectAllEpisodes").addEventListener("click", () => {
    if (!state.activeDrama) return;
    state.selectedEpisodes = new Set(state.activeDrama.episodeIds.map((_, index) => index + 1));
    renderEpisodePicker();
  });
  $("invertEpisodes").addEventListener("click", () => {
    if (!state.activeDrama) return;
    const inverted = new Set();
    state.activeDrama.episodeIds.forEach((_, index) => {
      if (!state.selectedEpisodes.has(index + 1)) inverted.add(index + 1);
    });
    state.selectedEpisodes = inverted;
    renderEpisodePicker();
  });
  $("clearEpisodes").addEventListener("click", () => {
    state.selectedEpisodes.clear();
    renderEpisodePicker();
  });
  $("addSelectedEpisodes").addEventListener("click", addSelectedEpisodes);

  $("pauseAll").addEventListener("click", () => controlDownloads("pause"));
  $("resumeAll").addEventListener("click", () => controlDownloads("resume"));
  $("clearCompleted").addEventListener("click", () => clearTasks("completed"));
  $("clearAll").addEventListener("click", () => clearTasks("all"));
  ["headerOpenFolder", "openFolder", "settingsOpenFolder"].forEach((id) => $(id).addEventListener("click", openDownloadFolder));
  $("saveDownloadDir").addEventListener("click", saveDownloadSettings);
  $("restoreDownloadDir").addEventListener("click", restoreDownloadDirectory);
  $("saveConfig").addEventListener("click", saveConfig);
  $("generateConfig").addEventListener("click", generateConfig);
  $("refreshConfig").addEventListener("click", async () => {
    await loadConfig(true);
    showToast("已重新读取本机配置");
  });
  $("toggleConfig").addEventListener("click", toggleConfigVisibility);
  $("clearConfig").addEventListener("click", clearConfig);
}

async function init() {
  localStorage.removeItem("duanju_download_tasks");
  bindEvents();
  await Promise.all([loadConfig(true), loadDownloadSettings(), loadDownloads()]);
  await searchDramas();
  state.polling = setInterval(loadDownloads, 1200);
}

init();
