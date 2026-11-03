const els = {
  userId: document.querySelector("#userId"),
  threadId: document.querySelector("#threadId"),
  agentRole: document.querySelector("#agentRole"),
  topbarAgentRole: document.querySelector("#topbarAgentRole"),
  agentPrompt: document.querySelector("#agentPrompt"),
  skillOptions: document.querySelector("#skillOptions"),
  runId: document.querySelector("#runId"),
  status: document.querySelector("#status"),
  statusDot: document.querySelector("#statusDot"),
  settingsPanel: document.querySelector("#settingsPanel"),
  settingsToggle: document.querySelector("#settingsTop"),
  workspace: document.querySelector(".workspace"),
  appSidebar: document.querySelector(".app-sidebar"),
  settingsBackdrop: document.querySelector("#settingsBackdrop"),
  currentUserName: document.querySelector("#currentUserName"),
  currentUserLevel: document.querySelector("#currentUserLevel"),
  logoutButton: document.querySelector("#logoutButton"),
  adminButton: document.querySelector("#adminButton"),
  adminPanel: document.querySelector("#adminPanel"),
  adminClose: document.querySelector("#adminClose"),
  adminError: document.querySelector("#adminError"),
  adminStatus: document.querySelector("#adminStatus"),
  adminSearchForm: document.querySelector("#adminSearchForm"),
  adminSearch: document.querySelector("#adminSearch"),
  adminSearchButton: document.querySelector("#adminSearchButton"),
  adminNew: document.querySelector("#adminNew"),
  adminUsers: document.querySelector("#adminUsers"),
  adminCount: document.querySelector("#adminCount"),
  adminPrev: document.querySelector("#adminPrev"),
  adminNext: document.querySelector("#adminNext"),
  accountForm: document.querySelector("#accountForm"),
  accountFormTitle: document.querySelector("#accountFormTitle"),
  accountUsername: document.querySelector("#accountUsername"),
  accountPassword: document.querySelector("#accountPassword"),
  accountPasswordLabel: document.querySelector("#accountPasswordLabel"),
  accountLevel: document.querySelector("#accountLevel"),
  accountAdmin: document.querySelector("#accountAdmin"),
  accountActive: document.querySelector("#accountActive"),
  accountHint: document.querySelector("#accountHint"),
  accountSave: document.querySelector("#accountSave"),
  accountCancel: document.querySelector("#accountCancel"),
  userAvatar: document.querySelector("#userAvatar"),
  conversationNav: document.querySelector(".conversation-nav"),
  loginOverlay: document.querySelector("#loginOverlay"),
  loginForm: document.querySelector("#loginForm"),
  loginUsername: document.querySelector("#loginUsername"),
  loginPassword: document.querySelector("#loginPassword"),
  loginSubmit: document.querySelector("#loginSubmit"),
  loginSubmitLabel: document.querySelector("#loginSubmitLabel"),
  loginError: document.querySelector("#loginError"),
  loginStatus: document.querySelector("#loginStatus"),
  closeSettings: document.querySelector("#closeSettings"),
  topNewThread: document.querySelector("#topNewThread"),
  clearChat: document.querySelector("#clearChat"),
  messages: document.querySelector("#messages"),
  taskPlan: document.querySelector("#taskPlan"),
  planSummary: document.querySelector("#planSummary"),
  planList: document.querySelector("#planList"),
  planTitle: document.querySelector("#planTitle"),
  composer: document.querySelector("#composer"),
  prompt: document.querySelector("#prompt"),
  imageUrl: document.querySelector("#imageUrl"),
  imageToggle: document.querySelector("#imageToggle"),
  send: document.querySelector("#send"),
  newThread: document.querySelector("#newThread"),
  fillPrompt: document.querySelector("#fillPrompt"),
};

const state = {
  assistantNode: null,
  suppressPostImageText: false,
  assistantRenderFrame: null,
  toolCards: new Map(),
  toolActivities: new Map(),
  currentUser: null,
  authVersion: 0,
  loginBusy: false,
  loggingOut: false,
  busy: false,
  runController: null,
  threadListVersion: 0,
  adminOpen: false,
  adminSaving: false,
  adminLoading: false,
  accountUsers: [],
  editingAccountId: null,
  accountOffset: 0,
  accountTotal: 0,
  accountQuery: "",
  accountRequestVersion: 0,
  progressLabel: "正在处理请求…",
  progressTools: new Map(),
  todos: [],
  planRunStatus: "",
  viewVersion: 0,
  followOutput: true,
};

const DEFAULT_AGENT_ROLE = "general_assistant";
const EXAMPLE_PROMPT = "你是一个通用助手，帮助用户解答问题、整理资料、撰写内容和制定计划。回答清晰简洁，优先给出可用成果，并根据任务使用已启用的工具和技能。";

const responseVersions = new WeakMap();

els.agentRole.value = DEFAULT_AGENT_ROLE;
renderEmpty();
updatePromptState();
restoreSession();

els.agentRole.addEventListener("change", updatePromptState);
els.topbarAgentRole.addEventListener("change", () => {
  els.agentRole.value = els.topbarAgentRole.value;
  updatePromptState();
});
els.threadId.addEventListener("input", updatePromptState);
els.messages.addEventListener("scroll", trackMessageScroll, { passive: true });
els.messages.addEventListener("wheel", (event) => {
  if (event.deltaY < 0 && els.messages.scrollHeight > els.messages.clientHeight) {
    state.followOutput = false;
  }
}, { passive: true });
els.settingsToggle.addEventListener("click", () => setSettingsOpen(true));
els.logoutButton.addEventListener("click", logout);
els.adminButton.addEventListener("click", openAccountManagement);
els.adminClose.addEventListener("click", () => closeAccountManagement());
els.adminPanel.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeAccountManagement();
});
els.adminPanel.addEventListener("click", (event) => {
  if (event.target === els.adminPanel) closeAccountManagement();
});
els.accountForm.addEventListener("submit", saveAccount);
els.adminNew.addEventListener("click", () => editAccount());
els.accountCancel.addEventListener("click", () => editAccount());
els.adminSearchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  state.accountQuery = els.adminSearch.value.trim();
  state.accountOffset = 0;
  loadAccounts();
});
els.adminPrev.addEventListener("click", () => {
  state.accountOffset = Math.max(0, state.accountOffset - 20);
  loadAccounts();
});
els.adminNext.addEventListener("click", () => {
  state.accountOffset += 20;
  loadAccounts();
});
els.closeSettings.addEventListener("click", () => setSettingsOpen(false));
els.settingsBackdrop.addEventListener("click", () => setSettingsOpen(false));
els.topNewThread.addEventListener("click", () => els.newThread.click());
els.clearChat.addEventListener("click", () => els.newThread.click());
els.imageToggle.addEventListener("click", () => {
  els.imageUrl.classList.toggle("show");
  if (els.imageUrl.classList.contains("show")) els.imageUrl.focus();
});
els.prompt.addEventListener("input", autoResizePrompt);
els.prompt.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") els.composer.requestSubmit();
});
els.loginForm.addEventListener("submit", submitLogin);

