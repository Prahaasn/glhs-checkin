// Coverage page async state and multi-day planning, using the real scripts.
const test = require('node:test');
const assert = require('node:assert/strict');
const {DAY, staff, entry, coverage, range, response, deferred, flush, boot} = require('./ui_harness.cjs');

test('coverage and staff directory update while activity is pending or fails', async()=>{
  const history = deferred();
  const ui = boot({'/events':()=>history.promise});
  ui.read('directoryStaff=[]');
  const refresh = ui.context.refresh();
  await flush();
  assert.ok(ui.requests.includes('/absences'));
  assert.equal(ui.element('coverage-planned').textContent, 1);
  assert.equal(ui.read('directoryStaff[0].name'), 'Alex Morgan');
  history.resolve(response({detail:'History unavailable'},503));
  await refresh;
  assert.match(ui.element('coverage-rows').innerHTML, /Alex Morgan/);
  assert.equal(ui.element('notice').hidden, false);
});

test('ending a session resets coverage date and cancelled filter', ()=>{
  const ui = boot();
  ui.element('coverage-day').value = '2026-10-08';
  ui.element('coverage-cancelled').checked = true;
  ui.context.clearCoverage();
  assert.equal(ui.element('coverage-day').value, '');
  assert.equal(ui.element('coverage-cancelled').checked, false);
  assert.equal(ui.element('coverage-rows').innerHTML, '');
});

test('switching date removes old actionable rows even if refresh fails', async()=>{
  const pending = deferred();
  let slow = false;
  const ui = boot({'/absences':()=>slow ? pending.promise : response(coverage)});
  await ui.context.refreshCoverage();
  assert.match(ui.element('coverage-rows').innerHTML, /Edit cover/);
  slow = true;
  ui.element('coverage-day').value = '2026-10-08';
  ui.element('coverage-day').onchange();
  assert.doesNotMatch(ui.element('coverage-rows').innerHTML, /Edit cover|Alex Morgan/);
  assert.equal(ui.element('coverage-planned').textContent, '—');
  assert.equal(ui.read('coverageEntries.length'), 0);
  pending.resolve(response({detail:'Coverage unavailable'},503));
  await flush();
  assert.doesNotMatch(ui.element('coverage-rows').innerHTML, /Edit cover|Alex Morgan/);
  assert.match(ui.element('coverage-message').textContent, /Could not refresh/);
});

test('entering another date cannot expose dashboard rows during a failed refresh', async()=>{
  const pending = deferred();
  let slow = false;
  const ui = boot({'/absences':()=>slow ? pending.promise : response(coverage)});
  ui.read("page='dashboard'");
  await ui.context.refreshCoverage();
  slow = true;
  ui.element('coverage-day').value = '2026-10-08';
  ui.read("page='coverage'");
  const refresh = ui.context.refreshCoverage();
  assert.doesNotMatch(ui.element('coverage-rows').innerHTML, /Edit cover|Alex Morgan/);
  pending.resolve(response({detail:'Coverage unavailable'},503));
  await refresh;
  assert.equal(ui.read('coverageEntries.length'), 0);
});

for (const status of [201,503]) {
  test('earlier save response ' + status + ' leaves a newer dialog intact', async()=>{
    const pending = deferred();
    const ui = boot({'/absences':options=>options.method ? pending.promise : response(coverage)});
    ui.context.openCoverage('create');
    ui.element('coverage-teacher').value = '1';
    ui.element('coverage-form-day').value = '2026-10-08';
    ui.element('coverage-substitute').value = 'Old form';
    const saving = ui.element('coverage-form').onsubmit({preventDefault(){}});
    ui.element('coverage-dialog-close').onclick();
    ui.context.openCoverage('create');
    ui.element('coverage-substitute').value = 'New unsaved form';
    pending.resolve(response(status===201 ? {...entry,day:'2026-10-08'} : {detail:'Save failed'},status));
    await saving;
    assert.equal(ui.element('coverage-dialog').open, true);
    assert.equal(ui.element('coverage-substitute').value, 'New unsaved form');
    assert.equal(ui.element('coverage-form-error').textContent, '');
    assert.equal(ui.element('coverage-save').disabled, false);
    assert.equal(ui.element('coverage-day').value, DAY);
  });
}

