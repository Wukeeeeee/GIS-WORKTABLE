const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.className = '';
    this.hidden = false;
    this.textContent = '';
    this.classList = { add: name => { this.className += ' ' + name; } };
  }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute(name, value) { this.attributes[name] = value; }
}

function createCards(gis = {}, extras = {}) {
  const document = { createElement: tag => new Element(tag) };
  const window = { GIS: gis, ...extras };
  const sourcePath = path.resolve(__dirname, '../js/execution_cards.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Map, Set, String, JSON, Math, RegExp,
  }, { filename: sourcePath });
  const container = new Element('div');
  return { cards: window.GIS.executionCards.create(container), container, window };
}

test('Scrapling page reads count as completed reads in execution progress', () => {
  const { cards, container } = createCards();
  cards.handle({ type: 'tool_start', step_id: 'web-step', step_label: '搜索纽约天气',
    name: 'fetch_webpage_scrapling', tool_call_id: 'read-1', input: { url: 'https://weather.example/' } });
  cards.handle({ type: 'tool_end', step_id: 'web-step', name: 'fetch_webpage_scrapling',
    tool_call_id: 'read-1', output: '纽约今日多云。' });

  const card = container.children[0].children[0];
  assert.match(card.children[1].textContent, /已读取1个网页/);
});

test('running cards show an indeterminate progress cue and a distinct status icon', () => {
  const { cards, container } = createCards();
  cards.handle({ type: 'tool_start', step_id: 'running-step', name: 'execute_python', tool_call_id: 'call-1' });

  const card = container.children[0].children[0];
  const badge = card.children[0].children[2];
  assert.match(card.className, /ai-step-running/);
  assert.equal(badge.children[1].textContent, '执行中');
  assert.match(badge.children[0].innerHTML, /stroke-dasharray/);
  assert.equal(card.children[2].hidden, false);
});

test('partial tool results finish with the warning status and stop the progress cue', () => {
  const { cards, container } = createCards();
  cards.handle({ type: 'tool_start', step_id: 'partial-step', name: 'execute_python', tool_call_id: 'call-2' });
  cards.handle({ type: 'tool_end', step_id: 'partial-step', name: 'execute_python', tool_call_id: 'call-2',
    output: JSON.stringify({ success: true, partial: true, warnings: ['跳过1个无效要素'] }) });

  const card = container.children[0].children[0];
  const badge = card.children[0].children[2];
  assert.match(card.className, /ai-step-warning/);
  assert.match(badge.children[1].textContent, /部分完成/);
  assert.match(badge.children[0].innerHTML, /M10\.3/);
  assert.equal(card.children[2].hidden, true);
});

test('execution failure, waiting, and cancellation each expose a matching status', () => {
  const { cards, container } = createCards();
  cards.handle({ type: 'tool_start', step_id: 'failed-step', name: 'execute_python', tool_call_id: 'call-3' });
  cards.handle({ type: 'tool_end', step_id: 'failed-step', name: 'execute_python', tool_call_id: 'call-3', is_error: true, output: '执行失败' });
  cards.handle({ type: 'waiting_choice', step_id: 'waiting-step', step_label: '选择图层' });
  const waitingCard = container.children[0].children[1];
  assert.match(waitingCard.className, /ai-step-waiting/);
  assert.equal(waitingCard.children[0].children[2].children[1].textContent, '等待选择');
  cards.handle({ type: 'tool_start', step_id: 'cancelled-step', name: 'execute_python', tool_call_id: 'call-4' });
  cards.finish('cancelled', '用户已取消');

  const steps = container.children[0].children;
  assert.match(steps[0].className, /ai-step-failed/);
  assert.equal(steps[0].children[0].children[2].children[1].textContent, '步骤失败');
  assert.match(steps[2].className, /ai-step-cancelled/);
  assert.equal(steps[2].children[0].children[2].children[1].textContent, '已取消');
});

