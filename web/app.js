import {channelColor, mapCoordinates, renderMap} from "/map.js";
import {encryptSubmission} from "/leaderboard-crypto.mjs";

const $ = selector => document.querySelector(selector);
const home = $("#home"), gameView = $("#game"), svg = $("#map");
const modeNames = {showcase: "功能展示", omnidirectional: "非定向源", mixed_directional: "有定向源"};
const homepageBoardIds = {
  human_omnidirectional: "#home-board-human-omnidirectional",
  human_mixed_directional: "#home-board-human-mixed-directional",
  strategy_omnidirectional: "#home-board-strategy-omnidirectional",
  strategy_mixed_directional: "#home-board-strategy-mixed-directional",
};
const mapBounds = {x: -2200, y: -2200, width: 4400, height: 4400};
const maxMapZoom = 64;
let state = null, target = {x: 0, y: 0};
let channelSelection = new Set();
let batchCancelled = false, timer = null;
let strategyActive = false, strategyRunning = false, strategyName = null;
let mapView = {...mapBounds}, mapZoom = 1;
let completionShownFor = null;

async function api(path, options = {}) {
  const response = await fetch(path, {headers: {"Content-Type": "application/json"}, ...options});
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "请求失败");
  return body;
}
function notify(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2200);
}
const seconds = value => `${Number(value || 0).toFixed(1)} s`;
const selectedChannel = () => Number($("#action-channel").value || 1);

function addTableCell(row, value, className = "") {
  const cell = document.createElement("td");
  cell.textContent = value;
  if (className) cell.className = className;
  row.append(cell);
  return cell;
}
function renderHomeLeaderboard(category, records) {
  const body = $(homepageBoardIds[category]);
  body.replaceChildren();
  if (!records.length) {
    const row = document.createElement("tr");
    const cell = addTableCell(row, "暂无成绩", "empty-row");
    cell.colSpan = 4; body.append(row); return;
  }
  records.slice(0, 50).forEach((record, index) => {
    const row = document.createElement("tr");
    addTableCell(row, record.rank ?? index + 1);
    const entrant = addTableCell(row, record.nickname);
    if (category.startsWith("strategy_")) {
      const strategy = document.createElement("span");
      strategy.className = "strategy-name";
      strategy.textContent = record.public_strategy_name || "匿名策略";
      entrant.append(strategy);
    }
    addTableCell(row, Number(record.seconds_per_source).toFixed(3));
    const map = category.endsWith("mixed_directional")
      ? `${record.source_count} 源 · ${record.directional_count} 定向`
      : `${record.source_count} 源`;
    addTableCell(row, map);
    body.append(row);
  });
}
async function loadHomeLeaderboards() {
  const statusText = $("#home-leaderboards-status");
  try {
    const status = await api("/api/leaderboard");
    if (!status.configured || !status.leaderboard_url) throw new Error("排行榜尚未配置");
    const base = status.leaderboard_url.endsWith("/") ? status.leaderboard_url : `${status.leaderboard_url}/`;
    const link = $("#home-leaderboards-link");
    link.href = base; link.hidden = false;
    const response = await fetch(new URL("leaderboard.json", base), {cache: "no-store"});
    if (!response.ok) throw new Error(`排行榜数据加载失败 (${response.status})`);
    const data = await response.json();
    for (const [category, selector] of Object.entries(homepageBoardIds)) {
      renderHomeLeaderboard(category, data.categories?.[category] || []);
    }
    statusText.textContent = "每类展示前 50 名 · 每分钟自动更新";
  } catch (error) {
    statusText.textContent = `${error.message}；本地游戏不受影响`;
    for (const category of Object.keys(homepageBoardIds)) renderHomeLeaderboard(category, []);
  }
}
document.querySelectorAll(".home-board").forEach(board => {
  board.querySelectorAll("[data-board-tab]").forEach(button => {
    button.onclick = () => {
      board.querySelectorAll("[data-board-tab]").forEach(item => item.setAttribute("aria-selected", String(item === button)));
      board.querySelectorAll("[data-board-panel]").forEach(panel => { panel.hidden = panel.dataset.boardPanel !== button.dataset.boardTab; });
    };
  });
});

