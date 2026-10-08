const {test}=require('node:test');
const assert=require('node:assert/strict');
const config=require('../app.config.js');
test('Role variants have distinct native identities and the shared app retains its identity',()=>{
  const original=process.env.EXPO_PUBLIC_APP_WORKSPACE;
  try {
    delete process.env.EXPO_PUBLIC_APP_WORKSPACE;
    assert.equal(config().android.package,'com.zwelithini.mediflow');
    const identities=new Set();
    for(const role of ['patient','doctor','reception']){
      process.env.EXPO_PUBLIC_APP_WORKSPACE=role;const value=config();
      assert.equal(value.android.package,`com.zwelithini.mediflow.${role}`);
      assert.equal(value.ios.bundleIdentifier,`com.zwelithini.mediflow.${role}`);
      identities.add(value.android.package);
    }
    assert.equal(identities.size,3);
    process.env.EXPO_PUBLIC_APP_WORKSPACE='unknown';assert.throws(config);
  } finally {if(original===undefined)delete process.env.EXPO_PUBLIC_APP_WORKSPACE;else process.env.EXPO_PUBLIC_APP_WORKSPACE=original;}
});