const seriesDays = [
  {id:1, day:'2026-10-08', version:1, cancelled:false, substitute_name:null},
  {id:2, day:'2026-10-09', version:3, cancelled:false, substitute_name:null},
  {id:3, day:'2026-10-12', version:2, cancelled:false, substitute_name:null},
  {id:4, day:'2026-10-13', version:5, cancelled:true, substitute_name:null}];
const seriesEntry = {...entry, id:2, day:'2026-10-09', version:3, series_id:'plan-1',
  series:{position:2, total:4, first_day:'2026-10-08', last_day:'2026-10-13', planned:3, days:seriesDays}};
const lastSave = ui => ui.sent.filter(request => request.method !== 'GET').pop();

test('planning several school days previews the weekend skip and sends the count', async()=>{
  const ui = boot({'/absences':options=>options.method ? response({...entry, day:'2026-10-08', series:{total:4}}, 201) : response(coverage)});
  ui.context.openCoverage('create');
  assert.equal(ui.element('coverage-days-field').hidden, false);
  assert.equal(ui.element('coverage-scope').hidden, true);
  ui.element('coverage-teacher').value = '1';
  ui.element('coverage-form-day').value = '2026-10-08';
  ui.element('coverage-days').value = '4';
  ui.context.renderCoveragePreview();
  assert.match(ui.element('coverage-preview').textContent, /Oct 8 through .*Oct 13 · 4 school days, weekends skipped/);
  assert.match(ui.element('coverage-preview').textContent, /\(Thu 8, Fri 9, Mon 12, Tue 13\)/);
  await ui.element('coverage-form').onsubmit({preventDefault(){}});
  assert.deepEqual(lastSave(ui).body, {substitute_name:null, teacher_pk:1, day:'2026-10-08', school_days:4});
  assert.match(ui.element('coverage-message').textContent, /Planned 4 school days for Alex Morgan/);
});

test('weekend first days and invalid counts are flagged before saving', ()=>{
  const ui = boot();
  ui.context.openCoverage('create');
  ui.element('coverage-form-day').value = '2026-10-10';
  ui.context.renderCoveragePreview();
  assert.match(ui.element('coverage-preview').textContent, /Saturday is a weekend day/);
  assert.equal(ui.element('coverage-preview').dataset.warning, 'true');
  ui.element('coverage-days').value = '91';
  ui.context.renderCoveragePreview();
  assert.match(ui.element('coverage-preview').textContent, /Enter 1 to 90 school days/);
});

test('editing cover on a multi-day plan defaults to later active days with reviewed versions', async()=>{
  const ui = boot({'/absences/2':()=>response({...seriesEntry, substitute_name:'Pat Lee', changed_days:2})});
  ui.context.openCoverage('edit', seriesEntry);
  assert.equal(ui.element('coverage-scope').hidden, false);
  assert.equal(ui.element('coverage-scope-following').checked, true);
  assert.match(ui.element('coverage-scope-following-text').textContent, /1 later day \(through .*Oct 12\)/);
  ui.element('coverage-substitute').value = 'Pat Lee';
  await ui.element('coverage-form').onsubmit({preventDefault(){}});
  assert.deepEqual(lastSave(ui).body, {substitute_name:'Pat Lee', version:3, cancelled:false, scope:'following', versions:{3:2}});
  assert.match(ui.element('coverage-message').textContent, /Cover saved for Alex Morgan on 2 school days/);
});

test('cancelling a multi-day plan starts with only the selected day', async()=>{
  const ui = boot({'/absences/2':()=>response({...seriesEntry, cancelled:true, changed_days:1})});
  ui.context.openCoverage('cancel', seriesEntry);
  assert.equal(ui.element('coverage-scope-following').checked, false);
  assert.equal(ui.element('coverage-scope-day').checked, true);
  await ui.element('coverage-form').onsubmit({preventDefault(){}});
  assert.deepEqual(lastSave(ui).body, {substitute_name:null, version:3, cancelled:true});
});