function syncStrategySelectors(name) {
  if (!name) return;
  for (const select of [$("#strategy-select"), $("#strategy-live-select")]) {
    if ([...select.options].some(option => option.value === name)) select.value = name;
  }
}

function hideCompletionResults() {
  $("#completion-dialog").hidden = true;
}
function showCompletionResults() {
  if (!state?.completed || completionShownFor === state.session_id) return;
  completionShownFor = state.session_id;
  strategyRunning = false;
  clearInterval(timer); timer = null;
  const average = state.virtual_time_s / state.source_count;
  const eligible = !state.assisted && state.mode !== "showcase";
  $("#completion-summary").textContent = `全部 ${state.source_count} 个源已清除`;
  $("#result-actor").textContent = state.actor === "strategy" ? `策略 · ${state.strategy_name || strategyName || "未命名"}` : "人工";
  $("#result-mode").textContent = modeNames[state.mode] || state.mode;
  $("#result-source-count").textContent = `${state.source_count} 个`;
  $("#result-source-types-row").hidden = state.mode !== "mixed_directional";
  $("#result-source-types").textContent = `定向 ${state.directional_count} 个 · 非定向 ${state.omnidirectional_count} 个`;
  $("#result-cleared-count").textContent = `${state.cleared_count} / ${state.source_count}`;
  $("#result-virtual-time").textContent = seconds(state.virtual_time_s);
  $("#result-average-time").textContent = `${average.toFixed(2)} 秒/源`;
  $("#result-distance").textContent = `${Number(state.distance_m).toFixed(1)} m`;
  $("#result-assistance").textContent = state.assisted ? "使用过辅助" : "无辅助通关";
  $("#result-leaderboard").textContent = eligible ? "可以提交" : state.mode === "showcase" ? "功能展示不参与" : "不可提交";
  $("#completion-dialog").hidden = false;
}

function applyMapView() {
  svg.setAttribute("viewBox", `${mapView.x} ${mapView.y} ${mapView.width} ${mapView.height}`);
  $("#map-zoom-level").textContent = `${mapZoom.toFixed(mapZoom < 10 ? 1 : 0)}×`;
}
function resetMapView() {
  mapView = {...mapBounds}; mapZoom = 1; applyMapView();
}
function zoomMap(factor, anchor = {x: target.x, y: -target.y}, centerAnchor = false) {
  const nextZoom = Math.min(maxMapZoom, Math.max(1, mapZoom * factor));
  if (nextZoom === mapZoom) return;
  const nextWidth = mapBounds.width / nextZoom, nextHeight = mapBounds.height / nextZoom;
  const xRatio = centerAnchor ? 0.5 : (anchor.x - mapView.x) / mapView.width;
  const yRatio = centerAnchor ? 0.5 : (anchor.y - mapView.y) / mapView.height;
  const minX = mapBounds.x, maxX = mapBounds.x + mapBounds.width - nextWidth;
  const minY = mapBounds.y, maxY = mapBounds.y + mapBounds.height - nextHeight;
  mapView = {
    x: Math.min(maxX, Math.max(minX, anchor.x - xRatio * nextWidth)),
    y: Math.min(maxY, Math.max(minY, anchor.y - yRatio * nextHeight)),
    width: nextWidth,
    height: nextHeight,
  };
  mapZoom = nextZoom; applyMapView();
}

