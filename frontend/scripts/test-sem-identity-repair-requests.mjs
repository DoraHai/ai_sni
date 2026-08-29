import assert from 'node:assert/strict'

import { createRequestController } from '../src/views/settings/semIdentityRepairRequests.js'

const requests = createRequestController()
const first = requests.start()
assert.equal(first.signal.aborted, false)

const second = requests.start()
assert.equal(first.signal.aborted, true, 'a newer request must abort the stale request')
assert.equal(second.signal.aborted, false)
assert.equal(requests.finish(first), false, 'a stale request must not clear the active controller')

requests.cancel()
assert.equal(second.signal.aborted, true, 'closing the dialog must abort the active request')

const third = requests.start()
assert.equal(requests.finish(third), true)
assert.equal(third.signal.aborted, false, 'a completed current request must not be aborted')

console.log('SEM identity repair request cancellation test passed')
