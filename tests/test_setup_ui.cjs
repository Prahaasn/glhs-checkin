// Setup checklist, batch badge printing, and the badge sheet, using the real scripts.
const test = require('node:test');
const assert = require('node:assert/strict');
const {setup, response, deferred, flush, boot} = require('./ui_harness.cjs');

const people = [
  {id:1, name:'Alex Morgan', teacher_id:'DEMO-001', active:true, presence:'unrecorded', inside:null, last_seen:null, badge_issued_at:null},
  {id:2, name:'Jordan Rivera', teacher_id:'DEMO-002', active:true, presence:'out', inside:false, last_seen:1, badge_issued_at:1760000000},
  {id:3, name:'Taylor Chen', teacher_id:'DEMO-003', active:false, presence:'out', inside:false, last_seen:1, badge_issued_at:1760000000}];
const checklist = {...setup, remaining:2, staff:{active:2, inactive:1, demo:true}, badges:{missing:[1], issued:1}, steps:[
  {key:'roster', status:'done', title:'Staff roster', detail:'2 active staff members · 1 inactive.', lines:[], help:[],
    actions:[{type:'page', page:'teachers', label:'Open Staff & badges'}]},
  {key:'badges', status:'todo', title:'Badges', detail:'1 of 2 active staff members has no badge on record.', lines:[],
    help:[{text:'Print at Actual size / 100%.', command:null}], actions:[{type:'print_missing', label:'Print 1 badge'}]},
  {key:'office', status:'done', title:'Office logins', detail:'1 active office login.', lines:[], actions:[],
    help:[{text:'Run <this> on the server.', command:'uv run --env-file .env python -m app.setup add-user --username NAME'}]},
  {key:'stations', status:'todo', title:'Scanner stations', detail:'Station 2 is not signed in.', actions:[], help:[],
    lines:['Station 1: signed in until Sat Oct 11, 7:00 PM · no scans yet']}]};
const card = (id, name, teacher_id) => ({id, name, teacher_id, badge_code:'code-' + id, qr:['000', '010', '000'], code128:'11011'});
const lastWrite = ui => ui.sent.filter(request => request.method !== 'GET').pop();
const stepClick = (ui, key, action = 0) => ui.element('setup-steps').onclick({target:{closest:()=>({dataset:{setupStep:key, action:String(action)}})}});

function office(routes = {}) {
  const ui = boot({'/setup':()=>response(checklist), ...routes});
  ui.read("page='setup';directoryStaff=" + JSON.stringify(people));
  return ui;
}

test('checklist renders steps, escaped help commands, actions, and the remaining count', async()=>{
  const ui = office();
  await ui.context.refreshSetup();
  const html = ui.element('setup-steps').innerHTML;
  assert.match(html, /setup-step done[\s\S]*✓[\s\S]*Staff roster/);
  assert.match(html, /setup-step todo[\s\S]*Badges[\s\S]*To do[\s\S]*Print 1 badge/);
  assert.match(html, /Run &lt;this&gt; on the server\.<code>uv run --env-file \.env python -m app\.setup add-user/);
  assert.match(html, /Station 1: signed in until/);
  assert.equal(ui.element('setup-count').textContent, 2);
  assert.equal(ui.element('setup-count').hidden, false);
  assert.equal(ui.element('badge-summary').textContent, '1 active staff member has no badge on record.');
  ui.element('setup-steps').innerHTML = 'unchanged';
  await ui.context.refreshSetup();
  assert.equal(ui.element('setup-steps').innerHTML, 'unchanged');
});

