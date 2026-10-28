// Scanner station recovery, using the real scripts.
const test = require('node:test');
const assert = require('node:assert/strict');
const {response, deferred, flush, boot} = require('./ui_harness.cjs');

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

for (const stationName of ['front-1', 'front-2']) {
  test(stationName + ' can sign staff in and out without changing its login', async()=>{
    const ui = boot({'/scans':()=>response({name:'Alex Morgan', message:'Recorded', occurred_at:1})});
    await ui.context.connect({role:'station', station:stationName, expires_at:9999999999});
    assert.equal(ui.read('direction'), 'in');
    assert.equal(ui.element('logout').textContent, 'Lock station');
    let focused = 0;
    ui.element('scan-code').focus = ()=>focused++;
    for (const mode of ['in', 'out', 'in']) {
      ui.element('scan-'+mode).onclick();
      assert.equal(ui.element('scan-'+mode).attributes['aria-pressed'], 'true');
      assert.match(ui.element('scan-title').textContent, new RegExp(mode.toUpperCase()));
      ui.element('scan-code').value='fictional-badge';
      ui.element('scan-form').onsubmit({preventDefault(){}});
      await flush();
      assert.equal(ui.sent.filter(r=>r.route==='/scans').at(-1).body.direction, mode);
      assert.equal(ui.read('stationName'), stationName);
      assert.equal(ui.read('direction'), mode);
      assert.equal(ui.element('scan-out').disabled, false);
    }
    assert.ok(focused >= 3);
  });
}

test('switching mode clears an unsubmitted badge and old feedback without sending a scan', async()=>{
  const ui = boot();
  await ui.context.connect({role:'station', station:'front-1'});
  ui.element('scan-code').value='partial-badge';
  ui.element('scan-feedback').textContent='Previous person checked in';
  ui.element('scan-out').onclick();
  assert.equal(ui.element('scan-code').value, '');
  assert.equal(ui.element('scan-feedback').textContent, 'Ready to sign OUT');
  assert.equal(ui.sent.filter(r=>r.route==='/scans').length, 0);
});

test('mode stays locked during a request and an ambiguous failure; retry preserves the original scan', async()=>{
  const held = deferred();
  let attempts=0;
  const ui = boot({'/scans':()=>++attempts===1 ? held.promise : response({name:'Alex',message:'Checked OUT',occurred_at:1})});
  await ui.context.connect({role:'station', station:'front-1'});
  ui.element('scan-out').onclick();
  ui.element('scan-code').value='fictional-badge';
  ui.element('scan-form').onsubmit({preventDefault(){}});
  assert.equal(ui.element('scan-in').disabled, true);
  ui.element('scan-in').onclick();
  assert.equal(ui.read('direction'), 'out');
  held.resolve(response({detail:'Unavailable'},503));
  await flush();
  assert.equal(ui.element('scan-in').disabled, true);
  ui.element('scan-in').onclick();
  assert.equal(ui.read('direction'), 'out');
  await ui.element('retry').onclick();
  const scans=ui.sent.filter(r=>r.route==='/scans');
  assert.deepEqual(scans[0].body,scans[1].body);
  assert.equal(ui.element('scan-in').disabled,false);
  assert.equal(ui.read('direction'),'out');
});

test('reconnecting restores a pending OUT scan and keeps mode changes locked', async()=>{
  const ui = boot();
  const pending={code:'fictional-badge',direction:'out',request_id:'00000000-0000-4000-8000-000000000099'};
  ui.stored.set('pending:front-1',JSON.stringify(pending));
  await ui.context.connect({role:'station',station:'front-1'});
  assert.equal(ui.read('direction'),'out');
  assert.equal(ui.element('scan-out').attributes['aria-pressed'],'true');
  assert.equal(ui.element('scan-in').disabled,true);
  assert.equal(ui.element('retry').hidden,false);
  ui.element('scan-in').onclick();
  assert.equal(ui.read('direction'),'out');
});

test('a definitive rejected badge releases the mode buttons', async()=>{
  const ui=boot({'/scans':()=>response({detail:'Unknown badge'},404)});
  await ui.context.connect({role:'station',station:'front-2'});
  ui.element('scan-code').value='unknown-badge';
  ui.element('scan-form').onsubmit({preventDefault(){}});
  await flush();
  assert.equal(ui.element('scan-out').disabled,false);
  ui.element('scan-out').onclick();
  assert.equal(ui.read('direction'),'out');
});
