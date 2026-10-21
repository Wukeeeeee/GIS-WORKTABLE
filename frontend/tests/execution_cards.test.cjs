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

function createCards() {
  const document = { createElement: tag => new Element(tag) };
  const window = { GIS: {} };
  const sourcePath = path.resolve(__dirname, '../js/execution_cards.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), {
    window, document, Map, Set, String, JSON, Math, RegExp,
  }, { filename: sourcePath });
  const container = new Element('div');
  return { cards: window.GIS.executionCards.create(container), container };
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