test('print missing badges preselects staff without one, then issues and draws a sheet', async()=>{
  const ui = office({'/badges/batch':()=>response({issued:[card(1, 'Alex Morgan', 'DEMO-001')], replaced:0, issued_at:1})});
  await ui.context.refreshSetup();
  stepClick(ui, 'badges');
  assert.equal(ui.element('print-dialog').open, true);
  const list = ui.element('print-list').innerHTML;
  assert.match(list, /data-print-pick="1" checked>[\s\S]*No badge on record/);
  assert.match(list, /data-print-pick="2">[\s\S]*Badge issued/);
  assert.doesNotMatch(list, /Taylor Chen/);
  assert.match(ui.element('print-summary').textContent, /^1 new badge will be drawn[\s\S]*None of them has a badge on record/);
  assert.equal(ui.element('print-issue').textContent, 'Issue 1 badge');
  assert.equal(ui.element('print-issue').className, 'primary');
  assert.equal(ui.sent.filter(request => request.method === 'POST').length, 0);
  await ui.context.issueBadges();
  assert.deepEqual(lastWrite(ui).body, {teacher_pks:[1], reviewed_badges:{1:null}});
  assert.equal(ui.element('print-dialog').open, false);
  const sheet = ui.element('badge-preview').innerHTML;
  assert.match(sheet, /Alex Morgan[\s\S]*DEMO-001 · FICTIONAL DEMO/);
  assert.match(sheet, /<svg class="badge-barcode" viewBox="0 0 25 1"[\s\S]*d="M10 0h2v1h-2zM13 0h2v1h-2z"/);
  assert.match(sheet, /<svg class="badge-qr" viewBox="0 0 3 3"[\s\S]*d="M1 1h1v1h-1z"/);
  assert.equal(ui.element('print-root').innerHTML, sheet);
  assert.equal(ui.bodyClasses.has('has-badge-sheet'), true);
  assert.equal(ui.element('badge-sheet-panel').hidden, false);
  assert.equal(ui.read('page'), 'teachers');
  assert.match(ui.element('toast').textContent, /1 badge issued\. Print the sheet now/);
});

test('choosing someone who has a badge warns before replacing it', async()=>{
  const ui = office({'/badges/batch':()=>response({issued:[card(1, 'Alex Morgan', 'DEMO-001'), card(2, 'Jordan Rivera', 'DEMO-002')], replaced:1, issued_at:1})});
  ui.context.openPrintDialog('missing');
  ui.element('print-list').onchange({target:{dataset:{printPick:'2'}, checked:true}});
  assert.match(ui.element('print-summary').textContent, /2 new badges[\s\S]*1 badge they carry now will stop working immediately/);
  assert.equal(ui.element('print-issue').textContent, 'Replace and issue 2 badges');
  assert.equal(ui.element('print-issue').className, 'primary danger');
  await ui.context.issueBadges();
  assert.deepEqual(lastWrite(ui).body, {teacher_pks:[1, 2], reviewed_badges:{1:null, 2:1760000000}});
  ui.context.pickPrint('none');
  assert.equal(ui.element('print-issue').disabled, true);
});

test('a refused batch keeps the dialog open and draws nothing', async()=>{
  const ui = office({'/badges/batch':()=>response({detail:'Alex Morgan has a different badge on record than this screen showed. Review the list again; no badges were issued.'}, 409)});
  ui.context.openPrintDialog('all');
  await ui.context.issueBadges();
  assert.equal(ui.element('print-dialog').open, true);
  assert.match(ui.element('print-error').textContent, /^Alex Morgan has a different badge on record/);
  assert.equal(ui.element('print-issue').disabled, false);
  assert.equal(ui.element('badge-preview').innerHTML, '');
  assert.equal(ui.bodyClasses.has('has-badge-sheet'), false);
});

test('a stale list sends what it showed, and a refusal redraws the real replacement warning', async()=>{
  const reissued = people.map(person => person.id === 1 ? {...person, badge_issued_at:1760500000} : person);
  const ui = office({'/teachers':()=>response(reissued),
    '/badges/batch':()=>response({detail:'Alex Morgan has a different badge on record than this screen showed. Review the list again; no badges were issued.'}, 409)});
  ui.context.openPrintDialog('missing');
  assert.equal(ui.element('print-issue').textContent, 'Issue 1 badge');
  // Another desk issues Alex's badge; a background refresh updates the list without redrawing the dialog.
  ui.read('directoryStaff=' + JSON.stringify(reissued));
  await ui.context.issueBadges();
  assert.deepEqual(lastWrite(ui).body, {teacher_pks:[1], reviewed_badges:{1:null}});
  assert.match(ui.element('print-list').innerHTML, /data-print-pick="1" checked>[\s\S]*Badge issued/);
  assert.equal(ui.element('print-issue').textContent, 'Replace and issue 1 badge');
  assert.equal(ui.element('print-issue').className, 'primary danger');
  assert.deepEqual(JSON.parse(ui.read('JSON.stringify(printReview.reviewed_badges)')), {1:1760500000});
});