function syncTarget() {
  target = {x: Number($("#target-x").value), y: Number($("#target-y").value)};
  const d = Math.hypot(target.x - state.position[0], target.y - state.position[1]);
  $("#move-preview").textContent = `${d.toFixed(1)} m / ${(d / 5).toFixed(1)} 虚拟秒`;
  renderMap(svg, state, channelSelection, target, selectedChannel());
}
function renderChannels() {
  const container = $("#channels");
  container.replaceChildren();
  state.channels.forEach(item => {
    const row = document.createElement("div");
    row.className = `channel-row ${selectedChannel() === item.channel ? "active" : ""}`;
    row.style.setProperty("--channel-color", channelColor(item.channel));
    const selected = document.createElement("input");
    selected.type = "checkbox";
    selected.checked = channelSelection.has(item.channel);
    selected.title = "选择频道：显示图层并加入批量检测";
    selected.setAttribute("aria-label", `选择频道 ${item.channel}`);
    selected.onchange = () => {
      selected.checked ? channelSelection.add(item.channel) : channelSelection.delete(item.channel);
      renderBatchSummary();
      renderMap(svg, state, channelSelection, target, selectedChannel());
    };
    const button = document.createElement("button");
    button.textContent = `${String(item.channel).padStart(2, "0")} · ${item.status}`;
    button.onclick = () => {
      $("#action-channel").value = String(item.channel);
      channelSelection.add(item.channel);
      renderChannels(); renderBatchSummary();
      renderMap(svg, state, channelSelection, target, selectedChannel());
    };
    row.append(selected, button); container.append(row);
  });
}
function renderBatchSummary() {
  const ordered = [...channelSelection].sort((a, b) => a - b);
  if (ordered.includes(state.current_channel)) { ordered.splice(ordered.indexOf(state.current_channel), 1); ordered.unshift(state.current_channel); }
  const switches = ordered.reduce((sum, ch, index) => sum + (ch !== (index ? ordered[index - 1] : state.current_channel) ? 1 : 0), 0);
  $("#batch-summary").textContent = ordered.length ? `频道 ${ordered.join(" → ")}；预计 ${ordered.length * 5 + switches} 秒` : "未选择频道";
  return ordered;
}
function renderLog() {
  const log = $("#log");
  log.innerHTML = state.events.slice(-80).map(event => {
    const channel = event.channel ? `ch${event.channel} ` : "";
    const result = event.result || (event.success === true ? "success" : event.success === false ? "failed" : "");
    return `<div>#${event.index} ${event.type} ${channel}${result} · ${Number(event.virtual_time_s).toFixed(1)}s</div>`;
  }).join("");
  log.scrollTop = log.scrollHeight;
}
function render() {
  if (!state) return;
  $("#mode-name").textContent = modeNames[state.mode] || state.mode;
  $("#virtual-time").textContent = `虚拟 ${seconds(state.virtual_time_s)}`;
  $("#player-time").textContent = `玩家 ${seconds(state.player_time_s)}`;
  $("#clear-count").textContent = state.source_count === null ? `已清除 ${state.cleared_count}` : `已清除 ${state.cleared_count} / ${state.source_count}`;
  $("#assist-status").textContent = state.assisted ? "辅助局" : "无辅助";
  $("#assist-status").classList.toggle("assisted", state.assisted);
  $("#undo").disabled = !state.can_undo || state.paused;
  $("#pause").textContent = state.paused ? "继续" : "暂停";
  const unavailable = state.paused || state.completed || strategyActive;
  ["move", "measure", "clear", "batch-start", "intel-total", "intel-exists", "intel-position"].forEach(id => $("#" + id).disabled = unavailable);
  $("#strategy-controls").hidden = !strategyActive;
  $("#strategy-status").textContent = strategyActive ? `${strategyName} · ${state.completed ? "已完成" : strategyRunning ? "连续运行中" : "已暂停，可单步"}` : "";
  $("#strategy-step").disabled = strategyRunning || state.paused || state.completed;
  $("#strategy-run").disabled = state.paused || state.completed;
  $("#strategy-run").textContent = strategyRunning ? "暂停连续运行" : "连续运行";
  const eligible = state.completed && !state.assisted && state.mode !== "showcase";
  $("#leaderboard-strategy-label").hidden = state.actor !== "strategy";
  $("#leaderboard-submit").disabled = !eligible;
  $("#leaderboard-eligibility").textContent = eligible
    ? `${state.actor === "strategy" ? "策略" : "人工"} · ${modeNames[state.mode]} · ${(state.virtual_time_s / state.source_count).toFixed(3)} 秒/源`
    : state.assisted ? "本局使用过辅助，不能进入排行榜" : state.mode === "showcase" ? "功能展示不进入排行榜" : "完整无辅助通关后可提交";
  renderChannels(); renderBatchSummary(); renderMap(svg, state, channelSelection, target, selectedChannel()); renderLog();
  showCompletionResults();
}

