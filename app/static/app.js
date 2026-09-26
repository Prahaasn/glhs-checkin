const $ = id => document.getElementById(id);
let role = sessionStorage.getItem('role'), key = sessionStorage.getItem('key');
let staff = [], events = [], filter = 'all', page = 'dashboard', direction = 'in', busy = false, pending = null, badgeUrl, refreshVersion=0;
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time = epoch => epoch ? new Date(epoch * 1000).toLocaleTimeString([], {hour:'numeric', minute:'2-digit'}) : 'No scans yet';
const dateTime = epoch => new Date(epoch * 1000).toLocaleString();
const initials = name => name.split(' ').map(x => x[0]).slice(0,2).join('').toUpperCase();
const uuid = () => crypto.randomUUID ? crypto.randomUUID() : '10000000-1000-4000-8000-100000000000'.replace(/[018]/g,c=>(c^crypto.getRandomValues(new Uint8Array(1))[0]&15>>c/4).toString(16));
async function api(path, options = {}) {
  const response = await fetch('/api' + path, {...options, headers: {'Content-Type':'application/json', [role === 'admin' ? 'X-Admin-Key' : 'X-Station-Key']: key || '', ...options.headers}});
  if (!response.ok) { let detail = 'Request failed'; try { const data = await response.json(); detail = typeof data.detail === 'string' ? data.detail : 'Please check the entered values.'; } catch {} if(response.status===401 && key) lock(); const error = new Error(detail); error.status=response.status; throw error; }
  return response;
}
function lock() { refreshVersion++; sessionStorage.clear(); key = role = null; staff=[]; events=[]; $('workspace').hidden=true; $('login').hidden=false; $('access-key').value=''; $('scan-code').value=''; $('roster').replaceChildren(); $('directory').replaceChildren(); $('event-table').replaceChildren(); $('recent').replaceChildren(); $('badge').hidden=true; if(badgeUrl)URL.revokeObjectURL(badgeUrl); pending=null; }
function navigate(next) {
  if (!key) return;
  if(role === 'station' && next !== 'kiosk') return;
  page=next;
  document.querySelectorAll('.page').forEach(p=>p.hidden=p.id!==next);
  document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b.dataset.page===next));
  if(role==='admin' && next!=='kiosk') refresh();
  if(next==='kiosk') { $('scan-code').focus(); if(role==='admin') $('scan-feedback').textContent='Lock this computer and sign in with a station key to scan.'; }
}
async function connect() {
  if(role === 'admin') await api('/teachers');
  else { const data = await (await api('/station')).json(); $('station-name').textContent='Connected: '+data.station; }
  sessionStorage.setItem('role',role); sessionStorage.setItem('key',key);
  $('login').hidden=true; $('workspace').hidden=false;
  document.querySelectorAll('.nav').forEach(b=>b.hidden=role==='station' && b.dataset.page!=='kiosk');
  navigate(role==='admin'?'dashboard':'kiosk');
  if(role==='admin') await refresh();
}
$('login-form').addEventListener('submit',async e=> {e.preventDefault();role=$('role').value;key=$('access-key').value;try {await connect();$('access-key').value='';$('login-error').textContent='';} catch(error){$('login-error').textContent=error.message;key=null;}});
$('logout').onclick=lock;
document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>navigate(b.dataset.page));
function renderRoster() {
 const query=$('search').value.toLowerCase();
 const shown=staff.filter(t=>(filter==='all'||t.inside===(filter==='in'))&&(t.name.toLowerCase().includes(query)||t.teacher_id.toLowerCase().includes(query)));
 $('roster').innerHTML=shown.map(t=>`<tr><td><div class="person"><span class="avatar">${esc(initials(t.name))}</span><div>${esc(t.name)}<small>${esc(t.teacher_id)}</small></div></div></td><td><span class="status ${t.inside?'inside':''}">${t.inside?'● Inside':'○ Outside'}</span></td><td>${esc(time(t.last_seen))}</td></tr>`).join('')||'<tr><td colspan="3" class="empty">No staff to show. Add teachers in Teachers & badges.</td></tr>';
 $('in-count').textContent=staff.filter(t=>t.inside).length; $('out-count').textContent=staff.filter(t=>!t.inside).length; $('total-count').textContent=staff.length; $('roster-count').textContent=staff.length+' staff';
}
async function refresh() {
 if(role!=='admin'||!key)return;
 const version=++refreshVersion;
 try {
  const snapshot=$('as-of').value;
  const path=snapshot?'/presence?at='+Math.floor(new Date(snapshot).getTime()/1000):'/teachers';
  const [roster,activity,directory]=await Promise.all([api(path).then(r=>r.json()),api('/events').then(r=>r.json()),api('/teachers').then(r=>r.json())]);
  if(role!=='admin'||!key||version!==refreshVersion)return;
  staff=roster.filter(t=>t.active||snapshot);events=activity;
  renderRoster();
  document.querySelector('.live-pill').textContent=snapshot?'◷ Snapshot':'● Live';
  $('subtitle').textContent=snapshot?'Recorded presence at '+new Date(snapshot).toLocaleString():'A little less paperwork. A lot more clarity.';
  $('sync').textContent='Updated '+new Date().toLocaleTimeString([], {hour:'numeric',minute:'2-digit'});
  $('recent').innerHTML=events.slice(0,6).map(e=>`<div class="activity-item"><span class="avatar">${e.direction==='in'?'↙':'↗'}</span><div><strong>${esc(e.name)}</strong><p>${e.changed?'Checked':'Already'} ${esc(e.direction)} · ${esc(e.station)}</p><small>${esc(dateTime(e.occurred_at))}</small></div></div>`).join('')||'<div class="empty">No scans yet. Your school day starts here.</div>';
  $('event-table').innerHTML=events.map(e=>`<tr><td>${esc(e.name)}<small>${esc(e.teacher_id)}</small></td><td>${e.changed?'Checked':'Already'} ${esc(e.direction)}</td><td>${esc(e.station)}</td><td>${esc(dateTime(e.occurred_at))}</td><td>${esc(e.reason || (e.changed?'':'Repeat scan; no status change'))}</td></tr>`).join('');
  $('directory').innerHTML=directory.map(t=>`<tr><td>${esc(t.name)}<small>${t.inside?'Inside':'Outside'} · ${t.active?'Active':'Inactive'}</small></td><td>${esc(t.teacher_id)}</td><td>${t.active?`<button class="text-button directory-action" data-badge="${t.id}">Replace badge</button><button class="text-button directory-action" data-correct="${t.id}" data-inside="${t.inside}">Correct status</button><button class="text-button" data-deactivate="${t.id}">Deactivate</button>`:'Badge disabled'}</td></tr>`).join('');
  $('notice').textContent='';
 }catch(error){if(version!==refreshVersion)return;$('notice').textContent='Dashboard could not refresh. Displayed data may be stale. '+error.message;$('sync').textContent='Connection lost — data may be stale';}
}
$('search').oninput=renderRoster;
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('selected',x===b));renderRoster();});
$('as-of').onchange=refresh; $('live').onclick=()=>{$('as-of').value='';refresh();};
async function showBadge(data) {
 const response=await api('/badge-image',{method:'POST',body:JSON.stringify({code:data.badge_code,direction:'in',request_id:uuid()})});
 if(badgeUrl) URL.revokeObjectURL(badgeUrl);badgeUrl=URL.createObjectURL(await response.blob());
 $('badge-img').src=badgeUrl, refreshVersion=0;$('badge-name').textContent=data.name;$('badge').hidden=false;
}
$('teacher-form').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;try{const data=await(await api('/teachers',{method:'POST',body:JSON.stringify({name:$('teacher-name').value.trim(),teacher_id:$('teacher-id').value.trim()})})).json();$('teacher-form').reset();$('teacher-message').textContent='Teacher registered. Print the new badge below.';await showBadge(data);await refresh();}catch(error){$('teacher-message').textContent=error.message;}finally{button.disabled=false;}};
$('print').onclick=()=>window.print();
$('directory').onclick=async e=>{const b=e.target.closest('button');if(!b)return;b.disabled=true;try{
 if(b.dataset.badge){if(!confirm('Replace this badge? The old badge will stop working.'))return;await showBadge(await(await api('/teachers/'+b.dataset.badge+'/badge',{method:'POST'})).json());}
 if(b.dataset.deactivate){if(!confirm('Deactivate this teacher and their badge?'))return;await api('/teachers/'+b.dataset.deactivate,{method:'PATCH'});}
 if(b.dataset.correct){const reason=prompt('Why is this status being corrected? (At least 3 characters)');if(!reason)return;await api('/teachers/'+b.dataset.correct+'/correction',{method:'POST',body:JSON.stringify({direction:b.dataset.inside==='true'?'out':'in',request_id:uuid(),reason})});}
 await refresh();
 }catch(error){$('teacher-message').textContent=error.message;}finally{b.disabled=false;}};
