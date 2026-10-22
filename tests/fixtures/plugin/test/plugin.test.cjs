const test = require('node:test');
const assert = require('node:assert/strict');
test('plugin behavior', () => assert.equal(require('../plugin.cjs').double(4), 8));
