const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');

const html = fs.readFileSync(path.resolve(__dirname, '../index.html'), 'utf8');
const i18n = fs.readFileSync(path.resolve(__dirname, '../js/i18n.js'), 'utf8');
const layers = fs.readFileSync(path.resolve(__dirname, '../js/layers.js'), 'utf8');
const messagesSource = i18n.slice(i18n.indexOf('var messages = {'), i18n.indexOf('\n  };', i18n.indexOf('var messages = {')));
const messageKeys = new Set(Array.from(messagesSource.matchAll(/^\s*'([^']+)'\s*:/gm), match => match[1]));

function menuBlock(menu, nextMenu) {
  const startMarker = `data-menu="${menu}"`;
  const endMarker = `data-menu="${nextMenu}"`;
  const start = html.indexOf(startMarker);
  const end = html.indexOf(endMarker, start + startMarker.length);
  assert.notEqual(start, -1, `Missing ${menu} menu`);
  assert.notEqual(end, -1, `Missing menu boundary after ${menu}`);
  return html.slice(start, end);
}

for (const [menu, nextMenu] of [['tools', 'raster'], ['raster', 'help']]) {
  test(`${menu} menu text is fully localized for English`, () => {
    const block = menuBlock(menu, nextMenu);
    const buttons = Array.from(block.matchAll(/<button\b[^>]*class="[^"]*map-menu-item[^"]*"[^>]*>([\s\S]*?)<\/button>/g));
    assert.ok(buttons.length > 0, `No menu items found in ${menu}`);

    for (const [index, button] of buttons.entries()) {
      const textSpans = Array.from(button[1].matchAll(/<span\b([^>]*)>([\s\S]*?)<\/span>/g))
        .filter(([, , text]) => text.replace(/<[^>]*>/g, '').trim());
      assert.equal(textSpans.length, 1, `${menu} menu item ${index + 1} should have one text label`);
      const [, attrs, text] = textSpans[0];
      const key = attrs.match(/\bdata-i18n="([^"]+)"/);
      assert.ok(key, `${menu} menu label is missing data-i18n: ${text}`);
      assert.ok(messageKeys.has(key[1]), `${menu} menu label has no English message: ${key[1]}`);
    }
  });
}

test('dynamic layer count is localized by the layer renderer, not reset as static copy', () => {
  const match = html.match(/<span\b([^>]*\bid="workspaceLayerCount"[^>]*)>([^<]*)<\/span>/);
  assert.ok(match, 'Missing workspace layer count');
  assert.doesNotMatch(match[1], /\bdata-i18n=/, 'dynamic layer count must not be reset by static translation');
  assert.match(layers, /count\.textContent\s*=\s*GIS\.i18n\s*\?\s*GIS\.i18n\.layerCount\(layerData\.length\)/,
    'layer renderer should format the current count in the active language');
});

test('3D layer load failures have an English message for the visible warning', () => {
  assert.ok(messageKeys.has('map.3d-layer-load-failed'));
  assert.match(i18n, /map\.3d-layer-load-failed': 'Could not display this layer on the 3D globe/);
});
