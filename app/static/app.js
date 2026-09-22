const els = {
  userId: document.querySelector("#userId"),
  threadId: document.querySelector("#threadId"),
  agentRole: document.querySelector("#agentRole"),
  agentPrompt: document.querySelector("#agentPrompt"),
  skillOptions: document.querySelector("#skillOptions"),
  runId: document.querySelector("#runId"),
  status: document.querySelector("#status"),
  settingsPanel: document.querySelector("#settingsPanel"),
  settingsToggle: document.querySelector("#settingsToggle"),
  closeSettings: document.querySelector("#closeSettings"),
  topNewThread: document.querySelector("#topNewThread"),
  messages: document.querySelector("#messages"),
  composer: document.querySelector("#composer"),
  prompt: document.querySelector("#prompt"),
  imageUrl: document.querySelector("#imageUrl"),
  send: document.querySelector("#send"),
  newThread: document.querySelector("#newThread"),
  fillPrompt: document.querySelector("#fillPrompt"),
};

const state = {
  assistantNode: null,
  toolCards: new Map(),
  toolActivities: new Map(),
};

const EXAMPLE_PROMPT = "你是一个专业影视创作助手。回答要简洁，优先给出可执行方案；涉及分镜时输出镜号、景别、镜头运动和画面描述。";

renderEmpty();
updatePromptState();
checkHealth();
loadSkills();

els.agentRole.addEventListener("change", updatePromptState);
els.threadId.addEventListener("input", updatePromptState);
els.settingsToggle.addEventListener("click", () => setSettingsOpen(true));
els.closeSettings.addEventListener("click", () => setSettingsOpen(false));
els.topNewThread.addEventListener("click", () => els.newThread.click());

els.newThread.addEventListener("click", () => {
  els.threadId.value = "";
  els.runId.textContent = "-";
  state.assistantNode = null;
  state.toolCards.clear();
  state.toolActivities.clear();
  setStatus("idle");
  renderEmpty();
  els.skillOptions.querySelectorAll("input").forEach((input) => {
    input.checked = false;
  });
  updatePromptState();
});

els.fillPrompt.addEventListener("click", () => {
  els.agentRole.value = "";
  els.threadId.value = "";
  els.agentPrompt.value = EXAMPLE_PROMPT;
  updatePromptState();
});

els.composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = els.prompt.value.trim();
  const imageUrl = els.imageUrl.value.trim();
  if (!text && !imageUrl) return;

  const error = validateControls();
  if (error) {
    appendMessage("error", error);
    return;
  }

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
    appendMessage("error", err.message || String(err));
    setStatus("failed");
  } finally {
    setBusy(false);
  }
});

function updatePromptState() {
  const hasThread = Boolean(els.threadId.value.trim());
  const usesCustomPrompt = !els.agentRole.value.trim();
  els.agentPrompt.disabled = hasThread || !usesCustomPrompt;
  els.agentPrompt.closest("label").classList.toggle("disabled", els.agentPrompt.disabled);
  els.skillOptions.querySelectorAll("input").forEach((input) => {
    input.disabled = hasThread;
  });
  els.skillOptions.classList.toggle("disabled", hasThread);
  if (hasThread) {
    els.agentPrompt.placeholder = "已有 Thread ID 时沿用创建会话时的系统提示词";
  } else if (usesCustomPrompt) {
    els.agentPrompt.placeholder = "这里会作为新会话的系统提示词";
  } else {
    els.agentPrompt.placeholder = "选择 custom prompt 后可填写";
  }
}

function validateControls() {
  if (!els.userId.value.trim()) return "缺少 User ID";
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
    user_id: els.userId.value.trim(),
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
  try {
    const response = await fetch("/v1/skills");
    const data = await readJson(response);
    renderSkills(data.skills || []);
  } catch (err) {
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
    input.checked = Boolean(skill.enabled_by_default) || skill.id === "enterprise-policy";
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
  const response = await fetch("/v1/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await readJson(response);
  applyRunMeta(data);
  if (data.error) {
    appendMessage("error", data.error.message || "run failed");
    setStatus("failed");
    return;
  }
  appendMessage("assistant", data.message || "");
  setStatus(data.status || "completed");
}

async function runStream(body) {
  const response = await fetch("/v1/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    throw new Error(await response.text());
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";
    for (const rawEvent of events) handleSseEvent(rawEvent);
  }
  if (buffer.trim()) handleSseEvent(buffer);
}

function handleSseEvent(rawEvent) {
  const lines = rawEvent.split("\n");
  const event = (lines.find((line) => line.startsWith("event:")) || "").slice(6).trim();
  const dataLine = lines.find((line) => line.startsWith("data:"));
  if (!dataLine) return;
  const data = JSON.parse(dataLine.slice(5).trim());

  if (event === "run.started") {
    applyRunMeta(data);
    setStatus("running");
  } else if (event === "message.delta") {
    appendAssistantDelta(data.text || "");
  } else if (event === "tool.call.started") {
    finishAssistantBlock();
    appendToolCall(data, "running");
  } else if (event === "tool.call.completed") {
    finishAssistantBlock();
    appendToolCall(data, "completed");
  } else if (event === "tool.call.failed") {
    finishAssistantBlock();
    appendToolCall(data, "failed");
  } else if (event === "run.completed") {
    applyRunMeta(data);
    setStatus("completed");
  } else if (event === "run.failed") {
    appendMessage("error", data.error?.message || "run failed");
    setStatus("failed");
  }
}

async function readJson(response) {
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(data.error?.message || text || `HTTP ${response.status}`);
  }
  return data;
}

async function checkHealth() {
  try {
    const response = await fetch("/health");
    setStatus(response.ok ? "ready" : "unhealthy");
  } catch {
    setStatus("offline");
  }
}

function applyRunMeta(data) {
  if (data.run_id) els.runId.textContent = data.run_id;
  if (data.thread_id) {
    els.threadId.value = data.thread_id;
    updatePromptState();
  }
  if (data.status) setStatus(data.status);
}

function appendAssistantDelta(text) {
  if (!state.assistantNode) {
    state.assistantNode = appendMessage("assistant", "");
  }
  const content = state.assistantNode.querySelector(".message-content");
  content.textContent += text;
  scrollMessages();
}

function finishAssistantBlock() {
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
  content.textContent = text;
  item.append(title, content);
  els.messages.appendChild(item);
  scrollMessages();
  return item;
}

function appendToolCall(data, status) {
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
  els.settingsToggle.setAttribute("aria-expanded", String(open));
}

function renderEmpty() {
  els.messages.innerHTML = '<div class="empty">向我提问公司的请假、报销、审批流程或其他制度问题，我会检索已启用的制度资料并给出依据。</div>';
}

function clearEmpty() {
  const empty = els.messages.querySelector(".empty");
  if (empty) empty.remove();
}

function scrollMessages() {
  els.messages.scrollTop = els.messages.scrollHeight;
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
  };
  els.status.textContent = labels[status] || status;
  const configStatus = document.querySelector("#configStatus");
  if (configStatus) configStatus.textContent = status;
}

function setBusy(busy, status) {
  els.send.disabled = busy;
  els.agentRole.disabled = busy;
  els.threadId.disabled = busy;
  els.skillOptions.querySelectorAll("input").forEach((input) => {
    input.disabled = busy || Boolean(els.threadId.value.trim());
  });
  if (status) setStatus(status);
  updatePromptState();
}
