const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');

const source = fs.readFileSync(path.resolve(__dirname, '../js/spatial_stats.js'), 'utf8');
const i18n = fs.readFileSync(path.resolve(__dirname, '../js/i18n.js'), 'utf8');
const messagesSource = i18n.slice(i18n.indexOf('var messages = {'), i18n.indexOf('\n  };', i18n.indexOf('var messages = {')));
const messageKeys = new Set(Array.from(messagesSource.matchAll(/^\s*'([^']+)'\s*:/gm), match => match[1]));

test('spatial statistics panel labels and dynamic validation text have English messages', () => {
  const markup = source.slice(source.indexOf('var PANEL_HTML ='), source.indexOf('function tr('));
  const visibleChineseLines = markup.split(/\r?\n/).filter(line => /[\u3400-\u9fff]/.test(line));

  for (const line of visibleChineseLines) {
    assert.ok(line.includes('data-i18n') && line.includes('spatial-stats.'), `Missing localization key: ${line.trim()}`);
  }

  for (const [, key] of source.matchAll(/tr\('(spatial-stats\.[^']+)'/g)) {
    assert.ok(messageKeys.has(key), `Missing English message: ${key}`);
  }
});
