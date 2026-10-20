const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

function makeElement() {
  const children = [];
  const listeners = {};
  const classes = new Set();
  const element = {
    children, listeners, dataset: {}, style: { setProperty() {}, removeProperty() {} },
    classList: {
      add(...names) { names.forEach(name => classes.add(name)); },
      remove(...names) { names.forEach(name => classes.delete(name)); },
      toggle(name, force) {
        if (force === undefined) force = !classes.has(name);
        force ? classes.add(name) : classes.delete(name);
        return force;
      },
      contains(name) { return classes.has(name); },
    },
    addEventListener(name, callback) { (listeners[name] ||= []).push(callback); },
    appendChild(child) { children.push(child); child.parentNode = this; return child; },
    insertBefore(child) { if (!child) return null; children.push(child); child.parentNode = this; return child; },
    querySelector() { return makeElement(); },
    querySelectorAll() { return []; },
    setAttribute() {}, removeAttribute() {}, replaceChildren() {}, replaceWith() {},
    cloneNode() { return makeElement(); },
  };
  return element;
}

function bootWorkspace(saved, projects = []) {
  const elements = new Map();
  const documentListeners = {};
  const geoSourceCalls = { shows: [], searches: [] };
  const app = makeElement();
  const body = makeElement();
  body.clientWidth = 1200;
  const chat = makeElement();
  chat.hidden = true;
  const layerPanel = makeElement();
  const title = makeElement();
  const close = makeElement();
  const layerTab = makeElement();
  const taskPanel = makeElement();
  const taskRunButton = makeElement();
  const taskTabButton = makeElement();
  const taskInput = makeElement();
  const taskSelect = makeElement();
  const taskCancelButton = makeElement();
  const recentProjects = makeElement();
  let taskOutput = null;
  taskPanel.attributes = {};
  taskPanel.setAttribute = function(name, value) { this.attributes[name] = value; };
  taskPanel.querySelector = selector => selector === '.workspace-tool-feedback' ? taskOutput : null;
  taskPanel.querySelectorAll = selector => selector === '.spatial-tab' ? [taskTabButton]
    : [taskRunButton, taskTabButton, taskInput, taskSelect];
  taskPanel.insertBefore = function(output) {
    taskOutput = output;
    output.querySelector = selector => selector === '[data-action="cancel"]' ? taskCancelButton : null;
    return output;
  };
  const panes = ['home', 'browser', 'layers', 'tools'].map(name => {
    const pane = makeElement();
    pane.dataset.dockPane = name;
    pane.hidden = true;
    return pane;
  });
  const tabs = ['home', 'browser', 'layers', 'tools'].map(name => {
    const tab = makeElement();
    tab.dataset.dockTab = name;
    return tab;
  });
  elements.set('app', app);
  elements.set('mapLayerPanel', layerPanel);
  elements.set('workspaceDockTitle', title);
  elements.set('workspaceDockClose', close);
  elements.set('toggleLayerPanel', layerTab);
  elements.set('testPanel', taskPanel);
  elements.set('workspaceDataSearch', makeElement());
  elements.set('geosourceKeyword', makeElement());
  elements.set('chatInput', makeElement());
  elements.set('workspaceRecentProjectsList', recentProjects);
  let dock = null;
  const document = {
    readyState: 'complete',
    body: makeElement(), documentElement: makeElement(),
    querySelector(selector) {
      if (selector === '.app-body') return body;
      if (selector === '.chat-panel') return chat;
      return null;
    },
    querySelectorAll(selector) {
      if (selector === '[data-dock-tab]') return tabs;
      if (selector === '[data-dock-pane]') return panes;
      if (selector === '[data-workspace-action="ai"]') return [];
      return [];
    },
    getElementById(id) { return elements.get(id) || null; },
    createElement(tag) {
      const element = makeElement();
      element.querySelector = selector => selector.includes('data-dock-pane="layers"')
        ? panes.find(pane => pane.dataset.dockPane === 'layers') : makeElement();
      if (tag === 'aside') dock = element;
      return element;
    },
    addEventListener(name, callback) { documentListeners[name] = callback; },
  };
  body.querySelector = selector => selector === '.main-content' ? makeElement() : makeElement();
  body.insertBefore = child => { if (child.className === 'workspace-dock') dock.hidden = child.hidden; return child; };
  const localStorage = new Map(Object.entries(saved));
  const storage = {
    getItem(key) { return localStorage.has(key) ? localStorage.get(key) : null; },
    setItem(key, value) { localStorage.set(key, String(value)); },
  };
  const window = { GIS: {
    api: { listProjects() { return Promise.resolve({ projects }); } },
    map: { invalidateSize() {} },
    renderers: { getViewer() { return null; } },
    geosource: {
      closeWorldMap() {},
      show(skipInitialSearch) {
        geoSourceCalls.shows.push(skipInitialSearch);
        if (!skipInitialSearch && geoSourceCalls.searches.length === 0) this.doSearch(1);
      },
      doSearch(page) { geoSourceCalls.searches.push(page); },
    },
  }, innerWidth: 1200, addEventListener() {} };
  const context = { window, document, localStorage: storage, requestAnimationFrame(callback) { callback(); }, setInterval() { return 1; }, clearInterval() {}, console, Set, Map, Math, Number, String, Array, Object, Promise, Date };
  const sourcePath = path.resolve(__dirname, '../js/workspace.js');
  vm.runInNewContext(fs.readFileSync(sourcePath, 'utf8'), context, { filename: sourcePath });
  return { workspace: window.GIS.workspace, dock, localStorage: storage, panes, tabs,
    taskPanel, taskRunButton, taskTabButton, taskInput, taskSelect, taskCancelButton,
    documentListeners, geoSourceCalls, elements, recentProjects,
    get taskOutput() { return taskOutput; } };
}

