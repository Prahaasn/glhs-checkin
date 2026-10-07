// Overview attention queue, review dialogs, roster views, and activity filters, using the real scripts.
const test = require('node:test');
const assert = require('node:assert/strict');
const {DAY, entry, coverage, attention, response, flush, boot} = require('./ui_harness.cjs');

const person = {id:3, name:'Taylor Chen', teacher_id:'DEMO-003', active:true, presence:'in', inside:true, last_seen:1};
const stale = {id:'stale_in:3::', kind:'stale_in', tone:'warning', title:'Taylor Chen is still recorded IN from Tue Oct 6',
  detail:'Last status change Tue Oct 6, 3:10 PM.', teacher_pk:3,
  actions:[{type:'correct', label:'Record OUT', teacher_pk:3, direction:'out', reason:'Missed departure scan'}]};
const gap = {id:'needs_cover_today:1:1:', kind:'needs_cover_today', tone:'action', title:'Alex Morgan needs cover today',
  detail:'Planned absence with no substitute assigned.', teacher_pk:1, absence_id:1, day:DAY,
  actions:[{type:'edit_cover', label:'Assign cover', absence_id:1, day:DAY}]};
const missing = {id:'not_arrived:::' + DAY, kind:'not_arrived', tone:'info', title:'1 staff member with no arrival recorded today',
  detail:'Not planned out.', actions:[{type:'show_not_arrived', label:'Show list'}]};
const queue = {...attention, items:[gap, stale, missing], not_arrived:[2],
  planned_today:[{teacher_pk:1, absence_id:1, substitute_name:null}], coverage:{planned:1, covered:0, unassigned:1}};
const click = (ui, list, itemId, action = 0) => ui.element(list).onclick({target:{closest:()=>({dataset:{attention:itemId, action:String(action)}, disabled:false})}});
const lastWrite = ui => ui.sent.filter(request => request.method !== 'GET').pop();

function overview(routes = {}) {
  const ui = boot({'/attention':()=>response(queue), ...routes});
  ui.read("page='dashboard';directoryStaff=directoryStaff.concat([" + JSON.stringify(person) + "])");
  return ui;
}

test('attention queue renders actions, counts open items, and skips identical re-renders', async()=>{
  const ui = overview();
  await ui.context.refreshAttention();
  const html = ui.element('attention-list').innerHTML;
  assert.match(html, /Alex Morgan needs cover today[\s\S]*Assign cover/);
  assert.match(html, /Taylor Chen is still recorded IN[\s\S]*Record OUT/);
  assert.equal(ui.element('attention-count').textContent, 2);
  assert.equal(ui.element('attention-count').hidden, false);
  ui.element('attention-list').innerHTML = 'unchanged';
  await ui.context.refreshAttention();
  assert.equal(ui.element('attention-list').innerHTML, 'unchanged');
});

test('an empty queue says all clear and a failed check is reported', async()=>{
  let fail = false;
  const ui = overview({'/attention':()=>fail ? response({detail:'Database temporarily unavailable.'}, 503) : response(attention)});
  await ui.context.refreshAttention();
  assert.match(ui.element('attention-list').innerHTML, /All clear/);
  assert.equal(ui.element('attention-count').hidden, true);
  fail = true;
  await ui.context.refreshAttention();
  assert.match(ui.element('attention-list').innerHTML, /Could not check[\s\S]*Database temporarily unavailable/);
});

test('record OUT opens a prefilled correction and only the review saves it', async()=>{
  const ui = overview({'/teachers/3/correction':()=>response({name:'Taylor Chen', changed:true, direction:'out'})});
  await ui.context.refreshAttention();
  await click(ui, 'attention-list', stale.id);
  assert.equal(ui.element('correction-dialog').open, true);
  assert.equal(ui.element('correction-out').checked, true);
  assert.equal(ui.element('correction-reason').value, 'Missed departure scan');
  assert.match(ui.element('correction-current').textContent, /Currently recorded: IN since/);
  assert.equal(ui.sent.filter(request => request.method === 'POST').length, 0);
  await ui.context.saveCorrection();
  const write = lastWrite(ui);
  assert.equal(write.route, '/teachers/3/correction');
  assert.deepEqual({direction:write.body.direction, reason:write.body.reason}, {direction:'out', reason:'Missed departure scan'});
  assert.equal(ui.element('correction-dialog').open, false);
  assert.match(ui.element('toast').textContent, /Taylor Chen is now recorded OUT/);
});

