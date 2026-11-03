// Run with: node --test tests/frontend.test.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../app/static/app.js"), "utf8");

function createApp({ realScroll = false, authenticated = true, fetchImpl } = {}) {
  const frames = new Map();
  let nextFrame = 0;
  const makeElement = () => {
    const classes = new Set();
    const element = {
      value: "", style: {}, dataset: {}, events: {}, listeners: {}, attributes: {}, children: [],
      classList: {
        contains(name) { return classes.has(name); },
        add(name) { classes.add(name); }, remove(name) { classes.delete(name); },
        toggle(name, force) {
          const enabled = force === undefined ? !classes.has(name) : force;
          if (enabled) classes.add(name); else classes.delete(name);
          return enabled;
        },
      },
      addEventListener(name, callback) { this.listeners[name] = callback; this.events[name] = callback; },
      querySelector(selector) { return selector === "button" ? makeElement() : null; },
      querySelectorAll() { return []; }, closest() { return this; },
      setAttribute(name, value) { this.attributes[name] = value; },
      focus() { this.focused = true; },
      append(...items) { this.children.push(...items); },
      appendChild(item) { this.children.push(item); return item; },
      replaceChildren(...items) { this.children = items; },
    };
    return element;
  };
  const elements = new Map();
  const context = vm.createContext({
    document: {
      querySelector(selector) {
        if (!elements.has(selector)) elements.set(selector, makeElement());
        return elements.get(selector);
      },
      createElement: makeElement,
    },
    AbortController, TextDecoder, URLSearchParams, URL,
    // Startup requests are unrelated to these deterministic rendering tests.
    fetch: fetchImpl || (() => new Promise(() => {})),
    requestAnimationFrame(callback) { frames.set(++nextFrame, callback); return nextFrame; },
    cancelAnimationFrame(id) { frames.delete(id); },
  });
  vm.runInContext(source, context);
  if (authenticated) vm.runInContext('state.currentUser = { user_id: "test-user", username: "test", access_level: 1 }', context);
  vm.runInContext(`
    const messages = [];
    let renderCount = 0;
    appendMessage = (role, text) => {
      const content = {
        html: "",
        children: [],
        appendChild(child) { this.children.push(child); },
        replaceChildren(...children) { this.children = children; },
        set innerHTML(value) { this.html = value; renderCount += 1; }
      };
      const item = { role, dataset: { markdown: text }, content,
        querySelector: () => content };
      messages.push(item);
      return item;
    };
    const originalScrollMessages = scrollMessages;
    scrollMessages = () => {};
    appendToolCall = (data, status) => messages.push({ role: "tool", status });
    applyRunMeta = () => {};
  `, context);
  if (realScroll) vm.runInContext('scrollMessages = originalScrollMessages', context);
  return {
    context, frames,
    run(code) { return vm.runInContext(code, context, { timeout: 1000 }); },
    render(markdown) {
      context.markdown = markdown;
      return this.run('constContainer = {}; renderMarkdown(constContainer, markdown); constContainer.innerHTML');
    },
    tick() { for (const callback of [...frames.values()]) callback(); },
  };
}

test("incomplete heading and list markers always terminate", () => {
  const app = createApp();
  for (const marker of ["# ", "## ", "###### ", "- ", "* ", "+ ", "1. ", "123. ", "  -\t"]) {
    for (const prefix of ["", "查询过程与缺口说明：\n", "结论\n\n"]) {
      assert.ok(app.render(prefix + marker).includes(marker));
    }
  }
});

test("every prefix of a streamed policy answer can be rendered", () => {
  const app = createApp();
  const answer = [
    "## 审批结论", "", "**结论：** 需要按制度审批。", "",
    "查询过程与缺口说明：", "- 查询请假制度", "- 核对审批权限", "",
    "1. 提交申请", "2. 等待审核", "", "> 参考条款", "",
    "| 部门 | 审批人 |", "| --- | --- |", "| 审计法务部 | 分管领导 |", "",
    "```text", "审批流程", "```", "", "---", "请核对来源。",
  ].join("\n");
  for (let end = 0; end <= answer.length; end += 1) app.render(answer.slice(0, end));
  const html = app.render(answer);
  for (const tag of ["<h2>", "<strong>", "<ul>", "<ol>", "<blockquote>", "<table>", "<pre>", "<hr>"]) {
    assert.ok(html.includes(tag), tag);
  }
  assert.ok(html.endsWith("<p>请核对来源。</p>"));
});