els.newThread.addEventListener("click", () => {
  if (!state.currentUser || state.loggingOut) return;
  resetConversation();
  els.skillOptions.querySelectorAll("input").forEach((input) => {
    input.checked = false;
  });
  updatePromptState();
  els.prompt.focus();
});

els.fillPrompt.addEventListener("click", () => {
  els.agentRole.value = "";
  els.threadId.value = "";
  els.agentPrompt.value = EXAMPLE_PROMPT;
  updatePromptState();
});

els.composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.currentUser) {
    requireLogin();
    return;
  }
  if (state.busy || state.loggingOut) return;
  const text = els.prompt.value.trim();
  const imageUrl = els.imageUrl.value.trim();
  if (!text && !imageUrl) return;

  const error = validateControls();
  if (error) {
    appendMessage("error", error);
    return;
  }

  const viewVersion = ++state.viewVersion;
  state.followOutput = true;
  finishAssistantBlock();
  renderPlan([]);
  state.suppressPostImageText = false;
  appendMessage("user", [text, imageUrl && `[image] ${imageUrl}`].filter(Boolean).join("\n"));
  els.prompt.value = "";
  els.imageUrl.value = "";
  state.assistantNode = null;

  const body = buildRunBody(text, imageUrl);
  setBusy(true, "running");
  try {
    if (body.stream) {
      await runStream(body);
    } else {
      await runJson(body);
    }
  } catch (err) {
    if (viewVersion !== state.viewVersion || err.name === "AbortError") return;
    renderPlan(state.todos, "failed");
    appendMessage("error", err.message || String(err));
    setStatus("failed");
  } finally {
    if (viewVersion === state.viewVersion) {
      finishAssistantBlock();
      state.runController = null;
      setBusy(false);
    }
  }
});

function updatePromptState() {
  const hasThread = Boolean(els.threadId.value.trim());
  const usesCustomPrompt = !els.agentRole.value.trim();
  els.agentPrompt.disabled = hasThread || !usesCustomPrompt || state.busy || !state.currentUser || state.loggingOut;
  els.agentPrompt.closest("label").classList.toggle("disabled", els.agentPrompt.disabled);
  els.topbarAgentRole.disabled = hasThread || els.agentRole.disabled;
  els.skillOptions.querySelectorAll("input").forEach((input) => {
    input.disabled = hasThread || state.busy || !state.currentUser || state.loggingOut;
  });
  els.skillOptions.classList.toggle("disabled", hasThread);
  if (hasThread) {
    els.agentPrompt.placeholder = "已有 Thread ID 时沿用创建会话时的系统提示词";
  } else if (usesCustomPrompt) {
    els.agentPrompt.placeholder = "这里会作为新会话的系统提示词";
  } else {
    els.agentPrompt.placeholder = "选择 custom prompt 后可填写";
  }
  if (els.topbarAgentRole.value !== els.agentRole.value) els.topbarAgentRole.value = els.agentRole.value;
}

function validateControls() {
  if (!state.currentUser) return "请先登录";
  if (els.threadId.value.trim()) return "";
  if (els.agentRole.value.trim()) return "";
  if (!els.agentPrompt.value.trim()) return "新会话使用 custom prompt 时，需要填写 Agent Prompt";
  return "";
}

function buildRunBody(text, imageUrl) {
  const content = [];
  if (text) content.push({ type: "text", text });
  if (imageUrl) {
    content.push({
      type: "image",
      url: imageUrl,
      mime_type: "image/png",
      file_name: imageUrl.split("/").pop() || "image.png",
    });
  }

  const threadId = els.threadId.value.trim();
  const agentRole = els.agentRole.value.trim();
  const body = {
    thread_id: threadId || null,
    stream: true,
    content,
  };

  if (!threadId) {
    body.agent_role = agentRole || null;
    if (!agentRole) {
      body.agent_prompt = els.agentPrompt.value.trim();
    }
    body.active_skill_ids = selectedSkillIds();
  }
  return body;
}

async function loadSkills() {
  const authVersion = state.authVersion;
  try {
    const response = await apiFetch("/v1/skills");
    const data = await readJson(response);
    renderSkills(data.skills || []);
  } catch (err) {
    if (authVersion !== state.authVersion) return;
    els.skillOptions.textContent = `技能列表加载失败：${err.message || String(err)}`;
  }
}

function renderSkills(skills) {
  els.skillOptions.innerHTML = "";
  if (!skills.length) {
    els.skillOptions.textContent = "当前没有可用技能。";
    return;
  }
  for (const skill of skills) {
    const label = document.createElement("label");
    label.className = "skill-option";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = skill.id;
    input.checked = Boolean(skill.enabled_by_default);
    const text = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = skill.name;
    const description = document.createElement("small");
    description.textContent = skill.description;
    text.append(name, description);
    label.append(input, text);
    els.skillOptions.appendChild(label);
  }
  updatePromptState();
}

function selectedSkillIds() {
  return [...els.skillOptions.querySelectorAll("input:checked")].map((input) => input.value);
}

async function runJson(body) {
  const viewVersion = state.viewVersion;
  state.runController = new AbortController();
  const response = await apiFetch("/v1/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: state.runController.signal,
  });
  const data = await readJson(response);
  if (viewVersion !== state.viewVersion) return;
  applyRunMeta(data);
  renderPlan(data.todos || [], data.status);
  if (data.error) {
    appendMessage("error", data.error.message || "run failed");
    setStatus("failed");
    return;
  }
  appendStructuredMessage("assistant", [
    { type: "text", text: data.message || "" },
    ...(data.artifacts || []),
  ]);
  setStatus(data.status || "completed");
}

async function runStream(body) {
  const viewVersion = state.viewVersion;
  const authVersion = state.authVersion;
  state.runController = new AbortController();
  const response = await apiFetch("/v1/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: state.runController.signal,
  });
  if (!response.ok || !response.body) {
    await readJson(response);
    throw new Error("服务器没有返回对话内容");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (viewVersion !== state.viewVersion || authVersion !== state.authVersion) {
        await reader.cancel();
        return;
      }
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";
      for (const rawEvent of events) handleSseEvent(rawEvent);
    }
    if (buffer.trim()) handleSseEvent(buffer);
  } finally {
    reader.releaseLock();
  }
}