test('an unconfirmed correction retries with the same request ID until the form changes', async()=>{
  let status = 503;
  const ui = overview({'/teachers/3/correction':()=>response(status === 200 ? {name:'Taylor Chen', changed:true} : {detail:'Database temporarily unavailable.'}, status)});
  ui.context.openCorrection(person, {direction:'out', reason:'Missed departure scan'});
  await ui.context.saveCorrection();
  assert.match(ui.element('correction-error').textContent, /not confirmed[\s\S]*retry it safely/);
  const first = lastWrite(ui).body.request_id;
  await ui.context.saveCorrection();
  assert.equal(lastWrite(ui).body.request_id, first);
  ui.element('correction-reason').value = 'Forgot badge';
  status = 422;
  await ui.context.saveCorrection();
  const changed = lastWrite(ui).body.request_id;
  assert.notEqual(changed, first);
  status = 200;
  await ui.context.saveCorrection();
  assert.notEqual(lastWrite(ui).body.request_id, changed);
  assert.equal(ui.element('correction-dialog').open, false);
});

test('a correction needs an explicit status and a reason before any request', async()=>{
  const ui = overview();
  ui.context.openCorrection({...person, presence:'unrecorded'});
  assert.equal(ui.element('correction-in').checked, true);
  ui.element('correction-in').checked = false;
  await ui.context.saveCorrection();
  assert.match(ui.element('correction-error').textContent, /Choose IN or OUT/);
  ui.element('correction-out').checked = true;
  ui.element('correction-reason').value = 'no';
  await ui.context.saveCorrection();
  assert.match(ui.element('correction-error').textContent, /at least 3 characters/);
  assert.equal(ui.sent.filter(request => request.method === 'POST').length, 0);
});

test('assign cover opens that absence and saving from the overview stays there', async()=>{
  const ui = overview({'/absences/1':()=>response({...entry, substitute_name:'Pat Lee', version:2, changed_days:1})});
  await ui.context.refreshAttention();
  await click(ui, 'attention-list', gap.id);
  await flush();
  assert.equal(ui.element('coverage-dialog').open, true);
  assert.equal(ui.read('coverageAction'), 'edit');
  assert.equal(ui.read('coverageEditing.id'), 1);
  ui.element('coverage-substitute').value = 'Pat Lee';
  await ui.element('coverage-form').onsubmit({preventDefault(){}});
  assert.equal(ui.read('page'), 'dashboard');
  assert.match(ui.element('toast').textContent, /Cover saved for Alex Morgan on 1 school day/);
});

test('roster tags planned-out staff and filters planned and no-arrival views for live data only', async()=>{
  const ui = overview();
  ui.read("staff=" + JSON.stringify([
    {id:1, name:'Alex Morgan', teacher_id:'DEMO-001', active:true, presence:'unrecorded', inside:null, last_seen:null},
    {id:2, name:'Jordan Rivera', teacher_id:'DEMO-002', active:true, presence:'out', inside:false, last_seen:1},
    person]));
  await ui.context.refreshAttention();
  assert.match(ui.element('roster').innerHTML, /Alex Morgan[\s\S]*Planned out today · needs cover/);
  ui.context.setRosterFilter('planned');
  assert.match(ui.element('roster').innerHTML, /Alex Morgan/);
  assert.doesNotMatch(ui.element('roster').innerHTML, /Jordan Rivera|Taylor Chen/);
  ui.context.setRosterFilter('not-arrived');
  assert.match(ui.element('roster').innerHTML, /Jordan Rivera/);
  assert.doesNotMatch(ui.element('roster').innerHTML, /Alex Morgan|Taylor Chen/);
  ui.element('as-of').value = '2026-10-06T09:00';
  ui.context.renderRoster();
  assert.match(ui.element('roster').innerHTML, /No staff match/);
  ui.context.setRosterFilter('all');
  assert.doesNotMatch(ui.element('roster').innerHTML, /Planned out today|data-roster-correct/);
});

