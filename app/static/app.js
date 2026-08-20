const els = {
  userId: document.querySelector("#userId"),
  threadId: document.querySelector("#threadId"),
  agentRole: document.querySelector("#agentRole"),
  agentPrompt: document.querySelector("#agentPrompt"),
  streamMode: document.querySelector("#streamMode"),
  runId: document.querySelector("#runId"),
  status: document.querySelector("#status"),
  messages: document.querySelector("#messages"),
  composer: document.querySelector("#composer"),
  prompt: document.querySelector("#prompt"),
  imageUrl: document.querySelector("#imageUrl"),
  send: document.querySelector("#send"),
  newThread: document.querySelector("#newThread"),
  loadHistory: document.querySelector("#loadHistory"),
  clearContext: document.querySelector("#clearContext"),
};

const state = {
  assistantNode: null,
  toolNodes: new Map(),
};

renderEmpty();
checkHealth();

els.composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = els.prompt.value.trim();
  const imageUrl = els.imageUrl.value.trim();
  if (!text && !imageUrl) return;

  const validationError = validateRunControls();
  if (validationError) {
    appendMessage("error", validationError);
    return;
  }

  appendMessage("user", [text, imageUrl && `[image] ${imageUrl}`].filter(Boolean).join("\n"));
  els.prompt.value = "";
  els.imageUrl.value = "";

  const body = buildRunBody(text, imageUrl);
  state.assistantNode = null;
  state.toolNodes.clear();
  setBusy(true, "running");

  try {
    if (body.stream) {
      try {
        await runStream(body);
      } catch (error) {
        appendMessage("system", "流式读取失败，已自动改用非流式重试。");
        body.stream = false;
        await runJson(body);
      }
    } else {
      await runJson(body);
    }
  } catch (error) {
    appendMessage("error", error.message || String(error));
    setStatus("failed");
  } finally {
    setBusy(false);
  }
});

els.newThread.addEventListener("click", () => {
  els.threadId.value = "";
  els.runId.textContent = "-";
  setStatus("idle");
  state.assistantNode = null;
  state.toolNodes.clear();
  renderEmpty();
});

els.agentRole.addEventListener("change", updateAgentPromptState);
els.threadId.addEventListener("input", updateAgentPromptState);

els.loadHistory.addEventListener("click", async () => {
  const userId = els.userId.value.trim();
  const threadId = els.threadId.value.trim();
  if (!userId || !threadId) {
    appendMessage("error", "缺少 user_id 或 thread_id");
    return;
  }
  setBusy(true, "loading");
  try {
    const response = await fetch(`/v1/threads/${encodeURIComponent(threadId)}/messages?user_id=${encodeURIComponent(userId)}&page=1&page_size=20`);
    const data = await readJson(response);
    renderHistory(data.messages || []);
    setStatus("history loaded");
  } catch (error) {
    appendMessage("error", error.message || String(error));
    setStatus("failed");
  } finally {
    setBusy(false);
  }
});

els.clearContext.addEventListener("click", async () => {
  const userId = els.userId.value.trim();
  const threadId = els.threadId.value.trim();
  if (!userId || !threadId) {
    appendMessage("error", "缺少 user_id 或 thread_id");
    return;
  }
  setBusy(true, "clearing");
  try {
    const response = await fetch(`/v1/threads/${encodeURIComponent(threadId)}/context`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    });
    await readJson(response);
    appendMessage("system", "上下文已清除");
    setStatus("context cleared");
  } catch (error) {
    appendMessage("error", error.message || String(error));
    setStatus("failed");
  } finally {
    setBusy(false);
  }
});

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
  const body = {
    user_id: els.userId.value.trim(),
    thread_id: threadId || null,
    client_message_id: `msg_${Date.now()}_${Math.random().toString(16).slice(2)}`,
    stream: els.streamMode.checked,
    content,
  };

  if (!threadId) {
    const agentRole = els.agentRole.value.trim();
    body.agent_role = agentRole || null;
    if (!agentRole) {
      body.agent_prompt = els.agentPrompt.value.trim();
    }
  }
  return body;
}

function validateRunControls() {
  const threadId = els.threadId.value.trim();
  if (threadId) return "";
  const agentRole = els.agentRole.value.trim();
  const agentPrompt = els.agentPrompt.value.trim();
  if (!agentRole && !agentPrompt) {
    return "新会话选择 agent_role 为 null 时，需要填写 agent_prompt";
  }
  return "";
}

function updateAgentPromptState() {
  const isExistingThread = Boolean(els.threadId.value.trim());
  const isCustomPrompt = !els.agentRole.value.trim();
  els.agentPrompt.disabled = isExistingThread || !isCustomPrompt;
  els.agentPrompt.placeholder = isExistingThread
    ? "已有 thread_id 时沿用会话的系统提示词"
    : "agent_role 为 null 时填写系统提示词";
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
  } else {
    appendMessage("assistant", data.message || "");
    setStatus(data.status);
  }
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
    for (const rawEvent of events) {
      handleSseEvent(rawEvent);
    }
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
    upsertToolCall(data, "running");
  } else if (event === "tool.call.completed") {
    upsertToolCall(data, "completed");
  } else if (event === "tool.call.failed") {
    upsertToolCall(data, "failed");
  } else if (event === "run.completed") {
    applyRunMeta(data);
    setStatus("completed");
  } else if (event === "run.failed") {
    appendMessage("error", data.error?.message || "run failed");
    setStatus("failed");
  }
}

function applyRunMeta(data) {
  if (data.run_id) els.runId.textContent = data.run_id;
  if (data.thread_id) els.threadId.value = data.thread_id;
  if (data.status) setStatus(data.status);
}