function handleSseEvent(rawEvent) {
  const lines = rawEvent.split("\n");
  const event = (lines.find((line) => line.startsWith("event:")) || "").slice(6).trim();
  const dataLine = lines.find((line) => line.startsWith("data:"));
  if (!dataLine) return;
  const data = JSON.parse(dataLine.slice(5).trim());

  if (event === "run.started") {
    state.progressTools.clear();
    state.progressLabel = "正在处理请求…";
    renderPlan([], "running");
    applyRunMeta(data);
    setStatus("running");
  } else if (event === "plan.updated") {
    if (data.thread_id && data.thread_id !== els.threadId.value) return;
    renderPlan(data.todos, "running");
  } else if (event === "message.delta") {
    if (!state.progressTools.size && data.text) {
      state.progressLabel = "正在生成回复…";
      updateProgressSummary();
    }
    if (!state.suppressPostImageText) appendAssistantDelta(data.text || "");
  } else if (event === "tool.call.started") {
    finishAssistantBlock();
    updateToolProgress(data, "running");
    if (data.tool_type === "generate_ppt") state.suppressPostImageText = false;
    appendToolCall(data, "running");
  } else if (event === "tool.call.completed") {
    finishAssistantBlock();
    updateToolProgress(data, "completed");
    appendToolCall(data, "completed");
  } else if (event === "tool.call.failed") {
    finishAssistantBlock();
    updateToolProgress(data, "failed");
    appendToolCall(data, "failed");
  } else if (event === "artifact.created") {
    finishAssistantBlock();
    appendArtifact(data.artifact);
    // Images are already rendered as artifacts. The model's follow-up is often
    // a duplicate Markdown delivery report, which should not clutter the chat.
    if (data.artifact?.type === "image") state.suppressPostImageText = true;
  } else if (event === "run.completed") {
    finishAssistantBlock();
    renderPlan(data.todos || state.todos, "completed");
    applyRunMeta(data);
    setStatus("completed");
  } else if (event === "run.failed") {
    finishAssistantBlock();
    renderPlan(data.todos || state.todos, "failed");
    appendMessage("error", data.error?.message || "run failed");
    setStatus("failed");
  }
}

function renderPlan(todos, runStatus = "") {
  const labels = { pending: "待执行", in_progress: "执行中", completed: "已完成" };
  const ended = runStatus === "completed" || runStatus === "failed";
  state.todos = Array.isArray(todos) ? todos.filter((todo) =>
    todo && typeof todo.content === "string" && Object.hasOwn(labels, todo.status)
  ) : [];
  state.planRunStatus = runStatus;
  if (ended || (!runStatus && !state.todos.length)) state.progressTools.clear();
  if (!runStatus && !state.todos.length) state.progressLabel = "正在处理请求…";
  updateProgressSummary();
  els.planList.replaceChildren();
  for (const todo of state.todos) {
    const row = document.createElement("li");
    row.className = `plan-step ${ended && todo.status !== "completed" ? "unconfirmed" : todo.status}`;
    const status = document.createElement("span");
    status.className = "plan-step-status";
    status.textContent = ended && todo.status !== "completed" ?
      runStatus === "failed" ? "未完成" : "未确认完成" : labels[todo.status];
    const content = document.createElement("span");
    content.className = "plan-step-content";
    content.textContent = todo.content;
    row.append(status, content);
    els.planList.appendChild(row);
  }
}

function updateProgressSummary() {
  const runStatus = state.planRunStatus;
  const current = state.todos.find((todo) => todo.status === "in_progress");
  els.planTitle.textContent = state.todos.length ? "执行计划" : "任务进度";
  els.taskPlan.hidden = state.todos.length === 0 && runStatus !== "running";
  const completed = state.todos.filter((todo) => todo.status === "completed").length;
  const progress = `已完成 ${completed}/${state.todos.length}`;
  const summary = runStatus === "failed" ? `运行中断 · ${progress}` :
    runStatus === "completed" ? completed === state.todos.length ? `任务已完成 · ${progress}` :
      `回答已结束 · 已确认完成 ${completed}/${state.todos.length}` : progress;
  els.planSummary.textContent = state.todos.length ? summary :
    runStatus === "running" ? state.progressLabel : "";
  if (runStatus === "running" && current) els.planSummary.textContent += ` · ${current.content}`;
}

function updateToolProgress(data, status) {
  const labels = {
    write_todos: "正在整理执行计划…",
    bocha_search: "正在搜索网络资料…",
    search_enterprise_policy: "正在检索制度资料…",
    generate_image: "正在生成配图…",
    generate_ppt: "正在生成 PPT 和预览…",
    read_file: "正在读取参考资料…",
  };
  const key = data.tool_call_id || data.tool_type || "tool";
  if (status === "running") state.progressTools.set(key, labels[data.tool_type] || "正在执行工具…");
  else state.progressTools.delete(key);
  state.progressLabel = state.progressTools.size ? [...new Set(state.progressTools.values())].join(" · ") :
    status === "failed" ? "工具执行失败，正在处理…" : "工具已完成，正在继续处理…";
  updateProgressSummary();
}

async function readJson(response) {
  const text = await response.text();
  const authVersion = responseVersions.get(response);
  if (authVersion !== undefined && authVersion !== state.authVersion) throw staleRequest();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`服务响应异常（HTTP ${response.status}），请稍后重试`);
  }
  if (!response.ok) {
    const error = new Error(data.error?.message || text || `HTTP ${response.status}`);
    error.status = response.status;
    error.code = data.error?.code;
    throw error;
  }
  return data;
}

async function checkHealth() {
  const authVersion = state.authVersion;
  try {
    const response = await fetch("/health");
    if (authVersion === state.authVersion && state.currentUser && !state.busy) setStatus(response.ok ? "ready" : "unhealthy");
  } catch {
    if (authVersion === state.authVersion && state.currentUser && !state.busy) setStatus("offline");
  }
}

function applyRunMeta(data) {
  if (data.run_id) els.runId.textContent = data.run_id;
  if (data.thread_id) {
    els.threadId.value = data.thread_id;
    updatePromptState();
  }
  if (data.status) setStatus(data.status);
  if (data.thread_id) loadThreads();
}

function appendAssistantDelta(text) {
  if (!text) return;
  if (!state.assistantNode) {
    state.assistantNode = appendMessage("assistant", "");
  }
  state.assistantNode.dataset.markdown = `${state.assistantNode.dataset.markdown || ""}${text}`;
  if (state.assistantRenderFrame === null) {
    state.assistantRenderFrame = requestAnimationFrame(flushAssistantRender);
  }
}

function flushAssistantRender() {
  if (state.assistantRenderFrame === null) return;
  cancelAnimationFrame(state.assistantRenderFrame);
  state.assistantRenderFrame = null;
  if (!state.assistantNode) return;
  const content = state.assistantNode.querySelector(".message-content");
  renderMarkdown(content, state.assistantNode.dataset.markdown);
  scrollMessages();
}