test('deactivation is confirmed in a dialog that keeps server errors visible', async()=>{
  let status = 409;
  const ui = overview({'/teachers/3':()=>response(status === 200 ? person : {detail:'Record a check-out or office correction before deactivating.'}, status)});
  ui.element('directory').onclick({target:{closest:()=>({dataset:{deactivate:'3'}})}});
  assert.equal(ui.element('confirm-dialog').open, true);
  assert.match(ui.element('confirm-title').textContent, /Deactivate Taylor Chen/);
  assert.equal(ui.sent.filter(request => request.method === 'PATCH').length, 0);
  await ui.context.runConfirmed();
  assert.equal(ui.element('confirm-dialog').open, true);
  assert.match(ui.element('confirm-error').textContent, /Record a check-out/);
  status = 200;
  await ui.context.runConfirmed();
  assert.equal(ui.element('confirm-dialog').open, false);
  assert.match(ui.element('toast').textContent, /Taylor Chen was deactivated/);
  ui.element('directory').onclick({target:{closest:()=>({dataset:{deactivate:'3'}})}});
  ui.element('confirm-cancel').onclick();
  assert.equal(ui.element('confirm-dialog').open, false);
  assert.equal(ui.sent.filter(request => request.method === 'PATCH').length, 2);
});

test('activity filters by type and loads a chosen day', async()=>{
  const events = [
    {id:3, name:'Alex Morgan', teacher_id:'DEMO-001', direction:'out', station:'Office · Front Desk', occurred_at:3, changed:true, reason:'Missed departure scan'},
    {id:2, name:'Jordan Rivera', teacher_id:'DEMO-002', direction:'in', station:'front-1', occurred_at:2, changed:false, reason:null},
    {id:1, name:'Jordan Rivera', teacher_id:'DEMO-002', direction:'in', station:'front-1', occurred_at:1, changed:true, reason:null}];
  const ui = overview({'/events':()=>response(events)});
  ui.read("page='history'");
  ui.element('activity-kind').value = 'all';
  ui.element('activity-day').value = '2026-10-06';
  await ui.context.refresh();
  const request = ui.sent.filter(item => item.route === '/events').pop();
  assert.match(request.url, /since=\d+&until=\d+/);
  assert.match(ui.element('event-table').innerHTML, /Arrival station/);
  ui.element('activity-kind').value = 'corrections';
  ui.context.renderActivity();
  assert.match(ui.element('event-table').innerHTML, /Corrected to out[\s\S]*Missed departure scan/);
  assert.doesNotMatch(ui.element('event-table').innerHTML, /Jordan Rivera/);
  ui.element('activity-kind').value = 'repeats';
  ui.context.renderActivity();
  assert.match(ui.element('activity-count').textContent, /Showing 1 of 3/);
});

test('signing out clears the queue, dialogs, and filters', async()=>{
  const ui = overview();
  await ui.context.refreshAttention();
  ui.context.openCorrection(person);
  ui.element('activity-day').value = '2026-10-06';
  ui.context.setRosterFilter('planned');
  ui.context.clearLocal();
  assert.equal(ui.element('correction-dialog').open, false);
  assert.match(ui.element('attention-list').innerHTML, /Checking today/);
  assert.equal(ui.read('attentionData'), null);
  assert.equal(ui.element('activity-day').value, '');
  assert.equal(ui.read('filter'), 'all');
});
