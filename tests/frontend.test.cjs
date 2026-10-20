// Run with: node --test tests/frontend.test.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../app/static/app.js"), "utf8");

function createApp({ realScroll = false } = {}) {
  const frames = new Map();
  let nextFrame = 0;
  const element = {
    value: "", style: {},
    classList: { toggle() {}, add() {}, remove() {} },
    addEventListener() {}, querySelector() { return null; },
    querySelectorAll() { return []; }, closest() { return this; },
    children: [],
    append(...items) { this.children.push(...items); },
    appendChild(item) { this.children.push(item); return item; },
    replaceChildren(...items) { this.children = items; },
  };
  const makeElement = () => ({ ...element, children: [] });
  const context = vm.createContext({
    document: { querySelector: makeElement, createElement: makeElement },
    // Startup requests are unrelated to these deterministic rendering tests.
    fetch: () => new Promise(() => {}),
    requestAnimationFrame(callback) { frames.set(++nextFrame, callback); return nextFrame; },
    cancelAnimationFrame(id) { frames.delete(id); },
  });
  vm.runInContext(source, context);
  vm.runInContext(`
    const messages = [];
    let renderCount = 0;
    appendMessage = (role, text) => {
      const content = {
        html: "",
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
  assert.equal(app.run('els.planSummary.textContent'), '已完成 1/3');
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

test("starting a run shows planning status before the first plan arrives", () => {
  const app = createApp();
  app.run('handleSseEvent(\'event: run.started\\ndata: {}\')');
  assert.equal(app.run('els.taskPlan.hidden'), false);
  assert.equal(app.run('els.planSummary.textContent'), '正在生成计划…');
  assert.equal(app.run('els.planList.children.length'), 0);
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