test('signing out clears the sheet and a late batch response is never drawn', async()=>{
  const late = deferred();
  const ui = office({'/badges/batch':()=>late.promise});
  ui.read("addToBadgeSheet([" + JSON.stringify(card(2, 'Jordan Rivera', 'DEMO-002')) + "], sheetGeneration)");
  assert.match(ui.element('print-root').innerHTML, /Jordan Rivera/);
  ui.context.openPrintDialog('missing');
  const pending = ui.context.issueBadges();
  ui.context.clearLocal();
  late.resolve(response({issued:[card(1, 'Alex Morgan', 'DEMO-001')], replaced:0, issued_at:1}));
  await pending; await flush();
  assert.equal(ui.element('print-root').innerHTML, '');
  assert.equal(ui.element('badge-preview').innerHTML, '');
  assert.equal(ui.bodyClasses.has('has-badge-sheet'), false);
  assert.equal(ui.element('print-dialog').open, false);
});

test('reissuing someone swaps their card, and clearing the sheet needs confirmation', async()=>{
  const ui = office();
  ui.read("addToBadgeSheet([" + JSON.stringify(card(1, 'Alex Morgan', 'DEMO-001')) + "," + JSON.stringify(card(2, 'Jordan Rivera', 'DEMO-002')) + "], sheetGeneration)");
  ui.read("addToBadgeSheet([" + JSON.stringify({...card(1, 'Alex Morgan', 'DEMO-001'), badge_code:'newer'}) + "], sheetGeneration)");
  assert.equal(ui.read('badgeSheet.length'), 2);
  assert.equal(ui.read('badgeSheet[1].badge_code'), 'newer');
  ui.element('badge-sheet-clear').onclick();
  assert.equal(ui.element('confirm-dialog').open, true);
  assert.match(ui.element('confirm-body').textContent, /cannot be shown again/);
  assert.equal(ui.read('badgeSheet.length'), 2);
  await ui.context.runConfirmed();
  assert.equal(ui.read('badgeSheet.length'), 0);
  assert.equal(ui.element('badge-sheet-panel').hidden, true);
});

test('issuing one badge from the staff list reviews it and adds it to the sheet', async()=>{
  const ui = office({'/teachers/1/badge':()=>response(card(1, 'Alex Morgan', 'DEMO-001'))});
  ui.element('directory').onclick({target:{closest:()=>({dataset:{badge:'1'}})}});
  assert.equal(ui.element('confirm-title').textContent, 'Issue a badge for Alex Morgan?');
  assert.equal(ui.sent.filter(request => request.method === 'POST').length, 0);
  await ui.context.runConfirmed();
  assert.equal(lastWrite(ui).route, '/teachers/1/badge');
  assert.match(ui.element('badge-preview').innerHTML, /Alex Morgan/);
  ui.element('directory').onclick({target:{closest:()=>({dataset:{badge:'2'}})}});
  assert.equal(ui.element('confirm-title').textContent, "Replace Jordan Rivera's badge?");
});

test('a brand-new installation opens the checklist once per sign-in', async()=>{
  const ui = office({'/setup':()=>response({...setup, staff:{active:0, inactive:0, demo:false}, badges:{missing:[], issued:0}})});
  ui.read("page='dashboard'");
  await ui.context.refreshSetup();
  assert.equal(ui.read('page'), 'setup');
  ui.read("page='dashboard'");
  await ui.context.refreshSetup();
  assert.equal(ui.read('page'), 'dashboard');
});

test('the print dialog waits for the staff list instead of opening empty', ()=>{
  const ui = office();
  ui.read('directoryStaff=[]');
  ui.context.openPrintDialog('missing');
  assert.equal(ui.element('print-dialog').open, false);
  assert.match(ui.element('toast').textContent, /still loading/);
});