function appendAssistantDelta(text) {
  if (!state.assistantNode) {
    state.assistantNode = appendMessage("assistant", "");
  }
  const content = state.assistantNode.querySelector(".content");
  content.textContent += text;
  scrollMessages();
}

function upsertToolCall(data, status) {
  const key = data.tool_call_id || `${data.run_id || "run"}:${data.tool_type || "tool"}:${state.toolNodes.size}`;
  let node = state.toolNodes.get(key);
  if (!node) {
    node = createToolNode(data);
    state.toolNodes.set(key, node);
    clearEmpty();
    els.messages.appendChild(node.root);
  }

  node.title.textContent = data.tool_type || "tool";
  node.id.textContent = data.tool_call_id || "-";
  node.status.textContent = toolStatusLabel(status);
  node.status.dataset.status = status;
  node.root.dataset.status = status;

  if (status === "running") {
    node.stage.textContent = "工具调用中";
    node.arguments.textContent = formatJson(data.arguments || {});
    node.result.textContent = "";
    node.error.textContent = "";
    node.resultBlock.hidden = true;
    node.errorBlock.hidden = true;
  } else if (status === "completed") {
    node.stage.textContent = "工具调用后";
    node.result.textContent = formatJson(data.result || {});
    node.resultBlock.hidden = false;
    node.error.textContent = "";
    node.errorBlock.hidden = true;
  } else {
    node.stage.textContent = "工具调用后";
    node.error.textContent = data.error?.message || "工具调用失败";
    node.errorBlock.hidden = false;
    node.result.textContent = "";
    node.resultBlock.hidden = true;
  }
  scrollMessages();
}

function createToolNode(data) {
  const root = document.createElement("article");
  root.className = "tool-call";
  root.dataset.status = "running";

  const header = document.createElement("div");
  header.className = "tool-call-header";

  const main = document.createElement("div");
  main.className = "tool-call-main";

  const stage = document.createElement("span");
  stage.className = "tool-call-stage";
  stage.textContent = "工具开始";

  const title = document.createElement("strong");
  title.className = "tool-call-title";
  title.textContent = data.tool_type || "tool";

  const meta = document.createElement("span");
  meta.className = "tool-call-id";
  const id = document.createElement("span");
  id.textContent = data.tool_call_id || "-";
  meta.append("ID ", id);

  main.append(stage, title, meta);

  const status = document.createElement("span");
  status.className = "tool-call-status";
  status.dataset.status = "running";
  status.textContent = toolStatusLabel("running");
  header.append(main, status);

  const argumentsBlock = createToolBlock("参数");
  const resultBlock = createToolBlock("结果");
  const errorBlock = createToolBlock("错误");
  resultBlock.wrapper.hidden = true;
  errorBlock.wrapper.hidden = true;

  root.append(header, argumentsBlock.wrapper, resultBlock.wrapper, errorBlock.wrapper);
  return {
    root,
    stage,
    title,
    id,
    status,
    arguments: argumentsBlock.value,
    result: resultBlock.value,
    resultBlock: resultBlock.wrapper,
    error: errorBlock.value,
    errorBlock: errorBlock.wrapper,
  };
}

function createToolBlock(labelText) {
  const wrapper = document.createElement("div");
  wrapper.className = "tool-call-block";
  const label = document.createElement("span");
  label.className = "tool-call-label";
  label.textContent = labelText;
  const value = document.createElement("pre");
  value.className = "tool-call-value";
  wrapper.append(label, value);
  return { wrapper, value };
}

function toolStatusLabel(status) {
  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  return "调用中";
}

function appendMessage(role, text) {
  clearEmpty();
  const node = document.createElement("article");
  node.className = `message ${role}`;
  const label = document.createElement("span");
  label.className = "role";
  label.textContent = role;
  const content = document.createElement("div");
  content.className = "content";
  content.textContent = text;
  node.append(label, content);
  els.messages.appendChild(node);
  scrollMessages();
  return node;
}

function renderHistory(items) {
  els.messages.innerHTML = "";
  state.assistantNode = null;
  state.toolNodes.clear();
  if (!items.length) {
    renderEmpty("暂无历史");
    return;
  }
  for (const item of [...items].reverse()) {
    if (item.user) appendMessage("user", flattenContent(item.user.content));
    if (item.assistant) appendMessage("assistant", flattenContent(item.assistant.content));
  }
}

function flattenContent(content) {
  return (content || [])
    .map((block) => block.text || block.url || JSON.stringify(block))
    .join("\n");
}

function formatJson(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

async function readJson(response) {
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(text || response.statusText);
  }
  if (!response.ok) {
    throw new Error(data.detail || data.error?.message || response.statusText);
  }
  return data;
}

function renderEmpty(text = "开始一个新的测试会话") {
  els.messages.innerHTML = `<div class="empty">${text}</div>`;
}

function clearEmpty() {
  const empty = els.messages.querySelector(".empty");
  if (empty) empty.remove();
}

function scrollMessages() {
  els.messages.scrollTop = els.messages.scrollHeight;
}

function setBusy(isBusy, status) {
  els.send.disabled = isBusy;
  els.loadHistory.disabled = isBusy;
  els.clearContext.disabled = isBusy;
  if (status) setStatus(status);
}

function setStatus(status) {
  els.status.textContent = status;
}

async function checkHealth() {
  try {
    const response = await fetch("/health", { cache: "no-store" });
    await readJson(response);
    setStatus("ready");
  } catch (error) {
    setStatus("backend unreachable");
    appendMessage(
      "error",
      `无法连接后端：${error.message || String(error)}\n请确认访问的是服务器地址，而不是 127.0.0.1。`
    );
  }
}

updateAgentPromptState();