test("plain paragraphs and escaping still render correctly", () => {
  const app = createApp();
  assert.equal(app.render("第一行\n第二行\n\n下一段"), "<p>第一行<br>第二行</p><p>下一段</p>");
  assert.equal(app.render("<script>危险</script>"), "<p>&lt;script&gt;危险&lt;/script&gt;</p>");
});

test("a burst of deltas renders once per frame without losing text", () => {
  const app = createApp();
  app.run('appendAssistantDelta("")');
  assert.equal(app.frames.size, 0);
  for (const text of ["## ", "审批结论", "\n\n", "- ", "提交申请"]) {
    app.context.delta = text;
    app.run("appendAssistantDelta(delta)");
  }
  assert.equal(app.frames.size, 1);
  assert.equal(app.run("renderCount"), 0);
  app.tick();
  assert.equal(app.frames.size, 0);
  assert.equal(app.run("renderCount"), 1);
  assert.equal(app.run("messages[0].content.html"), "<h2>审批结论</h2><ul><li>提交申请</li></ul>");
});

test("tool boundaries flush narration before opening the next answer", () => {
  const app = createApp();
  app.run('appendAssistantDelta("正在查询制度"); handleSseEvent(\'event: tool.call.started\\ndata: {}\')');
  assert.equal(app.frames.size, 0);
  assert.equal(app.run("messages[0].content.html"), "<p>正在查询制度</p>");
  app.run('appendAssistantDelta("## ")');
  app.tick();
  app.run('appendAssistantDelta("审批结论")');
  app.tick();
  assert.equal(app.run("messages.length"), 3);
  assert.equal(app.run("messages[1].role"), "tool");
  assert.equal(app.run("messages[2].content.html"), "<h2>审批结论</h2>");
});

test("completion and failure flush the final delta even before a frame runs", () => {
  for (const event of ["run.completed", "run.failed"]) {
    const app = createApp();
    app.context.event = `event: ${event}\ndata: {}`;
    app.run('appendAssistantDelta("最后一段"); handleSseEvent(event)');
    assert.equal(app.frames.size, 0);
    assert.equal(app.run("messages[0].content.html"), "<p>最后一段</p>");
    assert.equal(app.run("state.assistantNode"), null);
    assert.equal(app.run("els.status.textContent"), event === "run.completed" ? "已完成" : "查询失败");
  }
});

test("plan events render statuses and progress using safe text", () => {
  const app = createApp();
  app.context.planEvent = 'event: plan.updated\ndata: ' + JSON.stringify({ todos: [
    { content: '已找到依据', status: 'completed' },
    { content: '<img src=x onerror=alert(1)>', status: 'in_progress' },
    { content: '生成回答', status: 'pending' },
  ] });
  app.run('handleSseEvent(planEvent)');
  assert.equal(app.run('els.taskPlan.hidden'), false);
  assert.equal(app.run('els.planSummary.textContent'), '已完成 1/3 · <img src=x onerror=alert(1)>');
  assert.equal(app.run('els.planList.children.length'), 3);
  assert.equal(app.run('els.planList.children[1].children[0].textContent'), '执行中');
  assert.equal(app.run('els.planList.children[1].children[1].textContent'), '<img src=x onerror=alert(1)>');
});

test("run completion and failure preserve actual unfinished steps", () => {
  for (const event of ['run.completed', 'run.failed']) {
    const app = createApp();
    app.run('renderPlan([{ content: "核对依据", status: "in_progress" }])');
    app.context.runEvent = `event: ${event}\ndata: {}`;
    app.run('handleSseEvent(runEvent)');
    assert.equal(app.run('state.todos[0].status'), 'in_progress');
    assert.ok(app.run('els.planSummary.textContent').includes(event === 'run.failed' ? '运行中断' : '回答已结束'));
    assert.equal(app.run('els.planList.children[0].children[0].textContent'), event === 'run.failed' ? '未完成' : '未确认完成');
    assert.equal(app.run('els.planList.children[0].className'), 'plan-step unconfirmed');
    app.run('renderPlan([])');
    assert.equal(app.run('els.taskPlan.hidden'), true);
    assert.equal(app.run('els.planList.children.length'), 0);
  }
});

