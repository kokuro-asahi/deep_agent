const els = {
  userId: document.querySelector("#userId"),
  threadId: document.querySelector("#threadId"),
  agentRole: document.querySelector("#agentRole"),
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
};

renderEmpty();
checkHealth();

els.composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = els.prompt.value.trim();
  const imageUrl = els.imageUrl.value.trim();
  if (!text && !imageUrl) return;

  appendMessage("user", [text, imageUrl && `[image] ${imageUrl}`].filter(Boolean).join("\n"));
  els.prompt.value = "";
  els.imageUrl.value = "";

  const body = buildRunBody(text, imageUrl);
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
  renderEmpty();
});

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
    body.agent_role = els.agentRole.value.trim();
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
  state.assistantNode = appendMessage("assistant", "");

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
