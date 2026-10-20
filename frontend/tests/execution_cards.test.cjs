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