test("plan events for another conversation are ignored", () => {
  const app = createApp();
  app.run('els.threadId.value = "current-thread"');
  app.context.planEvent = 'event: plan.updated\ndata: ' + JSON.stringify({ thread_id: 'old-thread', todos: [
    { content: '旧会话步骤', status: 'pending' },
  ] });
  app.run('handleSseEvent(planEvent)');
  assert.equal(app.run('state.todos.length'), 0);
});

test("starting a run reports processing without pretending a plan exists", () => {
  const app = createApp();
  app.run('handleSseEvent(\'event: run.started\\ndata: {}\')');
  assert.equal(app.run('els.taskPlan.hidden'), false);
  assert.equal(app.run('els.planSummary.textContent'), '正在处理请求…');
  assert.equal(app.run('els.planTitle.textContent'), '任务进度');
  assert.equal(app.run('els.planList.children.length'), 0);
});

test("progress follows real tool activity and response generation without a todo list", () => {
  const app = createApp();
  app.run('handleSseEvent(\'event: run.started\\ndata: {}\')');
  for (const [tool, label] of [['bocha_search', '正在搜索网络资料…'], ['generate_image', '正在生成配图…'], ['generate_ppt', '正在生成 PPT 和预览…']]) {
    app.context.start = `event: tool.call.started\ndata: ${JSON.stringify({tool_type: tool, tool_call_id: tool})}`;
    app.context.done = `event: tool.call.completed\ndata: ${JSON.stringify({tool_type: tool, tool_call_id: tool})}`;
    app.run('handleSseEvent(start)');
    assert.equal(app.run('els.planSummary.textContent'), label);
    app.run('handleSseEvent(done)');
    assert.equal(app.run('els.planSummary.textContent'), '工具已完成，正在继续处理…');
  }
  app.run('handleSseEvent(\'event: message.delta\\ndata: {"text":"PPT 已生成"}\')');
  assert.equal(app.run('els.planSummary.textContent'), '正在生成回复…');
  assert.equal(app.run('state.todos.length'), 0);
  app.run('handleSseEvent(\'event: run.completed\\ndata: {}\')');
  assert.equal(app.run('els.taskPlan.hidden'), true);
});

test("finishing one parallel tool does not hide another running tool", () => {
  const app = createApp();
  app.run('handleSseEvent(\'event: run.started\\ndata: {}\')');
  app.run('updateToolProgress({tool_type: "bocha_search", tool_call_id: "search"}, "running")');
  app.run('updateToolProgress({tool_type: "generate_image", tool_call_id: "image"}, "running")');
  app.run('updateToolProgress({tool_type: "bocha_search", tool_call_id: "search"}, "completed")');
  assert.equal(app.run('els.planSummary.textContent'), '正在生成配图…');
});

test("opening history restores its saved plan", async () => {
  const app = createApp();
  app.context.history = { messages: [], todos: [{ content: '已保存的步骤', status: 'completed' }] };
  app.run('fetch = async () => ({ ok: true, text: async () => JSON.stringify(history) })');
  await app.run('openThread({ thread_id: "saved-thread" })');
  assert.equal(app.run('els.taskPlan.hidden'), false);
  assert.equal(app.run('els.planSummary.textContent'), '已完成 1/1');
  assert.equal(app.run('els.planList.children[0].children[1].textContent'), '已保存的步骤');
});

test("a late history response cannot overwrite a newer conversation plan", async () => {
  const app = createApp();
  app.run('fetch = () => new Promise((resolve) => { resolveHistory = resolve; })');
  const opening = app.run('openThread({ thread_id: "old-thread" })');
  app.run('state.viewVersion += 1; els.threadId.value = "new-thread"; renderPlan([{content: "当前步骤", status: "in_progress"}])');
  app.run('resolveHistory({ok: true, text: async () => JSON.stringify({messages: [], todos: [{content: "旧步骤", status: "completed"}]})})');
  await opening;
  assert.equal(app.run('state.todos[0].content'), '当前步骤');
});

