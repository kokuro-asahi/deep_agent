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
  sidebarSettings: document.querySelector("#sidebarSettings"),
  settingsBackdrop: document.querySelector("#settingsBackdrop"),
  userMenu: document.querySelector("#userMenu"),
  userSearch: document.querySelector("#userSearch"),
  userOptions: document.querySelector("#userOptions"),
  currentUserName: document.querySelector("#currentUserName"),
  userAvatar: document.querySelector("#userAvatar"),
  conversationNav: document.querySelector(".conversation-nav"),
  loginOverlay: document.querySelector("#loginOverlay"),
  loginForm: document.querySelector("#loginForm"),
  loginUserId: document.querySelector("#loginUserId"),
  closeSettings: document.querySelector("#closeSettings"),
  topNewThread: document.querySelector("#topNewThread"),
  clearChat: document.querySelector("#clearChat"),
  messages: document.querySelector("#messages"),
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
  toolCards: new Map(),
  toolActivities: new Map(),
  users: [],
};

const EXAMPLE_PROMPT = "你是一个专业影视创作助手。回答要简洁，优先给出可执行方案；涉及分镜时输出镜号、景别、镜头运动和画面描述。";

renderEmpty();
updatePromptState();
checkHealth();
loadSkills();

els.agentRole.addEventListener("change", updatePromptState);
els.topbarAgentRole.addEventListener("change", () => {
  els.agentRole.value = els.topbarAgentRole.value;
  updatePromptState();
});
els.threadId.addEventListener("input", updatePromptState);
els.settingsToggle.addEventListener("click", () => setSettingsOpen(true));
els.sidebarSettings.addEventListener("click", toggleUserMenu);
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
els.userSearch.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && els.userSearch.value.trim()) selectUser(els.userSearch.value.trim());
});
els.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const userId = els.loginUserId.value.trim();
  if (!userId) return;
  await selectUser(userId);
  els.loginOverlay.classList.add("hidden");
  els.prompt.focus();
});

els.newThread.addEventListener("click", () => {
  els.threadId.value = "";
  els.runId.textContent = "-";
  state.assistantNode = null;
  state.suppressPostImageText = false;
  state.toolCards.clear();
  state.toolActivities.clear();
  setStatus("idle");
  renderEmpty();
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
  state.suppressPostImageText = false;

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
  els.topbarAgentRole.disabled = hasThread || els.agentRole.disabled;
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
  if (els.topbarAgentRole.value !== els.agentRole.value) els.topbarAgentRole.value = els.agentRole.value;
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
    if (!state.suppressPostImageText) appendAssistantDelta(data.text || "");
  } else if (event === "tool.call.started") {
    finishAssistantBlock();
    appendToolCall(data, "running");
  } else if (event === "tool.call.completed") {
    finishAssistantBlock();
    appendToolCall(data, "completed");
  } else if (event === "tool.call.failed") {
    finishAssistantBlock();
    appendToolCall(data, "failed");
  } else if (event === "artifact.created") {
    finishAssistantBlock();
    appendArtifact(data.artifact);
    // Images are already rendered as artifacts. The model's follow-up is often
    // a duplicate Markdown delivery report, which should not clutter the chat.
    if (data.artifact?.type === "image") state.suppressPostImageText = true;
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
  if (data.thread_id) loadThreads();
}

function appendAssistantDelta(text) {
  if (!state.assistantNode) {
    state.assistantNode = appendMessage("assistant", "");
  }
  const content = state.assistantNode.querySelector(".message-content");
  state.assistantNode.dataset.markdown = `${state.assistantNode.dataset.markdown || ""}${text}`;
  renderMarkdown(content, state.assistantNode.dataset.markdown);
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
  item.dataset.markdown = text;
  renderMarkdown(content, text);
  item.append(title, content);
  els.messages.appendChild(item);
  scrollMessages();
  return item;
}

function appendArtifact(artifact) {
  if (!artifact || artifact.type !== "image" || !artifact.metadata?.url) return;
  const item = appendMessage("assistant", "");
  const content = item.querySelector(".message-content");
  content.replaceChildren(createImageArtifact(artifact));
  scrollMessages();
}

function appendStructuredMessage(role, blocks) {
  if (!Array.isArray(blocks) || !blocks.length) return null;
  const hasImageArtifact = role === "assistant" && blocks.some((block) => block?.type === "image");
  const text = blocks
    .filter((block) => !hasImageArtifact && block?.type === "text" && typeof block.text === "string")
    .map((block) => block.text)
    .join("\n");
  const item = appendMessage(role, text);
  const content = item.querySelector(".message-content");
  for (const block of blocks) {
    if (block?.type !== "image") continue;
    const image = createImageArtifact(block);
    if (image) content.appendChild(image);
  }
  return item;
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
  els.messages.innerHTML = '<div class="empty">向我提问公司的请假、报销、审批流程或其他制度问题，我会检索已启用的制度资料并给出依据。</div>';
}

async function toggleUserMenu() {
  const open = !els.userMenu.classList.contains("open");
  els.userMenu.classList.toggle("open", open);
  els.sidebarSettings.setAttribute("aria-expanded", String(open));
  if (!open) return;
  els.userSearch.value = "";
  await loadUsers();
  els.userSearch.focus();
}

async function loadUsers() {
  try {
    const response = await fetch("/v1/threads/users");
    const data = await readJson(response);
    state.users = data.users || [];
    renderUserOptions(state.users);
  } catch (err) {
    els.userOptions.textContent = `用户加载失败：${err.message || String(err)}`;
  }
}

function renderUserOptions(users) {
  els.userOptions.replaceChildren();
  const choices = [...new Set([els.userId.value.trim(), ...users].filter(Boolean))];
  for (const userId of choices) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "user-option";
    button.textContent = userId;
    button.addEventListener("click", () => selectUser(userId));
    els.userOptions.appendChild(button);
  }
  if (!choices.length) els.userOptions.textContent = "暂无历史用户；可直接输入 User ID。";
}