async function start(mode, selectedStrategy = null) {
  try {
    state = await api("/api/sessions", {method: "POST", body: JSON.stringify({mode})});
    if (selectedStrategy) {
      const started = await api(`/api/sessions/${state.session_id}/strategy/start`, {method: "POST", body: JSON.stringify({name: selectedStrategy})});
      state = started.state; strategyActive = true; strategyName = selectedStrategy;
      syncStrategySelectors(strategyName);
    } else { strategyActive = false; strategyName = null; }
    strategyRunning = false;
    completionShownFor = null; hideCompletionResults();
    localStorage.setItem("arenaSession", state.session_id);
    home.hidden = true; gameView.hidden = false;
    channelSelection = new Set(); target = {x: 0, y: 0};
    resetMapView(); render(); startPolling();
  } catch (error) { notify(error.message); }
}
function startPolling() {
  clearInterval(timer);
  if (state?.completed) { timer = null; return; }
  timer = setInterval(async () => { if (!state) return; try { state = await api(`/api/sessions/${state.session_id}`); render(); } catch {} }, 1000);
}
async function command(action, commandId = crypto.randomUUID()) {
  try {
    state = await api(`/api/sessions/${state.session_id}/actions`, {method: "POST", body: JSON.stringify({action, command_id: commandId})});
    render(); return true;
  } catch (error) { notify(error.message); return false; }
}
async function control(name, payload = {}) {
  try {
    const result = await api(`/api/sessions/${state.session_id}/${name}`, {method: "POST", body: JSON.stringify(payload)});
    state = result.state || result;
    if (result.intel) $("#intel-results").textContent = JSON.stringify(result.intel);
    render();
  } catch (error) { notify(error.message); }
}

async function loadStrategies() {
  try {
    const {strategies} = await api("/api/strategies");
    for (const select of [$("#strategy-select"), $("#strategy-live-select")]) {
      const previous = strategyActive && strategyName ? strategyName : select.value;
      select.replaceChildren();
      strategies.forEach(item => select.add(new Option(item.name, item.name)));
      if (strategies.some(item => item.name === previous)) select.value = previous;
    }
    $("#strategy-start").disabled = strategies.length === 0;
    notify(strategies.length ? `找到 ${strategies.length} 个策略` : "strategies 目录中没有策略");
  } catch (error) { notify(error.message); }
}
async function strategyStep() {
  if (!strategyActive || state.completed) return false;
  try {
    const result = await api(`/api/sessions/${state.session_id}/strategy/step`, {method: "POST", body: "{}"});
    state = result.state; target = {x: state.position[0], y: state.position[1]};
    $("#target-x").value = target.x; $("#target-y").value = target.y;
    render(); return true;
  } catch (error) {
    strategyRunning = false; render(); notify(`策略已暂停：${error.message}`); return false;
  }
}
async function strategyLoop() {
  if (!strategyRunning) return;
  if (await strategyStep() && strategyRunning && !state.completed) setTimeout(strategyLoop, Number($("#strategy-speed").value));
}
async function attachStrategy(name) {
  try {
    strategyRunning = false;
    const result = await api(`/api/sessions/${state.session_id}/strategy/start`, {method: "POST", body: JSON.stringify({name})});
    state = result.state; strategyActive = true; strategyName = name; render();
    syncStrategySelectors(strategyName);
    notify(`已切换到 ${name}，当前地图与进度保留`);
  } catch (error) { notify(error.message); }
}