test('workspace restores a dock closed before reload without overwriting its saved state', () => {
  const harness = bootWorkspace({ gis_workspace_active_tab: 'layers', gis_workspace_dock_closed: 'true' });
  assert.equal(harness.dock.hidden, true);
  assert.equal(harness.localStorage.getItem('gis_workspace_dock_closed'), 'true');
  assert.equal(harness.localStorage.getItem('gis_workspace_active_tab'), 'layers');

  harness.workspace.setTab('layers');
  assert.equal(harness.dock.hidden, false);
  assert.equal(harness.localStorage.getItem('gis_workspace_dock_closed'), 'false');
});

test('cancel waiting keeps the operation locked until its request reaches a terminal result', () => {
  const harness = bootWorkspace({});
  harness.workspace.toolPending('testPanel', harness.taskRunButton);
  assert.equal(harness.taskRunButton.disabled, true);
  assert.equal(harness.taskTabButton.disabled, true);
  assert.equal(harness.taskInput.disabled, true);
  assert.equal(harness.taskSelect.disabled, true);

  harness.taskCancelButton.onclick();
  assert.equal(harness.taskOutput.dataset.state, 'cancelled');
  assert.equal(harness.taskRunButton.disabled, true);
  assert.equal(harness.taskTabButton.disabled, false);
  assert.equal(harness.taskInput.disabled, true);
  assert.equal(harness.taskSelect.disabled, true);
  assert.equal(harness.taskPanel.attributes['aria-busy'], 'true');

  harness.workspace.toolFeedback('testPanel', { ok: true, response: '完成' });
  assert.equal(harness.taskOutput.dataset.state, 'complete');
  assert.equal(harness.taskRunButton.disabled, false);
  assert.equal(harness.taskInput.disabled, false);
  assert.equal(harness.taskSelect.disabled, false);
  assert.equal(harness.taskPanel.attributes['aria-busy'], 'false');
});

test('workspace data search opens GeoSource without issuing a duplicate empty-state search', () => {
  const harness = bootWorkspace({});
  harness.elements.get('workspaceDataSearch').value = 'population';
  const target = {
    closest(selector) {
      return selector === '[data-workspace-action]'
        ? { dataset: { workspaceAction: 'search' } }
        : null;
    },
  };

  harness.documentListeners.click({ target });

  assert.deepEqual(harness.geoSourceCalls.shows, [true]);
  assert.deepEqual(harness.geoSourceCalls.searches, [1]);
  assert.equal(harness.elements.get('geosourceKeyword').value, 'population');
});

test('workspace recent-project cards escape untrusted project metadata', async () => {
  const harness = bootWorkspace({}, [{
    id: 'project" onclick="alert(1)',
    name: '工程 <img src=x onerror=alert(3)>',
    updatedAt: '<img onerror=1>ignored',
    layerCount: '<svg onload=alert(4)>',
  }]);
  await new Promise(resolve => setImmediate(resolve));

  const markup = harness.recentProjects.innerHTML;
  assert.ok(markup.includes('data-project-id="project&quot; onclick=&quot;alert(1)"'), markup);
  assert.ok(markup.includes('工程 &lt;img src=x onerror=alert(3)&gt;'), markup);
  assert.ok(markup.includes('&lt;img onerror=1&gt;'), markup);
  assert.ok(markup.includes('&lt;svg onload=alert(4)&gt;'), markup);
  assert.equal(markup.includes('<img src=x'), false);
  assert.equal(markup.includes('<svg onload='), false);
});

test('workspace tool feedback renders tool results and artifact names as text', () => {
  const harness = bootWorkspace({});
  harness.workspace.toolFeedback('testPanel', {
    ok: true,
    response: '结果：<img src=x onerror=alert(1)>',
    layers: [{ name: '<svg onload=alert(2)>' }],
  });

  assert.ok(harness.taskOutput.innerHTML.includes('结果：&lt;img src=x onerror=alert(1)&gt;'), harness.taskOutput.innerHTML);
  assert.ok(harness.taskOutput.innerHTML.includes('&lt;svg onload=alert(2)&gt;'), harness.taskOutput.innerHTML);
  assert.equal(harness.taskOutput.innerHTML.includes('<img src=x'), false);
  assert.equal(harness.taskOutput.innerHTML.includes('<svg onload='), false);
});