test('upcoming view loads two weeks and open day returns to that date', async()=>{
  const upcoming = {...range, planned:1, unassigned:1, days:[{day:'2026-10-09', planned:1, covered:0, unassigned:1, entries:[seriesEntry]}]};
  const ui = boot({'/absences/range':()=>response(upcoming)});
  ui.element('coverage-view-upcoming').onclick();
  await flush();
  const request = ui.sent.find(item => item.route === '/absences/range');
  assert.match(request.url, /start=2026-10-07&end=2026-10-20/);
  assert.equal(ui.element('coverage-day-panel').hidden, true);
  assert.match(ui.element('coverage-upcoming-list').innerHTML, /Alex Morgan[\s\S]*Day 2 of 4[\s\S]*Needs cover/);
  ui.element('coverage-upcoming-list').onclick({target:{closest:()=>({dataset:{openDay:'2026-10-09'}})}});
  assert.equal(ui.element('coverage-day').value, '2026-10-09');
  assert.equal(ui.read('coverageView'), 'day');
  assert.equal(ui.element('coverage-upcoming').hidden, true);
});

test('day rows flag a substitute covering two staff and a planned-out IN scan', async()=>{
  const busy = {...coverage, entries:[
    {...entry, substitute_name:'Pat Lee', presence:'in'},
    {...entry, id:9, teacher_pk:9, name:'Jordan Rivera', substitute_name:' pat  lee '}]};
  const ui = boot({'/absences':()=>response(busy)});
  await ui.context.refreshCoverage();
  assert.match(ui.element('coverage-rows').innerHTML, /Also covering Jordan Rivera/);
  assert.match(ui.element('coverage-rows').innerHTML, /Also covering Alex Morgan/);
  assert.match(ui.element('coverage-rows').innerHTML, /Recorded IN while planned out/);
});

test('conflict check warns about a double-booked substitute before saving', async()=>{
  const other = {...entry, id:9, teacher_pk:9, name:'Jordan Rivera', day:'2026-10-09', substitute_name:'Pat Lee'};
  const ui = boot({'/absences/range':()=>response({...range, days:[{day:'2026-10-09', entries:[other]}]})});
  ui.context.openCoverage('create');
  ui.element('coverage-teacher').value = '1';
  ui.element('coverage-form-day').value = '2026-10-08';
  ui.element('coverage-days').value = '2';
  ui.element('coverage-substitute').value = 'pat lee';
  await ui.context.checkCoverageConflicts();
  assert.match(ui.element('coverage-conflict').textContent, /Pat Lee is already covering Jordan Rivera on .*Oct 9/);
});

test('day stepping waits for the first coverage load instead of throwing', ()=>{
  const ui = boot();
  ui.element('coverage-day').value = '';
  ui.element('coverage-next').onclick();
  assert.equal(ui.element('coverage-day').value, '');
  ui.element('coverage-day').value = '2026-10-09';
  ui.element('coverage-next').onclick();
  assert.equal(ui.element('coverage-day').value, '2026-10-12');
});

test('conflict check covers a long plan in range-sized windows', async()=>{
  const late = {...entry, id:9, teacher_pk:9, name:'Jordan Rivera', day:'2026-12-15', substitute_name:'Pat Lee'};
  let ui;
  ui = boot({'/absences/range':()=>{
    const url = new URL(ui.sent[ui.sent.length - 1].url, 'http://local.test');
    const [start, end] = [url.searchParams.get('start'), url.searchParams.get('end')];
    return response({...range, start, end, days:start <= late.day && late.day <= end ? [{day:late.day, entries:[late]}] : []});
  }});
  ui.context.openCoverage('create');
  ui.element('coverage-teacher').value = '1';
  ui.element('coverage-form-day').value = '2026-10-08';
  ui.element('coverage-days').value = '90';
  ui.element('coverage-substitute').value = 'Pat Lee';
  await ui.context.checkCoverageConflicts();
  const windows = ui.sent.filter(item => item.route === '/absences/range').map(item => {
    const url = new URL(item.url, 'http://local.test');
    return [url.searchParams.get('start'), url.searchParams.get('end')];
  });
  assert.ok(windows.length >= 3);
  assert.equal(windows[0][0], '2026-10-08');
  for (const [start, end] of windows) assert.ok((Date.parse(end) - Date.parse(start)) / 86400000 < 62);
  assert.match(ui.element('coverage-conflict').textContent, /Pat Lee is already covering Jordan Rivera on .*Dec 15/);
});