function finishAssistantBlock() {
  flushAssistantRender();
  // A tool event separates the model's execution narration from the next
  // assistant response segment, so later deltas must not append to it.
  state.assistantNode = null;
}

function appendMessage(role, text) {
  clearEmpty();
  const item = document.createElement("article");
  item.className = `message ${role}`;
  const title = document.createElement("div");
  title.className = "message-role";
  title.textContent = role;
  const content = document.createElement("div");
  content.className = "message-content";
  item.dataset.markdown = text;
  renderMarkdown(content, text);
  item.append(title, content);
  els.messages.appendChild(item);
  scrollMessages();
  return item;
}

function appendArtifact(artifact) {
  const rendered = createArtifact(artifact);
  if (!rendered) return;
  const item = appendMessage("assistant", "");
  const content = item.querySelector(".message-content");
  content.replaceChildren(rendered);
  scrollMessages();
}

function appendStructuredMessage(role, blocks) {
  if (!Array.isArray(blocks) || !blocks.length) return null;
  const hasImageArtifact = role === "assistant" && blocks.some((block) => block?.type === "image")
    && !blocks.some((block) => block?.type === "file");
  const text = blocks
    .filter((block) => !hasImageArtifact && block?.type === "text" && typeof block.text === "string")
    .map((block) => block.text)
    .join("\n");
  const item = appendMessage(role, text);
  const content = item.querySelector(".message-content");
  for (const block of blocks) {
    const artifact = createArtifact(block);
    if (artifact) content.appendChild(artifact);
  }
  return item;
}

function createArtifact(block) {
  if (block?.type === "image") return createImageArtifact(block);
  if (block?.type === "file") return createFileArtifact(block);
  return null;
}

function createFileArtifact(block) {
  const metadata = block.metadata || block;
  if (typeof metadata.url !== "string" || !/^https?:\/\//i.test(metadata.url)) return null;
  const card = document.createElement("div");
  card.className = "file-artifact";
  const badge = document.createElement("span");
  badge.className = "file-artifact-badge";
  badge.textContent = "PPTX";
  const details = document.createElement("div");
  const name = document.createElement("strong");
  name.textContent = metadata.file_name || "presentation.pptx";
  const description = document.createElement("small");
  const parts = ["可编辑 PowerPoint"];
  if (Number.isInteger(metadata.slide_count) && metadata.slide_count > 0) parts.push(`${metadata.slide_count} 页`);
  if (Number.isFinite(metadata.size_bytes) && metadata.size_bytes > 0) parts.push(`${Math.ceil(metadata.size_bytes / 1024)} KB`);
  if (metadata.theme_name) parts.push(metadata.theme_name);
  description.textContent = parts.join(" · ");
  details.append(name, description);
  const download = document.createElement("a");
  download.href = metadata.url;
  download.target = "_blank";
  download.rel = "noopener noreferrer";
  download.download = metadata.file_name || "presentation.pptx";
  download.textContent = "下载 PPT";
  card.append(badge, details, download);
  if (isPdfPreview(metadata)) {
    const preview = document.createElement("details");
    preview.className = "file-preview";
    const summary = document.createElement("summary");
    summary.textContent = "预览 PPT";
    const frame = document.createElement("iframe");
    frame.title = `${metadata.file_name || "PPT"} 预览`;
    frame.loading = "lazy";
    frame.referrerPolicy = "no-referrer";
    preview.addEventListener("toggle", () => {
      if (preview.open && !frame.src) frame.src = `${pdfPreviewUrl(metadata)}#view=FitH`;
    });
    const hint = document.createElement("p");
    hint.textContent = "预览与生成文件一致，可在窗口中翻页和缩放。";
    const open = document.createElement("a");
    open.href = pdfPreviewUrl(metadata);
    open.target = "_blank";
    open.rel = "noopener noreferrer";
    open.textContent = "在新标签页打开预览";
    hint.appendChild(open);
    preview.append(summary, frame, hint);
    card.appendChild(preview);
  } else if (metadata.preview_status === "unavailable") {
    const hint = document.createElement("small");
    hint.className = "file-preview-unavailable";
    hint.textContent = "预览暂不可用，可下载 PPT 查看。";
    card.appendChild(hint);
  }
  return card;
}

function isPdfPreview(metadata) {
  if (metadata.preview_status !== "ready" || metadata.preview_mime_type !== "application/pdf") return false;
  try {
    const preview = new URL(metadata.preview_url);
    const source = new URL(metadata.url);
    return ["https:", "http:"].includes(preview.protocol) && preview.origin === source.origin
      && !preview.username && !preview.password && preview.pathname.toLowerCase().endsWith(".pdf");
  } catch {
    return false;
  }
}

function pdfPreviewUrl(metadata) {
  return `/v1/artifacts/ppt-preview?url=${encodeURIComponent(metadata.preview_url)}`;
}

function createImageArtifact(block) {
  const metadata = block.metadata || block;
  if (!metadata.url) return null;
  const figure = document.createElement("figure");
  figure.className = "image-artifact";
  const link = document.createElement("a");
  link.href = metadata.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  const image = document.createElement("img");
  image.src = metadata.preview_url || metadata.url;
  image.alt = metadata.alt || metadata.file_name || "生成图片";
  image.loading = "lazy";
  link.appendChild(image);
  figure.appendChild(link);
  if (metadata.alt) {
    const caption = document.createElement("figcaption");
    caption.textContent = metadata.alt;
    figure.appendChild(caption);
  }
  return figure;
}

function renderMarkdown(container, source) {
  try {
    renderMarkdownUnsafe(container, source);
  } catch (error) {
    console.error("Markdown rendering failed; falling back to plain text.", error);
    container.textContent = String(source || "");
  }
}

function renderMarkdownUnsafe(container, source) {
  const lines = String(source || "").replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) { index += 1; continue; }
    if (/^```/.test(line)) {
      const language = line.slice(3).trim();
      const code = [];
      index += 1;
      while (index < lines.length && !/^```/.test(lines[index])) code.push(lines[index++]);
      if (index < lines.length) index += 1;
      blocks.push(`<pre><code${language ? ` class="language-${escapeHtml(language)}"` : ""}>${escapeHtml(code.join("\n"))}</code></pre>`);
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      blocks.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      index += 1;
      continue;
    }
    if (/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line)) { blocks.push("<hr>"); index += 1; continue; }
    if (isTableDivider(lines[index + 1]) && line.includes("|")) {
      const headers = splitTableRow(line);
      index += 2;
      const rows = [];
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) rows.push(splitTableRow(lines[index++]));
      const headerHtml = headers.map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`).join("");
      const bodyHtml = rows.map((row) => `<tr>${headers.map((_, cellIndex) => `<td>${renderInlineMarkdown(row[cellIndex] || "")}</td>`).join("")}</tr>`).join("");
      blocks.push(`<div class="markdown-table-wrap"><table><thead><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`);
      continue;
    }
    const list = line.match(/^\s*([-*+]|\d+\.)\s+(.+)$/);
    if (list) {
      const ordered = /\d+\./.test(list[1]);
      const items = [];
      while (index < lines.length) {
        const item = lines[index].match(/^\s*([-*+]|\d+\.)\s+(.+)$/);
        if (!item || /\d+\./.test(item[1]) !== ordered) break;
        items.push(`<li>${renderInlineMarkdown(item[2])}</li>`);
        index += 1;
      }
      blocks.push(`<${ordered ? "ol" : "ul"}>${items.join("")}</${ordered ? "ol" : "ul"}>`);
      continue;
    }
    if (/^>\s?/.test(line)) {
      const quote = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) quote.push(lines[index++].replace(/^>\s?/, ""));
      blocks.push(`<blockquote>${renderInlineMarkdown(quote.join("\n")).replace(/\n/g, "<br>")}</blockquote>`);
      continue;
    }
    const paragraph = [];
    while (index < lines.length && lines[index].trim() && !/^```|^(#{1,6})\s+|^\s*([-*+]|\d+\.)\s+|^>\s?/.test(lines[index])) paragraph.push(lines[index++]);
    if (!paragraph.length) paragraph.push(lines[index++]);
    blocks.push(`<p>${renderInlineMarkdown(paragraph.join("\n")).replace(/\n/g, "<br>")}</p>`);
  }
  container.innerHTML = blocks.join("");
}