test("completed history does not present a stale plan as running", async () => {
  const app = createApp();
  app.context.history = { messages: [], run_status: 'completed', todos: [
    { content: '查询依据', status: 'completed' },
    { content: '整理回答', status: 'in_progress' },
  ] };
  app.run('fetch = async () => ({ ok: true, text: async () => JSON.stringify(history) })');
  await app.run('openThread({ thread_id: "saved-thread" })');
  assert.equal(app.run('els.planSummary.textContent'), '回答已结束 · 已确认完成 1/2');
  assert.equal(app.run('els.planList.children[1].children[0].textContent'), '未确认完成');
  assert.equal(app.run('state.todos[1].status'), 'in_progress');
});

test("a fully completed plan shows task completion", () => {
  const app = createApp();
  app.run('renderPlan([{content: "整理回答", status: "completed"}], "completed")');
  assert.equal(app.run('els.planSummary.textContent'), '任务已完成 · 已完成 1/1');
  assert.equal(app.run('els.planList.children[0].children[0].textContent'), '已完成');
});

test("streaming follows the bottom until the reader scrolls away", () => {
  const app = createApp({ realScroll: true });
  app.run('els.messages.scrollHeight = 2000; els.messages.clientHeight = 500; scrollMessages()');
  assert.equal(app.run('els.messages.scrollTop'), 1500);
  app.run('els.messages.scrollTop = 400; trackMessageScroll(); els.messages.scrollHeight = 2500; appendAssistantDelta("新的回答")');
  app.tick();
  assert.equal(app.run('state.followOutput'), false);
  assert.equal(app.run('els.messages.scrollTop'), 400);
  app.run('appendAssistantDelta("，继续输出"); handleSseEvent(\'event: run.completed\\ndata: {}\')');
  assert.equal(app.run('els.messages.scrollTop'), 400);
});

test("returning to the bottom resumes following new output", () => {
  const app = createApp({ realScroll: true });
  app.run('els.messages.scrollHeight = 2000; els.messages.clientHeight = 500; els.messages.scrollTop = 400; trackMessageScroll()');
  assert.equal(app.run('state.followOutput'), false);
  app.run('els.messages.scrollTop = 1500; trackMessageScroll(); els.messages.scrollHeight = 3000; appendAssistantDelta("继续回答")');
  app.tick();
  assert.equal(app.run('state.followOutput'), true);
  assert.equal(app.run('els.messages.scrollTop'), 2500);
});


test("image artifacts and plan updates coexist without duplicate delivery text", () => {
  const app = createApp();
  app.run('appendArtifact = (artifact) => messages.push({role: "artifact", artifact})');
  app.context.planEvent = 'event: plan.updated\ndata: ' + JSON.stringify({todos: [{content: '生成图片', status: 'completed'}]});
  app.run('handleSseEvent(\'event: artifact.created\\ndata: {"artifact":{"type":"image","metadata":{"url":"https://example.com/image.png"}}}\')');
  app.run('handleSseEvent(planEvent); handleSseEvent(\'event: message.delta\\ndata: {"text":"重复交付报告"}\'); handleSseEvent(\'event: run.completed\\ndata: {}\')');
  assert.equal(app.run('messages.length'), 1);
  assert.equal(app.run('messages[0].role'), 'artifact');
  assert.equal(app.run('els.planSummary.textContent'), '任务已完成 · 已完成 1/1');
});

test("PPT downloads render in live events and restored history", () => {
  for (const live of [true, false]) {
    const app = createApp();
    app.context.artifact = { type: "file", metadata: {
      url: "https://example.com/report.pptx", file_name: "<报告>.pptx", slide_count: 5, size_bytes: 30720,
    } };
    if (live) {
      app.run('handleSseEvent("event: artifact.created\\ndata: " + JSON.stringify({ artifact }))');
    } else {
      app.run('appendStructuredMessage("assistant", [{type: "text", text: "已生成"}, artifact])');
    }
    assert.equal(app.run('messages[0].content.children[0].className'), 'file-artifact');
    assert.equal(app.run('messages[0].content.children[0].children[1].children[0].textContent'), '<报告>.pptx');
    assert.equal(app.run('messages[0].content.children[0].children[1].children[1].textContent'), '可编辑 PowerPoint · 5 页 · 30 KB');
    assert.equal(app.run('messages[0].content.children[0].children[2].href'), 'https://example.com/report.pptx');
    assert.equal(app.run('messages[0].content.children[0].children[2].download'), '<报告>.pptx');
  }
});

test("PPT file cards reject executable links", () => {
  const app = createApp();
  assert.equal(app.run('createFileArtifact({metadata: {url: "javascript:alert(1)"}})'), null);
});

