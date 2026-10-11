// Scanner station recovery, using the real scripts.
const test = require('node:test');
const assert = require('node:assert/strict');
const {response, boot} = require('./ui_harness.cjs');

function station(result) {
  const ui = boot({'/scans':()=>result});
  const scan = {code:'fictional-badge', direction:'in', request_id:'00000000-0000-4000-8000-000000000001'};
  ui.stored.set('pending:front-1', JSON.stringify(scan));
  ui.read("role='station';stationName='front-1';pending=" + JSON.stringify(scan));
  return {ui, scan};
}

test('a scan rejected because the station was signed out is not resurrected after sign-in', async()=>{
  const {ui} = station(response({detail:'Station sign-in required.'}, 401));
  await ui.context.sendScan();
  assert.equal(ui.stored.has('pending:front-1'), false);
  assert.equal(ui.read('connected'), false);
  assert.match(ui.element('login-error').textContent, /signed out, so the last scan was not recorded/);
});

test('an unconfirmed scan after a server error is kept for a safe retry', async()=>{
  const {ui, scan} = station(response({detail:'Database temporarily unavailable.'}, 503));
  await ui.context.sendScan();
  assert.equal(ui.stored.get('pending:front-1'), JSON.stringify(scan));
  assert.equal(ui.element('retry').hidden, false);
});