function splitTableRow(line) {
  return line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
}

function isTableDivider(line = "") {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function renderInlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/_([^_]+)_/g, "<em>$1</em>")
    .replace(/\[([^\]]+)]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
}

function appendToolCall(data, status) {
  if (data.tool_type === "write_todos") return;
  const toolType = data.tool_type || "unknown_tool";
  if (!isSearchTool(toolType)) {
    appendToolActivity(data, status);
    return;
  }

  const callId = data.tool_call_id || `${toolType}-${Date.now()}`;
  let item = state.toolCards.get(callId);
  if (!item) {
    item = createToolCard(toolType);
    state.toolCards.set(callId, item);
  }
  updateToolCard(item, data, status);
  scrollMessages();
}

function appendToolActivity(data, status) {
  const toolType = data.tool_type || "unknown_tool";
  const callId = data.tool_call_id || `${toolType}-${Date.now()}`;
  let item = state.toolActivities.get(callId);
  if (!item) {
    clearEmpty();
    item = document.createElement("div");
    item.className = "tool-activity";
    els.messages.appendChild(item);
    state.toolActivities.set(callId, item);
  }
  const labels = {
    generate_image: ["正在生图", "图片已生成"],
    generate_ppt: ["正在生成 PPT", "PPT 已生成"],
    read_file: ["正在读取参考资料", "已读取参考资料"],
    unknown_tool: ["正在准备工具", "工具已完成"],
  };
  const [runningLabel, completedLabel] = labels[toolType] || ["正在使用辅助工具", "辅助工具已完成"];
  item.classList.toggle("failed", status === "failed");
  item.textContent = status === "failed"
    ? `· ${data.error?.message || "辅助工具调用失败"}`
    : `· ${status === "running" ? runningLabel : completedLabel}`;
  scrollMessages();
}

function isSearchTool(toolType) {
  return toolType === "bocha_search" || toolType === "search_enterprise_policy";
}

function createToolCard(toolType) {
  clearEmpty();
  const item = document.createElement("article");
  item.className = "message tool tool-search";
  const title = document.createElement("div");
  title.className = "message-role";
  const details = document.createElement("details");
  details.className = "tool-details";
  const summary = document.createElement("summary");
  const content = document.createElement("div");
  content.className = "tool-result";
  details.append(summary, content);
  item.append(title, details);
  item.dataset.toolType = toolType;
  els.messages.appendChild(item);
  return item;
}

function updateToolCard(item, data, status) {
  const toolType = item.dataset.toolType;
  const toolName = toolType === "bocha_search" ? "联网搜索" : "企业制度知识库";
  const labels = { running: "搜索中", completed: "搜索完成", failed: "搜索失败" };
  item.classList.toggle("error", status === "failed");
  item.querySelector(".message-role").textContent = `${toolName} · ${labels[status]}`;

  const summary = item.querySelector("summary");
  const content = item.querySelector(".tool-result");
  content.replaceChildren();
  if (status === "running") {
    summary.textContent = "查看搜索内容";
    renderArguments(content, data.arguments || {});
  } else if (status === "completed") {
    summary.textContent = "查看搜索结果";
    renderSearchResults(content, data.result, toolType);
  } else {
    summary.textContent = "查看失败详情";
    const message = document.createElement("p");
    message.textContent = data.error?.message || "工具调用失败";
    content.appendChild(message);
  }
}

function renderArguments(container, arguments_) {
  const query = arguments_.query || "未提供搜索词";
  const queryLine = document.createElement("p");
  queryLine.className = "tool-query";
  queryLine.textContent = `搜索：${query}`;
  container.appendChild(queryLine);

  const options = Object.entries(arguments_).filter(([key]) => key !== "query");
  if (!options.length) return;
  const meta = document.createElement("p");
  meta.className = "tool-meta";
  meta.textContent = options.map(([key, value]) => `${key}: ${formatValue(value)}`).join(" · ");
  container.appendChild(meta);
}

function renderSearchResults(container, result, toolType) {
  const results = Array.isArray(result?.results) ? result.results : [];
  const query = result?.query;
  if (query) renderArguments(container, { query });
  if (!results.length) {
    const empty = document.createElement("p");
    empty.textContent = "没有返回可展示的检索结果。";
    container.appendChild(empty);
    return;
  }
  const list = document.createElement("ol");
  list.className = "search-results";
  for (const resultItem of results) {
    const row = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = resultItem.title || "未命名结果";
    row.appendChild(title);
    if (toolType === "bocha_search" && resultItem.url) {
      const link = document.createElement("a");
      link.href = resultItem.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = resultItem.site_name || resultItem.url;
      row.appendChild(link);
    } else if (resultItem.source_article || resultItem.source_pages || resultItem.file_id) {
      const source = document.createElement("span");
      source.className = "tool-meta";
      source.textContent = [resultItem.source_article, formatPages(resultItem.source_pages), resultItem.file_id].filter(Boolean).join(" · ");
      row.appendChild(source);
    }
    const excerpt = resultItem.snippet || resultItem.content;
    if (excerpt) {
      const text = document.createElement("p");
      text.textContent = excerpt;
      row.appendChild(text);
    }
    list.appendChild(row);
  }
  container.appendChild(list);
}

