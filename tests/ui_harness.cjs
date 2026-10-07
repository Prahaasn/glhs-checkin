// Run the real browser scripts against a small fake DOM. Rendering is checked in-app.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const DAY = '2026-10-07';
const SCRIPTS = ['coverage.js', 'dialogs.js', 'attention.js', 'app.js'];  // index.html order
const staff = [{id:1, name:'Alex Morgan', teacher_id:'DEMO-001', active:true,
  presence:'unrecorded', inside:null, last_seen:null}];
const entry = {id:1, teacher_pk:1, teacher_id:'DEMO-001', name:'Alex Morgan',
  active:true, day:DAY, substitute_name:null, cancelled:false, version:1,
  updated_at:1, updated_by:'Office', presence:'unrecorded'};
const coverage = {day:DAY, today:DAY, entries:[entry], planned:1, covered:0, unassigned:1};
const range = {start:DAY, end:'2026-10-20', today:DAY, planned:0, covered:0, unassigned:0, days:[]};
const attention = {today:DAY, day_start:0, items:[], not_arrived:[], planned_today:[],
  coverage:{planned:0, covered:0, unassigned:0}};
const response = (data, status=200) => ({ok:status<400, status, json:async()=>data});
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
};
const flush = () => new Promise(done => setImmediate(done));

function boot(routes = {}) {
  const elements = new Map(), listeners = {}, requests = [], sent = [], timers = [];
  const element = id => {
    if (!elements.has(id)) {
      const item = {id, value:'', textContent:'', innerHTML:'', checked:false,
        hidden:false, disabled:false, open:false, dataset:{}, listeners:{}, attributes:{},
        className:'', setAttribute(name, value){this.attributes[name]=value;}, removeAttribute(name){delete this.attributes[name];},
        replaceChildren(){this.innerHTML='';}, reset(){},
        close(){this.open=false;}, showModal(){this.open=true;}, focus(){},
        scrollIntoView(){}, addEventListener(event, handler){this.listeners[event]=handler;}};
      elements.set(id, item);
    }
    return elements.get(id);
  };
  const context = vm.createContext({
    document:{getElementById:element, querySelector:()=>element('nav'),
      querySelectorAll:()=>[], addEventListener:(event, handler)=>{(listeners[event] ||= []).push(handler);},
      body:{classList:{remove(){},toggle(){}}}},
    URLSearchParams, URL, Date, crypto:{randomUUID:()=>'00000000-0000-4000-8000-' + String(sent.length).padStart(12, '0')},
    // Timers are held until a test runs them, so delayed UI resets can be checked deterministically.
    setInterval(){}, setTimeout(handler){timers.push(handler); return timers.length;}, clearTimeout(id){if (id) timers[id - 1] = null;},
    encodeURIComponent,
    sessionStorage:{removeItem(){},getItem(){return null;},setItem(){}},
    fetch:async(url, options={})=>{
      const route = new URL(url, 'http://local.test').pathname.replace('/api','');
      requests.push(route); sent.push({url, route, method:options.method || 'GET',
        body:options.body ? JSON.parse(options.body) : null});
      if (route === '/session') return new Promise(()=>{});
      const result = routes[route];
      if (result) return typeof result === 'function' ? result(options, url) : result;
      if (route === '/teachers') return response(staff);
      if (route === '/events') return response([]);
      if (route === '/absences') return response(coverage);
      if (route === '/absences/range') return response(range);
      if (route === '/substitutes') return response([]);
      if (route === '/attention') return response(attention);
      throw new Error('Unexpected route: ' + route);
    }
  });
  // GLHS_UI_SOURCE_ROOT runs these tests against another checkout, e.g. main, to prove they fail there.
  const root = process.env.GLHS_UI_SOURCE_ROOT || path.resolve(__dirname, '..');
  for (const file of SCRIPTS) {
    const source = path.join(root, 'app/static', file);
    if (fs.existsSync(source)) vm.runInContext(fs.readFileSync(source, 'utf8'), context, {filename:file});
  }
  (listeners.DOMContentLoaded || []).forEach(handler => handler());
  vm.runInContext("role='admin';connected=true;page='coverage';directoryStaff=" + JSON.stringify(staff), context);
  element('coverage-day').value = DAY;
  const runTimers = () => timers.splice(0).forEach(handler => handler && handler());
  return {context, element, requests, sent, runTimers, read:code=>vm.runInContext(code,context)};
}

module.exports = {DAY, staff, entry, coverage, range, attention, response, deferred, flush, boot};