document.querySelectorAll('.export').forEach(b=>b.onclick=async()=>{try{const blob=await(await api('/export')).blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='staff-checkins.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){$('notice').textContent=error.message;}});
function setMode(mode){if(busy||pending)return;direction=mode;sessionStorage.setItem('direction',mode);$('mode-in').classList.toggle('selected',mode==='in');$('mode-out').classList.toggle('selected',mode==='out');$('scan-title').textContent=mode==='in'?'Ready for arrivals':'Ready for departures';$('scan-code').focus();}
$('mode-in').onclick=()=>setMode('in');$('mode-out').onclick=()=>setMode('out');
async function sendScan(){if(busy||role!=='station'||!pending)return;busy=true;$('scan-code').disabled=true;$('retry').hidden=true;$('scan-feedback').className='';$('scan-feedback').textContent='Recording scan…';try{const result=await(await api('/scans',{method:'POST',body:JSON.stringify(pending)})).json();$('scan-feedback').textContent=result.name+' · '+result.message;pending=null;}catch(error){$('scan-feedback').textContent=error.message+' — scan has not been confirmed.';$('scan-feedback').className='error';if(error.status && error.status<500){pending=null;}else if(key){$('retry').hidden=false;}}finally{busy=false;$('scan-code').disabled=false;if(!pending)$('scan-code').value='';$('scan-code').focus();}}
$('scan-form').onsubmit=e=>{e.preventDefault();if(busy||role!=='station')return;if(pending){$('scan-feedback').textContent='Retry the previous scan before scanning another badge.';return;}const code=$('scan-code').value.trim();if(!code)return;pending={code,direction,request_id:uuid()};sendScan();};
$('retry').onclick=sendScan;
// Unknown badges and validation errors are definitive failures, not ambiguous network failures.
// The retry button preserves the request ID so a lost response cannot record twice.
setInterval(()=>{$('clock').textContent=new Date().toLocaleDateString([], {weekday:'short',month:'short',day:'numeric'})+' · '+new Date().toLocaleTimeString([], {hour:'numeric',minute:'2-digit'});},1000);
setInterval(()=>{if(page==='dashboard'||page==='history')refresh();},5000);
setMode(sessionStorage.getItem('direction')||'in');if(key)connect().catch(error=>{lock();$('login-error').textContent=error.message;});