function formatPages(pages) {
  return Array.isArray(pages) && pages.length ? `页码：${pages.join(", ")}` : "";
}

function formatValue(value) {
  return Array.isArray(value) ? value.join(", ") : String(value);
}

function setSettingsOpen(open) {
  els.settingsPanel.classList.toggle("open", open);
  els.settingsBackdrop.classList.toggle("show", open);
  els.settingsToggle.setAttribute("aria-expanded", String(open));
}

function renderEmpty() {
  els.messages.innerHTML = '<div class="empty">你可以让我解答问题、整理资料、撰写内容或制定计划，也可以启用相应技能来完成具体任务。</div>';
}

function staleRequest() {
  const error = new Error("请求已取消");
  error.name = "AbortError";
  return error;
}

async function apiFetch(path, options = {}) {
  const authVersion = state.authVersion;
  const response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options });
  if (authVersion !== state.authVersion) throw staleRequest();
  if (response.status === 401) {
    requireLogin(state.currentUser ? "登录已过期或账号已停用，请重新登录。" : "");
    throw new Error("请重新登录");
  }
  responseVersions.set(response, authVersion);
  return response;
}

function setWorkspaceLocked(locked) {
  els.workspace.inert = locked;
  els.appSidebar.inert = locked;
  els.settingsPanel.inert = locked;
}

function setLoginBusy(busy, checking = false) {
  state.loginBusy = busy;
  els.loginUsername.disabled = busy;
  els.loginPassword.disabled = busy;
  els.loginSubmit.disabled = busy;
  els.loginForm.setAttribute("aria-busy", String(busy));
  els.loginSubmitLabel.textContent = checking ? "正在检查…" : busy ? "正在登录…" : "登录工作区";
  els.loginStatus.textContent = checking ? "正在检查登录状态…" : busy ? "正在验证账号…" : "";
}

function showLoginError(message = "") {
  els.loginError.textContent = message;
  els.loginError.hidden = !message;
}

function resetConversation() {
  state.viewVersion += 1;
  state.runController?.abort();
  state.runController = null;
  if (state.assistantRenderFrame !== null) cancelAnimationFrame(state.assistantRenderFrame);
  state.assistantRenderFrame = null;
  state.assistantNode = null;
  state.followOutput = true;
  state.suppressPostImageText = false;
  els.agentRole.value = DEFAULT_AGENT_ROLE;
  state.toolCards.clear();
  state.toolActivities.clear();
  renderPlan([]);
  els.threadId.value = "";
  els.runId.textContent = "-";
  els.prompt.value = "";
  els.imageUrl.value = "";
  renderEmpty();
  setBusy(false, "idle");
}

function requireLogin(message = "") {
  state.authVersion += 1;
  state.currentUser = null;
  state.loggingOut = false;
  closeAccountManagement(true);
  resetConversation();
  els.userId.value = "";
  els.currentUserName.textContent = "未登录";
  els.currentUserLevel.textContent = "请先登录";
  els.userAvatar.textContent = "?";
  els.logoutButton.hidden = true;
  els.logoutButton.disabled = false;
  els.adminButton.hidden = true;
  els.agentPrompt.value = "";
  els.agentRole.value = DEFAULT_AGENT_ROLE;
  els.skillOptions.replaceChildren();
  els.skillOptions.textContent = "登录后加载技能列表";
  renderThreads([]);
  setSettingsOpen(false);
  setWorkspaceLocked(true);
  els.loginPassword.value = "";
  els.loginOverlay.classList.remove("hidden");
  els.loginOverlay.setAttribute("aria-hidden", "false");
  setLoginBusy(false);
  showLoginError(message);
  setStatus("signed_out");
  updatePromptState();
  els.loginUsername.focus();
}

async function enterWorkspace(user) {
  state.authVersion += 1;
  state.currentUser = user;
  state.loggingOut = false;
  resetConversation();
  renderCurrentAccount();
  els.logoutButton.hidden = false;
  els.logoutButton.disabled = false;
  els.loginPassword.value = "";
  setLoginBusy(false);
  showLoginError();
  // Move focus before hiding the modal from assistive technology.
  setWorkspaceLocked(false);
  els.loginOverlay.classList.add("hidden");
  els.prompt.focus();
  els.loginOverlay.setAttribute("aria-hidden", "true");
  setStatus("ready");
  checkHealth();
  await Promise.all([loadSkills(), loadThreads()]);
}

async function restoreSession() {
  const authVersion = state.authVersion;
  setWorkspaceLocked(true);
  setBusy(false);
  setLoginBusy(true, true);
  try {
    const response = await apiFetch("/v1/auth/me");
    const user = await readJson(response);
    if (authVersion === state.authVersion) await enterWorkspace(user);
  } catch (err) {
    if (authVersion === state.authVersion) requireLogin("暂时无法检查登录状态，请重新登录或稍后重试。");
  }
}

