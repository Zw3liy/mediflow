const {test}=require('node:test');
const assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const queryString=require('query-string');

test('Router query decoding remains compatible with the patched CommonJS decoder',()=>{
  assert.deepEqual({...queryString.parse('name=Dr%20Goodwill&note=caf%C3%A9')},{name:'Dr Goodwill',note:'café'});
  assert.equal(queryString.parse('note=%25E0%25A4').note,'%E0%A4');
});

test('Malformed UTF-8 query input completes without exponential fallback',()=>{
  execFileSync(process.execPath,['-e',"require('query-string').parse('note='+('%E0%A4'.repeat(5000)))"],
    {cwd:process.cwd(),timeout:2000,stdio:'pipe'});
});
