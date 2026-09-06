import test from 'node:test'
import assert from 'node:assert/strict'
import { buildAccountCredentials as build, credentialCheckMessage } from '../src/utils/geoAccountCredentials.js'
test('webhook uses connector fields and never sends endpoint alias', () => {
  assert.deepEqual(build({auth_type:'webhook',credential_values:{webhook_url:'https://example.com/publish',secret:'s',headers:'{"Authorization":"Bearer t"}'}},'website'), {method:'POST',webhook_url:'https://example.com/publish',secret:'s',headers:{Authorization:'Bearer t'}})
})
test('gateway and native WeChat map credentials to backend contract', () => {
  assert.equal(build({auth_type:'social_api',provider:'gateway',credential_values:{api_url:'https://example.com/publish',access_token:'token'}},'zhihu').access_token,'token')
  const form={auth_type:'social_api',provider:'wechat_mp',credential_values:{app_id:'a',app_secret:'s'}}
  assert.equal(build(form,'wechat').app_secret,'s')
  assert.throws(()=>build(form,'zhihu'))
})
test('edit without replacement omits all credentials and rejects auth mode changes', () => {
  assert.equal(build({id:1,auth_type:'webhook',original_auth_type:'webhook',credential_values:{secret:'ignored'}},'website'),undefined)
  assert.throws(()=>build({id:1,auth_type:'social_api',original_auth_type:'webhook'},'website'))
})
test('replacement is complete, not a destructive partial secret update', () => {
  assert.throws(()=>build({id:1,replace_credentials:true,auth_type:'webhook',credential_values:{secret:'s'}},'website'))
})
test('invalid URLs, required fields, and malformed headers are rejected', () => {
  for(const url of ['http://example.com','https://user:pass@example.com','https://']) assert.throws(()=>build({auth_type:'webhook',credential_values:{webhook_url:url}},'website'))
  for(const headers of ['[]','null','oops','{"a":1}']) assert.throws(()=>build({auth_type:'webhook',credential_values:{webhook_url:'https://example.com',headers}},'website'))
  assert.throws(()=>build({auth_type:'social_api',provider:'gateway',credential_values:{api_url:'https://example.com'}},'zhihu'))
})
test('OAuth requires configuration before authorization, never a guessed token', () => {
  const credential_values={client_id:'a',client_secret:'s',authorize_url:'https://example.com/authorize',token_url:'https://example.com/token',redirect_uri:'https://example.com/callback',api_url:'https://example.com/publish'}
  const result=build({auth_type:'oauth2',credential_values},'zhihu')
  assert.equal(result.provider,'oauth2');assert.equal(result.access_token,undefined)
})
test('configuration checks cannot be described as live connection success', () => {
  assert.match(credentialCheckMessage({ok:true,check_scope:'configuration'}),/尚未验证/)
  assert.match(credentialCheckMessage({ok:true,check_scope:'authorization'}),/授权验证通过/)
  assert.throws(()=>credentialCheckMessage({ok:false}))
})