async function submitLogin(event) {
  event.preventDefault();
  if (state.loginBusy) return;
  const username = els.loginUsername.value.trim();
  const password = els.loginPassword.value;
  if (!username || !password) {
    showLoginError("请输入账号和密码。");
    return;
  }
  const authVersion = state.authVersion;
  setLoginBusy(true);
  showLoginError();
  try {
    const response = await fetch("/v1/auth/login", {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    responseVersions.set(response, authVersion);
    const data = await readJson(response);
    if (authVersion !== state.authVersion) return;
    // The browser uses the HttpOnly cookie; do not persist the returned access_token.
    await enterWorkspace(data.user);
  } catch (err) {
    if (authVersion !== state.authVersion) return;
    els.loginPassword.value = "";
    showLoginError(err.message || "登录失败，请稍后重试。");
  } finally {
    if (authVersion === state.authVersion) {
      setLoginBusy(false);
      els.loginPassword.focus();
    }
  }
}

async function logout() {
  if (!state.currentUser || state.loggingOut) return;
  const authVersion = state.authVersion;
  state.loggingOut = true;
  els.logoutButton.disabled = true;
  resetConversation();
  try {
    const response = await apiFetch("/v1/auth/logout", { method: "POST" });
    if (!response.ok) await readJson(response);
    requireLogin();
  } catch (err) {
    if (authVersion === state.authVersion) appendMessage("error", `退出失败：${err.message || "请稍后重试"}`);
  } finally {
    if (authVersion === state.authVersion) {
      state.loggingOut = false;
      els.logoutButton.disabled = false;
      setBusy(false);
    }
  }
}

async function loadThreads() {
  if (!state.currentUser) return;
  const authVersion = state.authVersion;
  const listVersion = ++state.threadListVersion;
  try {
    const response = await apiFetch("/v1/threads/mine");
    const data = await readJson(response);
    if (listVersion !== state.threadListVersion) return;
    renderThreads(data.threads || []);
  } catch (err) {
    if (authVersion !== state.authVersion || listVersion !== state.threadListVersion) return;
    renderThreads([], err.message || String(err));
  }
}

function renderThreads(threads, error = "") {
  const heading = document.createElement("div");
  heading.className = "nav-heading";
  heading.innerHTML = "<span>最近对话</span><button type=\"button\" aria-label=\"刷新对话\">↻</button>";
  heading.querySelector("button").addEventListener("click", loadThreads);
  els.conversationNav.replaceChildren(heading);
  if (error) {
    const notice = document.createElement("div");
    notice.className = "conversation";
    notice.textContent = "对话历史加载失败";
    els.conversationNav.appendChild(notice);
    return;
  }
  if (!threads.length) {
    const notice = document.createElement("div");
    notice.className = "conversation";
    notice.textContent = "暂无对话历史";
    els.conversationNav.appendChild(notice);
    return;
  }
  for (const thread of threads) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "conversation";
    item.dataset.threadId = thread.thread_id;
    const dot = document.createElement("span");
    dot.className = "conversation-dot teal";
    const title = document.createElement("span");
    title.textContent = thread.title || "新的 Agent 对话";
    item.append(dot, title);
    item.addEventListener("click", () => openThread(thread));
    els.conversationNav.appendChild(item);
  }
}

async function openThread(thread) {
  if (!state.currentUser || state.loggingOut) return;
  state.runController?.abort();
  state.runController = null;
  setBusy(false);
  state.suppressPostImageText = false;
  const viewVersion = ++state.viewVersion;
  state.followOutput = true;
  finishAssistantBlock();
  renderPlan([]);
  els.threadId.value = thread.thread_id;
  els.agentRole.value = thread.agent_role || "";
  updatePromptState();
  state.assistantNode = null;
  state.toolCards.clear();
  state.toolActivities.clear();
  els.messages.replaceChildren();
  els.conversationNav.querySelectorAll(".conversation").forEach((item) => {
    item.classList.toggle("active", item.dataset.threadId === thread.thread_id);
  });
  try {
    const response = await apiFetch(`/v1/threads/${encodeURIComponent(thread.thread_id)}/messages?page=1&page_size=100`);
    const data = await readJson(response);
    if (viewVersion !== state.viewVersion) return;
    renderPlan(data.todos || [], data.run_status);
    const conversations = [...(data.messages || [])].reverse();
    for (const conversation of conversations) {
      if (conversation.user?.content?.length) appendStructuredMessage("user", conversation.user.content);
      if (conversation.assistant?.content?.length) appendStructuredMessage("assistant", conversation.assistant.content);
    }
    if (!conversations.length) renderEmpty();
  } catch (err) {
    if (viewVersion !== state.viewVersion) return;
    appendMessage("error", `历史消息加载失败：${err.message || String(err)}`);
  }
}

function clearEmpty() {
  const empty = els.messages.querySelector(".empty");
  if (empty) empty.remove();
}

function trackMessageScroll() {
  const distance = els.messages.scrollHeight - els.messages.clientHeight - els.messages.scrollTop;
  state.followOutput = distance <= 4;
}

function scrollMessages() {
  if (state.followOutput) {
    els.messages.scrollTop = Math.max(0, els.messages.scrollHeight - els.messages.clientHeight);
  }
}

function setStatus(status) {
  const labels = {
    idle: "等待提问",
    ready: "准备就绪",
    running: "正在查询",
    completed: "已完成",
    failed: "查询失败",
    unhealthy: "服务异常",
    offline: "服务未连接",
    signed_out: "请先登录",
  };
  els.status.textContent = labels[status] || status;
  if (els.statusDot) els.statusDot.style.background = status === "failed" || status === "offline" ? "#e16d68" : status === "running" ? "#dfaa44" : "#55bd88";
  const configStatus = document.querySelector("#configStatus");
  if (configStatus) configStatus.textContent = status;
}

function setBusy(busy, status) {
  state.busy = busy;
  const disabled = busy || !state.currentUser || state.loggingOut;
  els.send.disabled = disabled;
  els.prompt.disabled = !state.currentUser || state.loggingOut;
  els.agentRole.disabled = disabled;
  els.topbarAgentRole.disabled = disabled || Boolean(els.threadId.value.trim());
  els.threadId.disabled = disabled;
  els.newThread.disabled = !state.currentUser || state.loggingOut;
  els.topNewThread.disabled = !state.currentUser || state.loggingOut;
  els.clearChat.disabled = !state.currentUser || state.loggingOut;
  els.skillOptions.querySelectorAll("input").forEach((input) => {
    input.disabled = disabled || Boolean(els.threadId.value.trim());
  });
  if (status) setStatus(status);
  updatePromptState();
}

function autoResizePrompt() {
  els.prompt.style.height = "auto";
  els.prompt.style.height = `${Math.min(els.prompt.scrollHeight, 160)}px`;
}

function renderCurrentAccount() {
  const user = state.currentUser;
  if (!user) return;
  els.userId.value = user.user_id;
  els.currentUserName.textContent = user.username;
  const levels = { 1: "初级用户", 2: "中级用户", 3: "高级用户" };
  els.currentUserLevel.textContent = `${user.username} · ${user.is_admin ? "管理员" : levels[user.access_level] || "用户"}`;
  els.userAvatar.textContent = user.username.slice(0, 2).toUpperCase();
  els.adminButton.hidden = !user.is_admin;
}

function showAccountError(message = "") {
  els.adminError.textContent = message;
  els.adminError.hidden = !message;
}

async function openAccountManagement() {
  if (!state.currentUser?.is_admin || state.loggingOut) return;
  state.adminOpen = true;
  state.accountOffset = 0;
  state.accountQuery = "";
  els.adminSearch.value = "";
  els.adminStatus.textContent = "";
  showAccountError();
  setSettingsOpen(false);
  setWorkspaceLocked(true);
  els.adminPanel.hidden = false;
  editAccount();
  await loadAccounts();
}

function closeAccountManagement(force = false) {
  if (state.adminSaving && !force) return;
  const wasOpen = state.adminOpen;
  state.adminOpen = false;
  state.adminSaving = false;
  state.adminLoading = false;
  state.accountRequestVersion += 1;
  state.accountUsers = [];
  state.editingAccountId = null;
  state.accountTotal = 0;
  els.adminPanel.hidden = true;
  els.adminUsers.replaceChildren();
  els.accountUsername.value = "";
  els.accountPassword.value = "";
  els.adminSearch.value = "";
  els.adminCount.textContent = "";
  els.adminStatus.textContent = "";
  showAccountError();
  if (wasOpen) {
    setWorkspaceLocked(!state.currentUser);
    if (state.currentUser && !force) els.adminButton.focus();
  }
}

function updateAccountControls() {
  const saving = state.adminSaving;
  const self = state.editingAccountId === state.currentUser?.user_id;
  [els.accountUsername, els.accountPassword, els.accountLevel, els.accountCancel,
    els.adminNew, els.adminSearch, els.adminSearchButton, els.adminClose].forEach((element) => {
    element.disabled = saving;
  });
  els.accountAdmin.disabled = saving || self;
  els.accountActive.disabled = saving || self;
  els.accountSave.disabled = saving || state.adminLoading;
  els.accountSave.textContent = saving ? "正在保存…" : state.editingAccountId ? "保存修改" : "创建账号";
  els.adminPrev.disabled = saving || state.adminLoading || state.accountOffset === 0;
  els.adminNext.disabled = saving || state.adminLoading || state.accountOffset + 20 >= state.accountTotal;
  els.accountForm.setAttribute("aria-busy", String(saving));
  els.adminUsers.querySelectorAll("button").forEach((button) => { button.disabled = saving; });
}

function editAccount(account = null) {
  if (state.adminSaving) return;
  state.editingAccountId = account?.user_id || null;
  els.accountFormTitle.textContent = account ? "编辑账号" : "新增账号";
  els.accountUsername.value = account?.username || "";
  els.accountPassword.value = "";
  els.accountPassword.required = !account;
  els.accountPasswordLabel.textContent = account ? "重置密码（选填）" : "初始密码";
  els.accountPassword.placeholder = account ? "留空则保留原密码" : "请输入初始密码";
  els.accountLevel.value = String(account?.access_level || 1);
  els.accountAdmin.checked = Boolean(account?.is_admin);
  els.accountActive.checked = account ? account.is_active : true;
  const self = account?.user_id === state.currentUser?.user_id;
  els.accountHint.textContent = self ? "不能停用当前账号或取消自己的管理员身份。重置自己的密码后需要重新登录。" :
    account ? "用户名修改后保留历史会话。重置密码或停用账号会注销该账号的登录状态。" : "新账号默认使用初级权限。";
  els.accountCancel.textContent = account ? "取消编辑" : "清空";
  showAccountError();
  updateAccountControls();
  if (state.adminOpen) els.accountUsername.focus();
}

function handleAccountError(error) {
  if (error.status === 403 && error.code === "ACCESS_DENIED") {
    if (state.currentUser) state.currentUser.is_admin = false;
    renderCurrentAccount();
    closeAccountManagement(true);
    appendMessage("error", "管理员权限已取消，无法继续管理账号。");
    return;
  }
  showAccountError(error.message || "账户管理暂时不可用，请稍后重试。");
}

async function loadAccounts() {
  if (!state.adminOpen || state.adminSaving || !state.currentUser?.is_admin) return;
  const authVersion = state.authVersion;
  const requestVersion = ++state.accountRequestVersion;
  state.adminLoading = true;
  showAccountError();
  els.adminCount.textContent = "正在加载账号…";
  updateAccountControls();
  try {
    const query = new URLSearchParams({ q: state.accountQuery, limit: "20", offset: String(state.accountOffset) });
    const response = await apiFetch(`/v1/admin/users?${query}`);
    const data = await readJson(response);
    if (requestVersion !== state.accountRequestVersion || !state.adminOpen) return;
    state.accountUsers = data.users || [];
    state.accountTotal = data.total || 0;
    renderAccounts();
  } catch (error) {
    if (authVersion !== state.authVersion || requestVersion !== state.accountRequestVersion || !state.adminOpen) return;
    state.accountUsers = [];
    state.accountTotal = 0;
    renderAccounts();
    handleAccountError(error);
  } finally {
    if (authVersion === state.authVersion && requestVersion === state.accountRequestVersion && state.adminOpen) {
      state.adminLoading = false;
      updateAccountControls();
    }
  }
}

function renderAccounts() {
  els.adminUsers.replaceChildren();
  const levels = { 1: "初级", 2: "中级", 3: "高级" };
  for (const account of state.accountUsers) {
    const row = document.createElement("tr");
    const values = [account.username, levels[account.access_level], account.is_admin ? "管理员" : "普通用户",
      account.is_active ? "启用" : "停用", account.last_login_at ? new Date(account.last_login_at).toLocaleString("zh-CN", { hour12: false }) : "尚未登录"];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    }
    const action = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "编辑";
    button.addEventListener("click", () => editAccount(account));
    action.appendChild(button);
    row.appendChild(action);
    els.adminUsers.appendChild(row);
  }
  if (!state.accountUsers.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.textContent = "没有匹配的账号";
    row.appendChild(cell);
    els.adminUsers.appendChild(row);
  }
  els.adminCount.textContent = `共 ${state.accountTotal} 个账号 · 第 ${Math.floor(state.accountOffset / 20) + 1}/${Math.max(1, Math.ceil(state.accountTotal / 20))} 页`;
}