test("PPT preview opens inline on demand in live output and history", () => {
  for (const live of [true, false]) {
    const app = createApp();
    app.context.artifact = {type: "file", metadata: {
      url: "https://example.com/report.pptx", file_name: "报告.pptx",
      preview_status: "ready", preview_mime_type: "application/pdf", preview_url: "https://example.com/preview.pdf",
    }};
    app.run(live ? 'appendArtifact(artifact)' : 'appendStructuredMessage("assistant", [artifact])');
    assert.equal(app.run('messages[0].content.children[0].children[3].className'), 'file-preview');
    assert.equal(app.run('messages[0].content.children[0].children[3].children[1].src'), undefined);
    app.run('const preview = messages[0].content.children[0].children[3]; preview.open = true; preview.events.toggle()');
    assert.equal(app.run('preview.children[1].src'), '/v1/artifacts/ppt-preview?url=https%3A%2F%2Fexample.com%2Fpreview.pdf#view=FitH');
    assert.equal(app.run('messages[0].content.children[0].children[2].href'), 'https://example.com/report.pptx');
  }
});

test("PPT preview rejects unsafe or unrelated embedded URLs", () => {
  const app = createApp();
  for (const url of ['javascript:alert(1)', 'https://other.example/preview.pdf', 'https://example.com/preview.html']) {
    app.context.metadata = {url: 'https://example.com/report.pptx', preview_status: 'ready', preview_mime_type: 'application/pdf', preview_url: url};
    assert.equal(app.run('isPdfPreview(metadata)'), false);
  }
});

test("an unavailable preview keeps the download link", () => {
  const app = createApp();
  app.run('const card = createFileArtifact({metadata: {url: "https://example.com/report.pptx", preview_status: "unavailable"}})');
  assert.equal(app.run('card.children[2].href'), 'https://example.com/report.pptx');
  assert.equal(app.run('card.children[3].textContent'), '预览暂不可用，可下载 PPT 查看。');
});

test("PPT generation after image generation restores assistant narration", () => {
  const app = createApp();
  app.run('state.suppressPostImageText = true');
  app.run('handleSseEvent(\'event: tool.call.started\\ndata: {"tool_type":"generate_ppt"}\')');
  app.run('handleSseEvent(\'event: message.delta\\ndata: {"text":"PPT 已生成"}\')');
  app.tick();
  assert.equal(app.run('messages[1].content.html'), '<p>PPT 已生成</p>');
});

function response(status, data = {}) {
  return { status, ok: status >= 200 && status < 300, text: async () => JSON.stringify(data) };
}

const loginUser = { user_id: "alice-id", username: "alice", access_level: 2, is_admin: false };
const nextTurn = () => new Promise(setImmediate);

test("startup checks the session before requesting protected data", async () => {
  const calls = [];
  let resolveSession;
  const app = createApp({ authenticated: false, fetchImpl: (url, options) => {
    calls.push({ url, options });
    return new Promise((resolve) => { resolveSession = resolve; });
  } });
  assert.deepEqual(calls.map((call) => call.url), ["/v1/auth/me"]);
  assert.equal(calls[0].options.credentials, "same-origin");
  assert.equal(app.run("els.workspace.inert"), true);
  assert.equal(app.run("els.loginSubmit.disabled"), true);
  resolveSession(response(401));
  await nextTurn();
  assert.equal(app.run("state.currentUser"), null);
  assert.equal(app.run("els.loginSubmit.disabled"), false);
  assert.equal(app.run("els.loginOverlay.classList.contains('hidden')"), false);
  assert.equal(app.run("els.loginError.hidden"), true);
  assert.equal(calls.length, 1);
});

test("page refresh restores a valid cookie session and loads only my threads", async () => {
  const calls = [];
  const app = createApp({ authenticated: false, fetchImpl: async (url, options) => {
    calls.push({ url, options });
    return response(200, url === "/v1/auth/me" ? loginUser : url === "/v1/skills" ? { skills: [] } : { threads: [] });
  } });
  await nextTurn();
  assert.equal(app.run("state.currentUser.user_id"), "alice-id");
  assert.equal(app.run("els.currentUserName.textContent"), "alice");
  assert.equal(app.run("els.currentUserLevel.textContent"), "alice · 中级用户");
  assert.equal(app.run("els.loginOverlay.classList.contains('hidden')"), true);
  assert.equal(app.run("els.workspace.inert"), false);
  assert.equal(app.run("els.logoutButton.hidden"), false);
  assert.ok(calls.some((call) => call.url === "/v1/threads/mine"));
  assert.ok(calls.some((call) => call.url === "/v1/skills"));
  assert.ok(!calls.some((call) => call.url.includes("by-user") || call.url.includes("/users")));
});