document.querySelectorAll("[data-mode]").forEach(button => button.onclick = () => start(button.dataset.mode));
$("#strategy-entry").onclick = async () => { $("#strategy-setup").hidden = !$("#strategy-setup").hidden; if (!$("#strategy-setup").hidden) await loadStrategies(); };
$("#strategy-refresh").onclick = loadStrategies;
$("#strategy-live-refresh").onclick = loadStrategies;
$("#strategy-start").onclick = () => start($("#strategy-mode").value, $("#strategy-select").value);
$("#strategy-switch").onclick = () => attachStrategy($("#strategy-live-select").value);
$("#strategy-step").onclick = strategyStep;
$("#strategy-run").onclick = () => { strategyRunning = !strategyRunning; render(); if (strategyRunning) strategyLoop(); };
$("#strategy-stop").onclick = async () => {
  strategyRunning = false;
  try {
    const result = await api(`/api/sessions/${state.session_id}/strategy/stop`, {method: "POST", body: "{}"});
    state = result.state; strategyActive = false; strategyName = null; render();
  } catch (error) { notify(error.message); }
};
function returnHome() {
  strategyRunning = false; hideCompletionResults();
  gameView.hidden = true; home.hidden = false; clearInterval(timer); timer = null;
}
$("#back").onclick = returnHome;
$("#completion-close").onclick = hideCompletionResults;
$("#completion-home").onclick = returnHome;
svg.addEventListener("click", event => { target = mapCoordinates(svg, event); $("#target-x").value = target.x; $("#target-y").value = target.y; syncTarget(); });
svg.addEventListener("wheel", event => {
  event.preventDefault();
  const point = mapCoordinates(svg, event);
  zoomMap(event.deltaY < 0 ? 1.5 : 1 / 1.5, {x: point.x, y: -point.y});
}, {passive: false});
$("#map-zoom-in").onclick = () => zoomMap(2, {x: target.x, y: -target.y}, true);
$("#map-zoom-out").onclick = () => zoomMap(0.5, {x: target.x, y: -target.y}, true);
$("#map-zoom-reset").onclick = resetMapView;
$("#target-x").oninput = syncTarget; $("#target-y").oninput = syncTarget;
$("#move").onclick = () => command({type: "move", x: target.x, y: target.y});
$("#measure").onclick = () => command({type: "measure", channel: selectedChannel()});
$("#clear").onclick = () => command({type: "clear", channel: selectedChannel()});
$("#pause").onclick = () => control(state.paused ? "resume" : "pause"); $("#undo").onclick = () => control("undo");
$("#batch-start").onclick = async () => {
  const ordered = renderBatchSummary(); if (!ordered.length) return;
  batchCancelled = false; $("#batch-cancel").disabled = false;
  const id = `batch-${crypto.randomUUID()}`;
  for (const channel of ordered) { if (batchCancelled || !(await command({type: "measure", channel}, id))) break; }
  $("#batch-cancel").disabled = true;
};
$("#batch-cancel").onclick = () => { batchCancelled = true; $("#batch-cancel").disabled = true; };
$("#channels-all").onclick = () => {
  channelSelection = new Set(state.channels.map(item => item.channel));
  renderChannels(); renderBatchSummary();
  renderMap(svg, state, channelSelection, target, selectedChannel());
};
$("#channels-none").onclick = () => {
  channelSelection.clear();
  renderChannels(); renderBatchSummary();
  renderMap(svg, state, channelSelection, target, selectedChannel());
};
$("#intel-total").onclick = () => control("intel", {kind: "total"});
$("#intel-exists").onclick = () => control("intel", {kind: "channel_exists", channel: selectedChannel()});
$("#intel-position").onclick = () => control("intel", {kind: "channel_position", channel: selectedChannel()});
$("#export-replay").onclick = async () => {
  try {
    const replay = await api(`/api/sessions/${state.session_id}/export`);
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([JSON.stringify(replay, null, 2)], {type: "application/json"}));
    link.download = `arena-${state.session_id}.json`; link.click(); URL.revokeObjectURL(link.href);
  } catch (error) { notify(error.message); }
};
async function pollGitHub(intervalSeconds) {
  await new Promise(resolve => setTimeout(resolve, intervalSeconds * 1000));
  try {
    const result = await api("/api/github/device/poll", {method: "POST", body: "{}"});
    if (result.status === "pending") return pollGitHub(result.interval);
    $("#github-auth").hidden = true;
    notify(`GitHub 已登录：${result.login}`);
    return submitLeaderboard();
  } catch (error) { notify(error.message); }
}
async function submitLeaderboard() {
  try {
    const nickname = $("#leaderboard-nickname").value.trim();
    const publicStrategyName = state.actor === "strategy" ? $("#leaderboard-strategy-name").value.trim() || "匿名策略" : null;
    if (!nickname) throw new Error("请先填写排行榜昵称");
    localStorage.setItem("arenaLeaderboardNickname", nickname);
    $("#leaderboard-stage").textContent = "正在准备加密材料…";
    const prepared = await api(`/api/sessions/${state.session_id}/leaderboard/prepare`, {
      method: "POST",
      body: JSON.stringify({nickname, public_strategy_name: publicStrategyName}),
    });
    if (prepared.status === "needs_auth") {
      $("#leaderboard-stage").textContent = "等待 GitHub 授权…";
      const auth = await api("/api/github/device/start", {method: "POST", body: "{}"});
      $("#github-code").textContent = auth.user_code;
      $("#github-link").href = auth.verification_uri;
      $("#github-auth").hidden = false;
      window.open(auth.verification_uri, "_blank", "noopener");
      notify("请在 GitHub 输入页面上的代码");
      return pollGitHub(auth.interval);
    }
    $("#leaderboard-stage").textContent = "正在本机浏览器加密回放…";
    const submission = await encryptSubmission({
      summary: prepared.summary,
      replay: prepared.replay,
      keyId: prepared.key_id,
      publicKeyJwk: prepared.public_key_jwk,
    });
    $("#leaderboard-stage").textContent = "正在上传加密成绩…";
    const result = await api(`/api/sessions/${state.session_id}/leaderboard/submit`, {
      method: "POST",
      body: JSON.stringify({submission}),
    });
    if (result.status === "needs_auth") return submitLeaderboard();
    $("#pull-request-link").href = result.pull_request_url;
    $("#pull-request-link").hidden = false;
    $("#leaderboard-stage").textContent = "已提交密文，等待 GitHub Actions 验证";
    notify("成绩已提交，等待自动验证");
  } catch (error) {
    $("#leaderboard-stage").textContent = "提交失败，请检查提示后重试";
    notify(error.message);
  }
}
$("#leaderboard-submit").onclick = submitLeaderboard;
$("#leaderboard-nickname").value = localStorage.getItem("arenaLeaderboardNickname") || "";

for (let channel = 1; channel <= 20; channel++) $("#action-channel").add(new Option(String(channel).padStart(2, "0"), channel));
$("#action-channel").onchange = () => {
  channelSelection.add(selectedChannel());
  renderChannels(); renderBatchSummary();
  renderMap(svg, state, channelSelection, target, selectedChannel());
};
const previousSession = localStorage.getItem("arenaSession");
loadHomeLeaderboards();
setInterval(loadHomeLeaderboards, 60000);
if (previousSession) {
  api(`/api/sessions/${previousSession}`).then(restored => {
    state = restored; home.hidden = true; gameView.hidden = false;
    target = {x: state.position[0], y: state.position[1]};
    $("#target-x").value = target.x; $("#target-y").value = target.y;
    resetMapView(); render(); startPolling();
  }).catch(() => localStorage.removeItem("arenaSession"));
}
