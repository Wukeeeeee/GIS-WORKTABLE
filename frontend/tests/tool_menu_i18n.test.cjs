const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');

const html = fs.readFileSync(path.resolve(__dirname, '../index.html'), 'utf8');
const i18n = fs.readFileSync(path.resolve(__dirname, '../js/i18n.js'), 'utf8');
const layers = fs.readFileSync(path.resolve(__dirname, '../js/layers.js'), 'utf8');
const analysisTools = fs.readFileSync(path.resolve(__dirname, '../js/analysis_tools.js'), 'utf8');
const settings = fs.readFileSync(path.resolve(__dirname, '../js/settings.js'), 'utf8');
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

test('AI provider setup note has an English translation for key and transport guidance', () => {
  assert.match(html, /data-i18n="settings\.ai-provider-note"/);
  assert.ok(messageKeys.has('settings.ai-provider-note'));
  assert.match(i18n, /settings\.ai-provider-note': '[^']*HTTPS[^']*remote WorkTable deployment/);
});

test('AI provider setup hint tells users where to get connection details in both languages', () => {
  assert.ok(messageKeys.has('settings.ai-provider-setup-hint'));
  assert.match(html, /data-i18n="settings\.ai-provider-setup-hint"[^>]*data-i18n-zh="接入模型时，请从服务商获取 API Key、兼容接口地址和模型名/);
  assert.match(i18n, /settings\.ai-provider-setup-hint': '[^']*API key[^']*endpoint URL[^']*model name[^']*from your provider/);
});

test('proxy settings disclose model traffic and private HTTP behavior in English', () => {
  for (const key of ['settings.proxy-desc', 'settings.proxy-info-title', 'settings.proxy-common', 'settings.proxy-private']) {
    assert.ok(messageKeys.has(key), `Missing English proxy message: ${key}`);
    assert.ok(html.includes(`data-i18n="${key}"`), `Missing localized proxy element: ${key}`);
  }
  assert.match(i18n, /settings\.proxy-desc': '[^']*model providers[^']*private model addresses/);
  assert.match(i18n, /settings\.proxy-private': '[^']*API key/);
});

test('GeoSource help explains cross-origin API-key removal in both languages', () => {
  assert.match(i18n, /settings\.geosource-copy': '[^']*auth parameter is removed on cross-origin redirects/);
  assert.match(html, /data-i18n="settings\.geosource-copy"[\s\S]*跨主机跳转时会移除该认证参数/);
});

test('self-configured provider fields have accessible names', () => {
  assert.match(settings, /aria-label="Provider 显示名称"/);
  assert.match(settings, /<label for="' \+ inputId \+ '"/);
  assert.match(settings, /<input id="' \+ inputId \+ '"/);
});

test('provider storage failure has an actionable, localized warning', () => {
  assert.ok(messageKeys.has('settings.provider-storage-warning'));
  assert.match(settings, /syncProviderStorageWarning\(host\)/);
  assert.match(settings, /syncProviderStorageWarning\(document\.getElementById\('providerList'\)\)/);
  assert.match(settings, /data-i18n-zh.*刷新或关闭页面后丢失/);
});

test('analysis launcher labels reference English message keys', () => {
  const keys = Array.from(analysisTools.matchAll(/i18nKey: '([^']+)'/g), match => match[1]);
  assert.equal(keys.length, 20, 'each launcher operation should declare a translation key');
  for (const key of [...keys, 'tool.analysis-tools', 'analysis.group.raster', 'analysis.group.vector',
    'analysis.group.statistics', 'analysis.group.conversion']) {
    assert.ok(messageKeys.has(key), `Missing English message for ${key}`);
  }
  assert.match(analysisTools, /_translate\(GROUP_I18N_KEYS\[group\], group\)/);
  assert.match(analysisTools, /_translate\(o\.i18nKey, o\.label\)/);
});