test("login submits username and password, clears password and uses cookie requests", async () => {
  const app = createApp({ authenticated: false });
  app.context.user = loginUser;
  app.run(`
    requireLogin();
    const authCalls = [];
    els.loginUsername.value = " alice ";
    els.loginPassword.value = "  exact password  ";
    fetch = async (url, options) => {
      authCalls.push({url, options});
      const data = url === "/v1/auth/login" ? {user, access_token: "must-not-be-stored"} : {};
      return {status: 200, ok: true, text: async () => JSON.stringify(data)};
    };
  `);
  await app.run("submitLogin({preventDefault(){}})");
  const calls = app.run("authCalls");
  assert.deepEqual(JSON.parse(calls[0].options.body), { username: "alice", password: "  exact password  " });
  assert.equal(calls[0].options.credentials, "same-origin");
  assert.equal(app.run("state.currentUser.user_id"), "alice-id");
  assert.equal(app.run("els.loginPassword.value"), "");
  assert.equal(app.run("els.send.disabled"), false);
  assert.equal(app.run("els.loginError.hidden"), true);
  assert.equal(app.run("els.loginForm.attributes['aria-busy']"), "false");
  assert.ok(calls.filter((call) => call.url.startsWith("/v1/")).every((call) => call.options.credentials === "same-origin"));
  app.run('els.agentRole.value = "enterprise_policy_advisor"; els.userId.value = "forged-user"');
  assert.equal(app.run("Object.hasOwn(buildRunBody('hello', ''), 'user_id')"), false);
});

test("invalid credentials stay on login and never request conversation data", async () => {
  const app = createApp({ authenticated: false });
  app.run(`
    requireLogin();
    els.loginUsername.value = "alice"; els.loginPassword.value = "bad";
    const authCalls = [];
    fetch = async (url) => {
      authCalls.push(url);
      return {status: 401, ok: false, text: async () => JSON.stringify({error: {message: "账号或密码错误"}})};
    };
  `);
  await app.run("submitLogin({preventDefault(){}})");
  assert.equal(app.run("state.currentUser"), null);
  assert.equal(app.run("els.loginError.textContent"), "账号或密码错误");
  assert.equal(app.run("els.loginPassword.value"), "");
  assert.equal(app.run("els.loginSubmit.disabled"), false);
  assert.equal(app.run("els.workspace.inert"), true);
  assert.equal(app.run("JSON.stringify(authCalls)"), '["/v1/auth/login"]');
});

test("401 clears the previous user's data and aborts streaming", async () => {
  const app = createApp();
  app.run(`
    els.userId.value = "alice-id"; els.threadId.value = "private-thread";
    els.prompt.value = "private draft"; els.agentPrompt.value = "private instruction";
    state.runController = new AbortController();
    const oldController = state.runController;
    renderPlan([{content: "private task", status: "in_progress"}]);
    fetch = async () => ({status: 401, ok: false});
  `);
  await assert.rejects(app.run('apiFetch("/v1/skills")'), /请重新登录/);
  assert.equal(app.run("oldController.signal.aborted"), true);
  assert.equal(app.run("state.currentUser"), null);
  assert.equal(app.run("els.userId.value + els.threadId.value + els.prompt.value + els.agentPrompt.value"), "");
  assert.equal(app.run("state.todos.length"), 0);
  assert.equal(app.run("els.loginError.textContent"), "登录已过期或账号已停用，请重新登录。");
  assert.equal(app.run("els.workspace.inert"), true);
});

test("logout calls the backend and returns to the locked login form", async () => {
  const app = createApp();
  app.run(`
    let logoutCall;
    fetch = async (url, options) => {logoutCall = {url, options}; return {ok: true, status: 204};};
  `);
  await app.run("logout()");
  assert.equal(app.run("logoutCall.url"), "/v1/auth/logout");
  assert.equal(app.run("logoutCall.options.method"), "POST");
  assert.equal(app.run("state.currentUser"), null);
  assert.equal(app.run("els.logoutButton.hidden"), true);
  assert.equal(app.run("els.send.disabled"), true);
  assert.equal(app.run("els.loginOverlay.classList.contains('hidden')"), false);
});