async function saveAccount(event) {
  event.preventDefault();
  if (!state.adminOpen || state.adminSaving || state.adminLoading || !state.currentUser?.is_admin) return;
  const authVersion = state.authVersion;
  const userId = state.editingAccountId;
  const username = els.accountUsername.value.trim();
  const password = els.accountPassword.value;
  if (!username || (!userId && !password)) {
    showAccountError("请输入账号和初始密码。");
    return;
  }
  const values = { username, access_level: Number(els.accountLevel.value),
    is_admin: els.accountAdmin.checked, is_active: els.accountActive.checked };
  if (password) values.password = password;
  state.adminSaving = true;
  els.adminStatus.textContent = "";
  showAccountError();
  updateAccountControls();
  try {
    const response = await apiFetch(userId ? `/v1/admin/users/${encodeURIComponent(userId)}` : "/v1/admin/users", {
      method: userId ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values),
    });
    const account = await readJson(response);
    if (authVersion !== state.authVersion || !state.adminOpen) return;
    els.accountPassword.value = "";
    if (account.user_id === state.currentUser.user_id) {
      if (password) {
        requireLogin("密码已更新，请使用新密码重新登录。");
        return;
      }
      state.currentUser = { user_id: account.user_id, username: account.username,
        access_level: account.access_level, is_admin: account.is_admin };
      renderCurrentAccount();
    }
    state.adminSaving = false;
    editAccount();
    els.adminStatus.textContent = userId ? "账号已更新。" : "账号已创建。";
    state.accountOffset = 0;
    state.accountQuery = "";
    els.adminSearch.value = "";
    await loadAccounts();
  } catch (error) {
    if (authVersion === state.authVersion && state.adminOpen) handleAccountError(error);
  } finally {
    if (authVersion === state.authVersion && state.adminOpen) {
      state.adminSaving = false;
      updateAccountControls();
    }
  }
}
