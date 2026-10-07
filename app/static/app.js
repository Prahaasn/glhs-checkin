const $ = id => document.getElementById(id);
let role = null, connected = false, stationName = null, sessionExpiry = 0;
let staff = [], events = [], filter = 'all', page = 'dashboard', direction = 'in', busy = false, pending = null, badgeUrl, refreshVersion=0, rosterPage=1, directoryPage=1, directoryStaff=[];
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time = epoch => {if(!epoch)return 'No scans yet';const seen=new Date(epoch*1000);return seen.toDateString()===new Date().toDateString()?seen.toLocaleTimeString([], {hour:'numeric',minute:'2-digit'}):seen.toLocaleString();};
const dateTime = epoch => new Date(epoch * 1000).toLocaleString();
const initials = name => name.split(' ').map(x => x[0]).slice(0,2).join('').toUpperCase();
const stationLabel = station => ({'front-1':'Arrival station','front-2':'Departure station'}[station] || station);
// Activity days use this browser's midnight, matching the times shown in the table.
const dayQuery = day => { if (!day) return ''; const start = new Date(day + 'T00:00:00'), next = new Date(start); next.setDate(start.getDate() + 1); return '?since=' + Math.floor(start / 1000) + '&until=' + Math.floor(next / 1000); };
let scanResetTimer = null;
const uuid = () => crypto.randomUUID ? crypto.randomUUID() : '10000000-1000-4000-8000-100000000000'.replace(/[018]/g,c=>(c^crypto.getRandomValues(new Uint8Array(1))[0]&15>>c/4).toString(16));
async function api(path, options = {}) {
  const response = await fetch('/api' + path, {...options, headers: {'Content-Type':'application/json', ...options.headers}});
  if (!response.ok) { let detail = 'Request failed'; try { const data = await response.json(); detail = typeof data.detail === 'string' ? data.detail : 'Please check the entered values.'; } catch {} if(response.status===401 && connected) clearLocal(); const error = new Error(detail); error.status=response.status; throw error; }
  return response;
}
function clearLocal() {
  refreshVersion++; connected=false; role=null; stationName=null;
  clearCoverage(); clearAttention(); clearDialogs();
  staff=[];events=[];pending=null;filter='all';
  $('activity-day').value='';$('activity-search').value='';$('activity-kind').value='all';
  $('workspace').hidden=true;$('login').hidden=false;$('sidebar').hidden=true;document.querySelector('nav').hidden=false;document.body.classList.remove('station-view');
  $('access-key').value='';$('password').value='';$('scan-code').value='';
  ['roster','directory','event-table','recent'].forEach(id=>$(id).replaceChildren());
  $('badge').hidden=true;$('badge-img').removeAttribute('src');$('badge-name').textContent='';
  $('scan-feedback').textContent='Waiting for a badge';$('teacher-message').textContent='';
  $('notice').hidden=true;
  if(badgeUrl)URL.revokeObjectURL(badgeUrl);
}
async function lock() {
  clearLocal();
  try { const response=await fetch('/api/session',{method:'DELETE'});if(!response.ok)throw new Error(); }
  catch { $('login-error').textContent='Session revocation is unconfirmed. Keep this computer secured, then retry Lock when the server returns.'; }
}
function navigate(next) {
  if (!connected) return;
  if(role === 'station' && next !== 'kiosk') return;
  page=next;
  document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==next);
  document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b.dataset.page===next));
  if(role==='admin' && next!=='kiosk') refresh();
  if(next==='kiosk') { $('scan-code').focus(); if(role==='admin') $('scan-feedback').textContent='Lock this computer and sign in with a station key to scan.'; }
}
async function connect(identity) {
  role=identity.role;connected=true;stationName=identity.station;sessionExpiry=identity.expires_at;
  $('login').hidden=true;$('workspace').hidden=false;$('sidebar').hidden=false;
  document.body.classList.toggle('station-view',role==='station');
  document.querySelector('nav').hidden=role==='station';
  $('signed-in-as').textContent=role==='station'?'':identity.display_name||'Office staff';
  document.querySelectorAll('.nav').forEach(b=>b.hidden=role==='station'?b.dataset.page!=='kiosk':b.dataset.page==='kiosk');
  if(role==='station') {
    direction=stationName==='front-2'?'out':'in';
    $('station-name').textContent=stationName==='front-2'?'Departure station':'Arrival station';
    $('scan-title').textContent=direction==='in'?'Scan to check IN':'Scan to check OUT';
    $('scan-instruction').textContent=direction==='in'?'Arriving staff scan their badge here.':'Departing staff scan their badge here.';
    try { pending=JSON.parse(sessionStorage.getItem('pending:'+stationName)); } catch {pending=null;}
    if(pending){$('retry').hidden=false;$('scan-feedback').textContent='Previous scan needs confirmation. Retry it before scanning another badge.';}
  }
  navigate(role==='admin'?'dashboard':'kiosk');
}
$('role').onchange=()=>{
 const station=$('role').value==='station';
 $('station-fields').hidden=!station;$('office-fields').hidden=station;
 $('access-key').required=station;$('username').required=!station;$('password').required=!station;
};
$('login-form').addEventListener('submit',async e=> {
 e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;
 try { const station=$('role').value==='station';
       const path=station?'/session':'/office-session';
       const credentials=station?{role:'station',access_key:$('access-key').value}:{username:$('username').value.trim(),password:$('password').value};
       const identity=await(await api(path,{method:'POST',body:JSON.stringify(credentials)})).json();
       $('access-key').value='';$('password').value='';$('login-error').textContent='';await connect(identity); }
 catch(error){$('login-error').textContent=error.message;clearLocal();}
 finally{button.disabled=false;}
});
$('logout').onclick=lock;
document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>navigate(b.dataset.page));
function setRosterFilter(value){filter=value;rosterPage=1;document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('selected',x.dataset.filter===value));renderRoster();}
function renderRoster() {
 const query=$('search').value.toLowerCase(), live=!$('as-of').value, {planned,notArrived}=attentionLookup();
 // Planned-out and no-arrival views describe today, so they only apply to the live roster.
 const matches=t=>filter==='all'||t.presence===filter||(live&&filter==='planned'&&planned.has(t.id))||(live&&filter==='not-arrived'&&notArrived.has(t.id));
 const shown=staff.filter(t=>matches(t)&&(t.name.toLowerCase().includes(query)||t.teacher_id.toLowerCase().includes(query)));
 rosterPage=Math.max(1,Math.min(rosterPage,Math.ceil(shown.length/20)));
 pager('roster',rosterPage,shown.length);
 const tag=t=>{const plan=live&&planned.get(t.id);return plan?`<small class="tag-line">Planned out today · ${plan.substitute_name?'Cover: '+esc(plan.substitute_name):'needs cover'}</small>`:'';};
 $('roster').innerHTML=shown.slice((rosterPage-1)*20,rosterPage*20).map(t=>`<tr><td><div class="person"><span class="avatar">${esc(initials(t.name))}</span><div>${esc(t.name)}<small>${esc(t.teacher_id)}</small>${tag(t)}</div></div></td><td><span class="status ${t.presence==='in'?'inside':t.presence==='out'?'outside':''}">${t.presence==='unrecorded'?'Not recorded':t.inside?'● In':'○ Out'}</span></td><td>${esc(time(t.last_seen))}</td><td>${live?`<button class="text-button" data-roster-correct="${t.id}">Correct</button>`:''}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">No staff match this view.</td></tr>';
 $('in-count').textContent=staff.filter(t=>t.inside).length; $('out-count').textContent=staff.filter(t=>t.presence==='out').length; $('unknown-count').textContent=staff.filter(t=>t.presence==='unrecorded').length; $('roster-count').textContent=staff.length+' staff';
}
async function refresh() {
 if(role!=='admin'||!connected)return;
 const version=++refreshVersion;
 try {
  refreshCoverage();
  if(page==='dashboard')refreshAttention();
  const snapshot=$('as-of').value;
  const path=snapshot?'/presence?at='+Math.floor(new Date(snapshot).getTime()/1000):'/teachers';
  const rosterRequest=api(path).then(r=>r.json());
  const directoryRequest=snapshot?api('/teachers').then(r=>r.json()):rosterRequest;
  directoryRequest.then(directory=>{
    if(role!=='admin'||!connected||version!==refreshVersion)return;
    directoryStaff=directory;renderDirectory();
  }).catch(()=>{}); // The aggregate below reports directory failures.
  const activityDay=page==='history'?$('activity-day').value:'';
  const [roster,activity]=await Promise.all([rosterRequest,api('/events'+dayQuery(activityDay)).then(r=>r.json()),directoryRequest]);
  if(role!=='admin'||!connected||version!==refreshVersion)return;
  staff=roster.filter(t=>t.active||snapshot);events=activity;
  renderRoster();
  $('live-status').textContent=snapshot?'◷ Earlier time':'● Live';
  $('demo-banner').hidden=!staff.length||!staff.every(t=>t.teacher_id.startsWith('DEMO-'));
  $('sync').textContent='Updated '+new Date().toLocaleTimeString([], {hour:'numeric',minute:'2-digit'});
  $('recent').innerHTML=events.slice(0,6).map(e=>`<div class="activity-item"><span class="avatar">${e.direction==='in'?'↙':'↗'}</span><div><strong>${esc(e.name)}</strong><p>${e.reason?'Office correction':e.changed?'Checked':'Already'} ${esc(e.direction)} · ${esc(stationLabel(e.station))}</p><small>${esc(dateTime(e.occurred_at))}</small></div></div>`).join('')||'<div class="empty">No scans yet. Your school day starts here.</div>';
  renderActivity();
  $('notice').textContent='';$('notice').hidden=true;
 }catch(error){if(version!==refreshVersion)return;$('notice').textContent='Dashboard could not refresh. Displayed data may be stale. '+error.message;$('notice').hidden=false;$('sync').textContent='Connection lost — data may be stale';$('live-status').textContent='⚠ Stale';}
}
function renderActivity(){
 const query=$('activity-search').value.trim().toLowerCase(), kind=$('activity-kind').value, day=$('activity-day').value;
 const shown=events.filter(e=>(!query||e.name.toLowerCase().includes(query)||e.teacher_id.toLowerCase().includes(query))&&(kind==='all'||(kind==='corrections'?Boolean(e.reason):kind==='repeats'?!e.changed:!e.reason)));
 $('activity-count').textContent=`Showing ${shown.length} of ${events.length} ${day?'on '+new Date(day+'T12:00:00').toLocaleDateString([], {weekday:'short',month:'short',day:'numeric'}):'latest'}${events.length>=200?' (first 200; export for all)':''}`;
 $('event-table').innerHTML=shown.map(e=>`<tr><td>${esc(e.name)}<small>${esc(e.teacher_id)}</small></td><td>${e.reason?'Corrected to':e.changed?'Checked':'Already'} ${esc(e.direction)}</td><td>${esc(stationLabel(e.station))}</td><td>${esc(dateTime(e.occurred_at))}</td><td>${esc(e.reason || (e.changed?'':'Repeat scan; no status change'))}</td></tr>`).join('')||'<tr><td colspan="5" class="empty">No activity matches these filters.</td></tr>';
}
function pager(prefix,current,total){$(prefix+'-page').textContent=total?`${(current-1)*20+1}–${Math.min(current*20,total)} of ${total}`:'0 staff';$(prefix+'-prev').disabled=current<=1;$(prefix+'-next').disabled=current*20>=total;}
function renderDirectory(){
 const query=$('directory-search').value.toLowerCase();const shown=directoryStaff.filter(t=>t.name.toLowerCase().includes(query)||t.teacher_id.toLowerCase().includes(query));
 directoryPage=Math.max(1,Math.min(directoryPage,Math.ceil(shown.length/20)));pager('directory',directoryPage,shown.length);
 $('directory').innerHTML=shown.slice((directoryPage-1)*20,directoryPage*20).map(t=>`<tr><td>${esc(t.name)}<small>${t.presence==='unrecorded'?'Not recorded':t.inside?'Inside':'Outside'} · ${t.active?'Active':'Inactive'}</small></td><td>${esc(t.teacher_id)}</td><td>${t.active?`<button class="text-button directory-action" data-badge="${t.id}">Replace badge</button><button class="text-button directory-action" data-correct="${t.id}" data-inside="${t.inside}">Correct status</button><button class="text-button" data-deactivate="${t.id}">Deactivate</button>`:'Badge disabled'}</td></tr>`).join('');
}
$('search').oninput=()=>{rosterPage=1;renderRoster();};
$('directory-search').oninput=()=>{directoryPage=1;renderDirectory();};
$('roster-prev').onclick=()=>{rosterPage--;renderRoster();};$('roster-next').onclick=()=>{rosterPage++;renderRoster();};
$('directory-prev').onclick=()=>{directoryPage--;renderDirectory();};$('directory-next').onclick=()=>{directoryPage++;renderDirectory();};
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>setRosterFilter(b.dataset.filter));
$('roster').onclick=e=>{const b=e.target.closest('button[data-roster-correct]');if(b)openCorrection(directoryStaff.find(t=>t.id===Number(b.dataset.rosterCorrect)));};
$('activity-search').oninput=renderActivity;$('activity-kind').onchange=renderActivity;$('activity-day').onchange=refresh;
$('activity-clear').onclick=()=>{$('activity-day').value='';$('activity-search').value='';$('activity-kind').value='all';refresh();};
$('as-of').onchange=refresh; $('live').onclick=()=>{$('as-of').value='';refresh();};
async function showBadge(data) {
 const response=await api('/badge-image',{method:'POST',body:JSON.stringify({code:data.badge_code,direction:'in',request_id:uuid()})});
 if(badgeUrl) URL.revokeObjectURL(badgeUrl);badgeUrl=URL.createObjectURL(await response.blob());
 $('badge-img').src=badgeUrl;$('badge-name').textContent=data.name;$('badge').hidden=false;
}
$('teacher-form').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;try{const data=await(await api('/teachers',{method:'POST',body:JSON.stringify({name:$('teacher-name').value.trim(),teacher_id:$('teacher-id').value.trim()})})).json();$('teacher-form').reset();$('teacher-message').textContent='Teacher registered. Print the new badge below.';await showBadge(data);await refresh();}catch(error){$('teacher-message').textContent=error.message;}finally{button.disabled=false;}};
$('print').onclick=()=>window.print();
$('directory').onclick=e=>{const b=e.target.closest('button');if(!b)return;
 const person=directoryStaff.find(t=>t.id===Number(b.dataset.badge||b.dataset.correct||b.dataset.deactivate));if(!person)return;
 if(b.dataset.correct)openCorrection(person);
 if(b.dataset.badge)confirmAction({title:`Replace ${person.name}'s badge?`,body:'Their current badge stops working immediately. Print the new badge before they leave the office.',confirm:'Replace badge',danger:true,
   run:async()=>{await showBadge(await(await api('/teachers/'+person.id+'/badge',{method:'POST'})).json());$('teacher-message').textContent=`New badge ready for ${person.name}. Print it now; it is not shown again.`;$('badge').scrollIntoView({block:'nearest'});refresh();}});
 if(b.dataset.deactivate)confirmAction({title:`Deactivate ${person.name}?`,body:'Their badge stops working and they leave the active roster. Scan history and planned coverage history are kept. They must be recorded OUT first.',confirm:'Deactivate',danger:true,
   run:async()=>{await api('/teachers/'+person.id,{method:'PATCH'});showToast(`${person.name} was deactivated.`);refresh();}});
};
document.querySelectorAll('.export').forEach(b=>b.onclick=async()=>{try{const day=$('activity-day').value;const blob=await(await api('/export'+dayQuery(day))).blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='staff-checkins'+(day?'-'+day:'')+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){$('notice').textContent=error.message;$('notice').hidden=false;}});
async function sendScan(){if(busy||role!=='station'||!pending)return;busy=true;$('scan-code').disabled=true;$('retry').hidden=true;$('scan-feedback').className='';$('scan-feedback').textContent='Recording scan…';try{const result=await(await api('/scans',{method:'POST',body:JSON.stringify(pending)})).json();$('scan-feedback').className='success';$('scan-feedback').textContent=result.name+' · '+result.message+' · '+time(result.occurred_at);pending=null;sessionStorage.removeItem('pending:'+stationName);clearTimeout(scanResetTimer);scanResetTimer=setTimeout(()=>{if(!pending&&!busy&&role==='station'){$('scan-feedback').className='';$('scan-feedback').textContent='Ready for the next badge';}},8000);}catch(error){$('scan-feedback').textContent=error.message+' — scan has not been confirmed.';$('scan-feedback').className='error';if(error.status && error.status<500){pending=null;sessionStorage.removeItem('pending:'+stationName);}else if(connected){$('retry').hidden=false;}}finally{busy=false;$('scan-code').disabled=false;if(!pending)$('scan-code').value='';$('scan-code').focus();}}
$('scan-form').onsubmit=e=>{e.preventDefault();if(busy||role!=='station')return;if(pending){$('scan-feedback').textContent='Retry the previous scan before scanning another badge.';return;}const code=$('scan-code').value.trim();if(!code)return;pending={code,direction,request_id:uuid()};sessionStorage.setItem('pending:'+stationName,JSON.stringify(pending));sendScan();};
$('retry').onclick=sendScan;
$('kiosk').addEventListener('click',e=>{if(role==='station' && !pending && !e.target.closest('button,input'))$('scan-code').focus();});
// Unknown badges and validation errors are definitive failures, not ambiguous network failures.
// The retry button preserves the request ID so a lost response cannot record twice.
setInterval(()=>{$('clock').textContent=new Date().toLocaleDateString([], {weekday:'short',month:'short',day:'numeric'})+' · '+new Date().toLocaleTimeString([], {hour:'numeric',minute:'2-digit'});},1000);
setInterval(()=>{if(page==='dashboard'||page==='history'||page==='coverage')refresh();},5000);
// Remove legacy key storage from earlier pilot versions. Browser sessions use HttpOnly cookies.
sessionStorage.removeItem('key');sessionStorage.removeItem('role');
api('/session').then(r=>r.json()).then(connect).catch(()=>clearLocal());
setInterval(()=>{if(connected && Date.now()/1000>=sessionExpiry){clearLocal();$('login-error').textContent='Session expired. Please sign in again.';}},1000);