test("failed logout stays authenticated and allows retry", async () => {
  const app = createApp();
  app.run('fetch = async () => {throw new Error("网络异常")};');
  await app.run("logout()");
  assert.equal(app.run("state.currentUser.user_id"), "test-user");
  assert.equal(app.run("els.logoutButton.disabled"), false);
  assert.equal(app.run("els.send.disabled"), false);
  assert.equal(app.run("messages[0].dataset.markdown"), "退出失败：网络异常");
});

test("late requests from the previous session cannot show data or log out the new user", async () => {
  for (const status of [200, 401]) {
    const app = createApp();
    app.run(`
      const threadRenders = [];
      renderThreads = (threads) => threadRenders.push(threads);
      let resolveOldRequest;
      fetch = () => new Promise(resolve => {resolveOldRequest = resolve});
    `);
    const pending = app.run("loadThreads()");
    app.run(`
      requireLogin();
      fetch = async (url) => ({ok: true, status: 200, text: async () => JSON.stringify({threads: [{thread_id: "bob-thread"}]})});
    `);
    await app.run('enterWorkspace({user_id: "bob-id", username: "bob", access_level: 1})');
    app.context.lateStatus = status;
    app.run('resolveOldRequest({status: lateStatus, ok: lateStatus === 200, text: async () => JSON.stringify({threads: [{thread_id: "alice-private-thread"}]})})');
    await pending;
    assert.equal(app.run("state.currentUser.user_id"), "bob-id");
    assert.equal(app.run("JSON.stringify(threadRenders).includes('alice-private-thread')"), false);
    assert.equal(app.run("threadRenders.at(-1)[0].thread_id"), "bob-thread");
  }
});

test("late response bodies are discarded after a session changes", async () => {
  const app = createApp();
  app.run(`
    let resolveBody;
    fetch = async () => ({ok: true, status: 200, text: () => new Promise(resolve => {resolveBody = resolve})});
  `);
  const res = await app.run('apiFetch("/v1/threads/mine")');
  app.context.pendingResponse = res;
  const pending = app.run("readJson(pendingResponse)");
  // Attach a rejection handler before resolving the body in the next JS turn.
  const rejected = assert.rejects(pending, { name: "AbortError" });
  app.run('requireLogin(); resolveBody(JSON.stringify({threads: [{thread_id: "private"}]}))');
  await rejected;
});

test("history queries omit user_id and use the authenticated cookie", async () => {
  const app = createApp();
  app.run('fetch = async (url, options) => {historyCall = {url, options}; return {ok: true, status: 200, text: async () => "{}"}}');
  await app.run('openThread({thread_id: "my-thread"})');
  assert.equal(app.run("historyCall.url"), "/v1/threads/my-thread/messages?page=1&page_size=100");
  assert.equal(app.run("historyCall.options.credentials"), "same-origin");
});

test("account management entry is visible only for administrators", async () => {
  const app = createApp();
  app.run('renderCurrentAccount()');
  assert.equal(app.run('els.adminButton.hidden'), true);
  app.run('let adminCalls = 0; fetch = async () => {adminCalls += 1};');
  await app.run('openAccountManagement()');
  assert.equal(app.run('adminCalls'), 0);
  app.run('state.currentUser.is_admin = true; renderCurrentAccount()');
  assert.equal(app.run('els.adminButton.hidden'), false);
  assert.equal(app.run('els.currentUserLevel.textContent'), 'test · 管理员');
});