function start(cards, id, step = 'shared', name = 'search_web', extra = {}) {
  cards.handle({ type: 'tool_start', tool_call_id: id, step_id: step, name, input: {}, ...extra });
}
function end(cards, id, step = 'shared', name = 'search_web', extra = {}) {
  cards.handle({ type: 'tool_end', tool_call_id: id, step_id: step, name, output: '处理完成', ...extra });
}
function row(h, index = 0) { return h.container.children[0].children[index]; }

test('a later unrelated tool cannot erase an earlier failed tool', () => {
  const h = createCards();
  start(h.cards, 'a');
  end(h.cards, 'a', 'shared', 'search_web', { is_error: true, output: '网络失败' });
  start(h.cards, 'b', 'shared', 'fetch_webpage');
  end(h.cards, 'b', 'shared', 'fetch_webpage');
  assert.match(row(h).className, /ai-step-failed/);
});

test('a successful retry resolves only the failed tool it retried', () => {
  const h = createCards();
  start(h.cards, 'a');
  end(h.cards, 'a', 'shared', 'search_web', { is_error: true });
  start(h.cards, 'retry');
  assert.equal(row(h).children[0].children[2].children[1].textContent, '正在重试');
  end(h.cards, 'retry');
  assert.match(row(h).className, /ai-step-success/);
  assert.match(row(h).children[3].children[1].children[0].className, /ai-tool-failed/);
});

test('parallel success does not resolve another call failure', () => {
  const h = createCards();
  start(h.cards, 'a'); start(h.cards, 'b');
  end(h.cards, 'a', 'shared', 'search_web', { is_error: true });
  start(h.cards, 'c');
  end(h.cards, 'b'); end(h.cards, 'c');
  assert.match(row(h).className, /ai-step-failed/);
});

test('duplicate starts and ends are idempotent even after completion', () => {
  const h = createCards();
  start(h.cards, 'a'); start(h.cards, 'a');
  end(h.cards, 'a'); end(h.cards, 'a'); start(h.cards, 'a');
  assert.equal(row(h).children[3].children[1].children.length, 1);
  assert.match(row(h).className, /ai-step-success/);
  assert.match(row(h).children[1].textContent, /已搜索1次/);
});

test('an end event without its start still exposes the result and deduplicates repeats', () => {
  const h = createCards();
  end(h.cards, 'orphan', 'shared', 'search_web', { is_error: true, output: '连接失败' });
  end(h.cards, 'orphan', 'shared', 'search_web', { is_error: true, output: '连接失败' });
  assert.match(row(h).className, /ai-step-failed/);
  assert.equal(row(h).children[3].children[1].children.length, 1);
});

test('legacy call IDs stay unique after an earlier call ends', () => {
  const h = createCards();
  start(h.cards, undefined, 'a', 'search_web');
  start(h.cards, undefined, 'b', 'fetch_webpage');
  end(h.cards, undefined, 'a', 'search_web');
  start(h.cards, undefined, 'c', 'execute_python');
  end(h.cards, undefined, 'b', 'fetch_webpage');
  end(h.cards, undefined, 'c', 'execute_python');
  for (const card of h.container.children[0].children) assert.match(card.className, /ai-step-success/);
});

test('a legacy end event with a step ID cannot finish a different step', () => {
  const h = createCards();
  start(h.cards, undefined, 'a'); start(h.cards, undefined, 'b');
  end(h.cards, undefined, 'b');
  assert.match(row(h, 0).className, /ai-step-running/);
  assert.match(row(h, 1).className, /ai-step-success/);
});

test('finishing without a tool result cannot claim success', () => {
  const h = createCards();
  start(h.cards, 'a');
  h.cards.finish('success');
  assert.match(row(h).className, /ai-step-warning/);
  assert.match(row(h).children[1].textContent, /未收到全部工具结果/);
});

