const test = require('node:test');
const assert = require('node:assert/strict');
const color = require('../index.cjs');
test('checks dependency behavior', () => assert.equal(color.red('42'), '42'));
