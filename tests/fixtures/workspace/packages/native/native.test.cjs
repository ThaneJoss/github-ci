const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
test('member without a script runs native tests from its package', () => {
  assert.equal(path.basename(process.cwd()), 'native');
  assert.equal(6 * 7, 42);
});
