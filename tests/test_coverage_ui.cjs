// Exercise async UI state with the actual scripts. Rendering is checked in-app.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const DAY = '2026-10-07';
const staff = [{id:1, name:'Alex Morgan', teacher_id:'DEMO-001', active:true,
  presence:'unrecorded', inside:null, last_seen:null}];
const entry = {id:1, teacher_pk:1, teacher_id:'DEMO-001', name:'Alex Morgan',
  active:true, day:DAY, substitute_name:null, cancelled:false, version:1,
  updated_at:1, updated_by:'Office', presence:'unrecorded'};
const coverage = {day:DAY, today:DAY, entries:[entry], planned:1, covered:0, unassigned:1};
const response = (data, status=200) => ({ok:status<400, status, json:async()=>data});
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
};
const flush = () => new Promise(done => setImmediate(done));

function boot(routes = {}) {
  const elements = new Map(), listeners = {}, requests = [];
  const element = id => {
    if (!elements.has(id)) {
      const item = {value:'', textContent:'', innerHTML:'', checked:false,
        hidden:false, disabled:false, open:false, dataset:{}, listeners:{},
        replaceChildren(){this.innerHTML='';}, reset(){},
        close(){this.open=false;}, showModal(){this.open=true;}, focus(){},
        scrollIntoView(){}, addEventListener(event, handler){this.listeners[event]=handler;}};
      elements.set(id, item);
    }
    return elements.get(id);
  };
  const context = vm.createContext({
    document:{getElementById:element, querySelector:()=>element('nav'),
      querySelectorAll:()=>[], addEventListener:(event, handler)=>{listeners[event]=handler;},
      body:{classList:{remove(){},toggle(){}}}},
    URLSearchParams, URL, Date, crypto:{}, setInterval(){}, setTimeout,
    sessionStorage:{removeItem(){},getItem(){return null;}},
    fetch:async(url, options={})=>{
      const route = new URL(url, 'http://local.test').pathname.replace('/api','');
      requests.push(route);
      if (route === '/session') return new Promise(()=>{});
      const result = routes[route];
      if (result) return typeof result === 'function' ? result(options) : result;
      if (route === '/teachers') return response(staff);
      if (route === '/events') return response([]);
      if (route === '/absences') return response(coverage);
      throw new Error('Unexpected route: ' + route);
    }
  });
  const root = process.env.GLHS_UI_SOURCE_ROOT || path.resolve(__dirname, '..');
  for (const file of ['coverage.js','app.js']) {
    vm.runInContext(fs.readFileSync(path.join(root,'app/static',file),'utf8'), context, {filename:file});
  }
  listeners.DOMContentLoaded();
  vm.runInContext("role='admin';connected=true;page='coverage';directoryStaff=" + JSON.stringify(staff), context);
  element('coverage-day').value = DAY;
  return {context, element, requests, read:code=>vm.runInContext(code,context)};
}

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