async function selectUser(userId) {
  els.userId.value = userId;
  els.currentUserName.textContent = userId;
  els.userAvatar.textContent = userId.slice(0, 2).toUpperCase();
  els.userMenu.classList.remove("open");
  els.sidebarSettings.setAttribute("aria-expanded", "false");
  els.threadId.value = "";
  els.runId.textContent = "-";
  state.assistantNode = null;
  state.toolCards.clear();
  state.toolActivities.clear();
  renderEmpty();
  updatePromptState();
  await loadThreads();
}

async function loadThreads() {
  const userId = els.userId.value.trim();
  if (!userId) return;
  try {
    const response = await fetch(`/v1/threads/by-user/${encodeURIComponent(userId)}`);
    const data = await readJson(response);
    renderThreads(data.threads || []);
  } catch (err) {
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
  els.threadId.value = thread.thread_id;
  updatePromptState();
  state.assistantNode = null;
  state.toolCards.clear();
  state.toolActivities.clear();
  els.messages.replaceChildren();
  els.conversationNav.querySelectorAll(".conversation").forEach((item) => {
    item.classList.toggle("active", item.dataset.threadId === thread.thread_id);
  });
  try {
    const response = await fetch(`/v1/threads/${encodeURIComponent(thread.thread_id)}/messages?user_id=${encodeURIComponent(els.userId.value)}&page=1&page_size=100`);
    const data = await readJson(response);
    const conversations = [...(data.messages || [])].reverse();
    for (const conversation of conversations) {
      if (conversation.user?.content?.length) appendStructuredMessage("user", conversation.user.content);
      if (conversation.assistant?.content?.length) appendStructuredMessage("assistant", conversation.assistant.content);
    }
    if (!conversations.length) renderEmpty();
  } catch (err) {
    appendMessage("error", `历史消息加载失败：${err.message || String(err)}`);
  }
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
  if (els.statusDot) els.statusDot.style.background = status === "failed" || status === "offline" ? "#e16d68" : status === "running" ? "#dfaa44" : "#55bd88";
  const configStatus = document.querySelector("#configStatus");
  if (configStatus) configStatus.textContent = status;
}

function setBusy(busy, status) {
  els.send.disabled = busy;
  els.agentRole.disabled = busy;
  els.topbarAgentRole.disabled = busy || Boolean(els.threadId.value.trim());
  els.threadId.disabled = busy;
  els.skillOptions.querySelectorAll("input").forEach((input) => {
    input.disabled = busy || Boolean(els.threadId.value.trim());
  });
  if (status) setStatus(status);
  updatePromptState();
}

function autoResizePrompt() {
  els.prompt.style.height = "auto";
  els.prompt.style.height = `${Math.min(els.prompt.scrollHeight, 160)}px`;
}
