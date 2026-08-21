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
  fillPrompt: document.querySelector("#fillPrompt"),
};

const state = {
  assistantNode: null,
};

const EXAMPLE_PROMPT = "你是一个专业影视创作助手。回答要简洁，优先给出可执行方案；涉及分镜时输出镜号、景别、镜头运动和画面描述。";

renderEmpty();
updatePromptState();
checkHealth();

els.agentRole.addEventListener("change", updatePromptState);
els.threadId.addEventListener("input", updatePromptState);

els.newThread.addEventListener("click", () => {
  els.threadId.value = "";
  els.runId.textContent = "-";
  state.assistantNode = null;
  setStatus("idle");
  renderEmpty();
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
    stream: els.streamMode.checked,
    content,
  };

  if (!threadId) {
    body.agent_role = agentRole || null;
    if (!agentRole) {
      body.agent_prompt = els.agentPrompt.value.trim();
    }
  }
  return body;
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
    appendMessage("tool", `调用工具 ${data.tool_type || ""}`);
  } else if (event === "tool.call.completed") {
    appendMessage("tool", `工具完成 ${data.tool_type || ""}`);
  } else if (event === "tool.call.failed") {
    appendMessage("error", data.error?.message || "工具调用失败");
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

function renderEmpty() {
  els.messages.innerHTML = '<div class="empty">创建新会话时可选择角色，也可以选择 custom prompt 并填写独立系统提示词。</div>';
}

function clearEmpty() {
  const empty = els.messages.querySelector(".empty");
  if (empty) empty.remove();
}

function scrollMessages() {
  els.messages.scrollTop = els.messages.scrollHeight;
}

function setStatus(status) {
  els.status.textContent = status;
}

function setBusy(busy, status) {
  els.send.disabled = busy;
  els.agentRole.disabled = busy;
  els.threadId.disabled = busy;
  els.streamMode.disabled = busy;
  if (status) setStatus(status);
  updatePromptState();
}