test('late events cannot rewrite a canceled task card', () => {
  const h = createCards();
  start(h.cards, 'a'); h.cards.finish('cancelled'); end(h.cards, 'a');
  start(h.cards, 'late', 'late');
  assert.match(row(h).className, /ai-step-cancelled/);
  assert.equal(h.container.children[0].children.length, 1);
});

test('warning metadata is retained even when the output is empty', () => {
  const h = createCards();
  start(h.cards, 'a'); end(h.cards, 'a', 'shared', 'search_web', { output: '', has_warning: true });
  assert.match(row(h).className, /ai-step-warning/);
});

test('a deferred fit retries after map data arrives and clears only its map error', () => {
  let ready = false;
  let fits = 0;
  const h = createCards({ layers: { getLayers: () => [{ _rawName: 'demo' }] },
    map: { fitLayer() { fits++; return ready; } } });
  start(h.cards, 'map', 'shared', 'focus_map', { map_ops_pending: 1 });
  end(h.cards, 'map', 'shared', 'focus_map', { has_warning: true });
  const evt = { type: 'layer_ops_delta', step_id: 'shared', layer_ops: [
    { action: 'fit', name: 'demo', _stream_id: 'fit-1' },
  ] };
  h.cards.handle(evt);
  assert.equal(h.cards.hasAppliedMapOp('fit-1'), false);
  assert.match(row(h).className, /ai-step-running/);
  ready = true;
  h.cards.handle(evt); h.cards.handle(evt); h.cards.finish('success');
  assert.equal(h.cards.hasAppliedMapOp('fit-1'), true);
  assert.equal(fits, 2);
  assert.match(row(h).className, /ai-step-warning/);
});

test('map completion does not overwrite an earlier tool failure', () => {
  const h = createCards({ map: { setView() { return true; } } });
  start(h.cards, 'a'); end(h.cards, 'a', 'shared', 'search_web', { is_error: true });
  h.cards.handle({ type: 'layer_ops_delta', step_id: 'shared', layer_ops: [
    { action: 'center', center: [0, 0], _stream_id: 'center-1' },
  ] });
  assert.match(row(h).className, /ai-step-failed/);
});

test('zoom zero is preserved and map readiness must be confirmed', () => {
  let zoom;
  const h = createCards({ map: { setView(center, value) { zoom = value; return false; } } });
  start(h.cards, 'map', 'shared', 'focus_map', { map_ops_pending: 1 });
  end(h.cards, 'map', 'shared', 'focus_map');
  h.cards.handle({ type: 'layer_ops_delta', step_id: 'shared', layer_ops: [
    { action: 'center', center: [0, 0], zoom: 0, _stream_id: 'center-1' },
  ] });
  h.cards.finish('success');
  assert.equal(zoom, 0);
  assert.equal(h.cards.hasAppliedMapOp('center-1'), false);
  assert.match(row(h).className, /ai-step-failed/);
});

test('invalid map coordinates are rejected before touching the map', () => {
  let views = 0;
  const h = createCards({ map: { setView() { views++; return true; } } });
  for (const center of [[NaN, 0], [181, 0], [0, 91], ['bad', 0]]) {
    h.cards.handle({ type: 'layer_ops_delta', step_id: 'shared', layer_ops: [
      { action: 'center', center, _stream_id: 'center-' + views },
    ] });
  }
  assert.equal(views, 0);
  assert.match(row(h).className, /ai-step-failed/);
});

test('null and scalar JSON arguments do not break the stream UI', () => {
  const h = createCards();
  for (const input of ['null', 'false', '123', '[]']) {
    assert.doesNotThrow(() => start(h.cards, input, input, 'amap_geocode', { input }));
  }
  assert.equal(h.container.children[0].children.length, 4);
});

test('empty or malformed map deltas create no phantom steps', () => {
  const h = createCards();
  for (const layer_ops of [null, {}, []]) h.cards.handle({ type: 'layer_ops_delta', layer_ops });
  assert.equal(h.container.children[0].hidden, true);
});