test("administrator can create an account and refresh its list", async () => {
  const app = createApp();
  app.run(`
    state.currentUser.is_admin = true;
    const accountCalls = [];
    fetch = async (url, options) => {
      accountCalls.push({url, options});
      const data = options.method === 'POST' ? {user_id: 'new-id', username: 'new-account', access_level: 2, is_admin: false, is_active: true} : {users: [], total: 0};
      return {status: options.method === 'POST' ? 201 : 200, ok: true, text: async () => JSON.stringify(data)};
    };
  `);
  await app.run('openAccountManagement()');
  assert.equal(app.run('els.adminPanel.hidden'), false);
  assert.equal(app.run('els.workspace.inert'), true);
  app.run('els.accountUsername.value = " new-account "; els.accountPassword.value = "0000"; els.accountLevel.value = "2"');
  await app.run('saveAccount({preventDefault(){}})');
  const post = app.run('accountCalls.find(c => c.options.method === "POST")');
  assert.equal(post.url, '/v1/admin/users');
  assert.deepEqual(JSON.parse(post.options.body), {username: 'new-account', password: '0000', access_level: 2, is_admin: false, is_active: true});
  assert.equal(app.run('els.accountPassword.value'), '');
  assert.equal(app.run('els.adminStatus.textContent'), '账号已创建。');
  assert.equal(app.run('state.adminSaving'), false);
});

test("editing an account preserves its ID and omits an unchanged password", async () => {
  const app = createApp();
  app.run(`
    state.currentUser.is_admin = true;
    state.adminOpen = true;
    editAccount({user_id: 'old-id', username: 'old-name', access_level: 1, is_admin: false, is_active: true});
    const editCalls = [];
    fetch = async (url, options) => {
      editCalls.push({url, options});
      return {status: 200, ok: true, text: async () => JSON.stringify(options.method === 'PATCH' ? {user_id: 'old-id', username: 'new-name', access_level: 3, is_admin: false, is_active: true} : {users: [], total: 0})};
    };
    els.accountUsername.value = 'new-name'; els.accountLevel.value = '3';
  `);
  assert.equal(app.run('els.accountPassword.required'), false);
  await app.run('saveAccount({preventDefault(){}})');
  const patch = app.run('editCalls.find(c => c.options.method === "PATCH")');
  assert.equal(patch.url, '/v1/admin/users/old-id');
  assert.equal(Object.hasOwn(JSON.parse(patch.options.body), 'password'), false);
  assert.equal(Object.hasOwn(JSON.parse(patch.options.body), 'user_id'), false);
});

test("changing own password returns to login and clears administrator data", async () => {
  const app = createApp();
  app.run(`
    state.currentUser.is_admin = true; state.adminOpen = true;
    editAccount({...state.currentUser, is_active: true});
    els.accountPassword.value = 'new-password';
    fetch = async () => ({status: 200, ok: true, text: async () => JSON.stringify({...state.currentUser, is_active: true})});
  `);
  assert.equal(app.run('els.accountAdmin.disabled'), true);
  assert.equal(app.run('els.accountActive.disabled'), true);
  await app.run('saveAccount({preventDefault(){}})');
  assert.equal(app.run('state.currentUser'), null);
  assert.equal(app.run('els.adminPanel.hidden'), true);
  assert.equal(app.run('els.adminButton.hidden'), true);
  assert.equal(app.run('els.accountPassword.value'), '');
  assert.equal(app.run('els.loginError.textContent'), '密码已更新，请使用新密码重新登录。');
});

test("closing or losing the administrator session discards pending account lists", async () => {
  const app = createApp();
  app.run(`
    state.currentUser.is_admin = true;
    let resolveAccountList;
    fetch = () => new Promise(resolve => {resolveAccountList = resolve});
  `);
  const pending = app.run('openAccountManagement()');
  app.run('requireLogin(); resolveAccountList({status: 200, ok: true, text: async () => JSON.stringify({users: [{username: "private"}], total: 1})})');
  await pending;
  assert.equal(app.run('state.accountUsers.length'), 0);
  assert.equal(app.run('els.adminUsers.children.length'), 0);
  assert.equal(app.run('els.adminPanel.hidden'), true);
});

test("revoked administrator permission closes management without logging out the user", async () => {
  const app = createApp();
  app.run(`
    state.currentUser.is_admin = true;
    fetch = async () => ({status: 403, ok: false, text: async () => JSON.stringify({error: {code: 'ACCESS_DENIED', message: '需要管理员权限'}})});
  `);
  await app.run('openAccountManagement()');
  assert.equal(app.run('state.currentUser.user_id'), 'test-user');
  assert.equal(app.run('state.currentUser.is_admin'), false);
  assert.equal(app.run('els.adminPanel.hidden'), true);
  assert.equal(app.run('els.adminButton.hidden'), true);
  assert.equal(app.run('els.workspace.inert'), false);
});
