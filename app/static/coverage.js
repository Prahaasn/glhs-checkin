let coverageEntries = [], coverageVersion = 0, coverageAuditVersion = 0;
let coverageEditing = null, coverageAction = 'create';
let coverageLoadedDay = null, coverageDialogVersion = 0;
let coverageView = 'day', coverageToday = null, coverageCheckVersion = 0, coverageCheckTimer = null;
const MAX_PLAN_DAYS = 90, UPCOMING_DAYS = 14, SHORT_DAY = {weekday:'short', month:'short', day:'numeric'};

// School dates are calendar days, so date math stays in UTC to avoid daylight-saving shifts.
const isoDate = iso => new Date(iso + 'T00:00:00Z');
const addDays = (iso, count) => { const date = isoDate(iso); date.setUTCDate(date.getUTCDate() + count); return date.toISOString().slice(0, 10); };
const isWeekend = iso => [0, 6].includes(isoDate(iso).getUTCDay());
const dayLabel = (iso, options = SHORT_DAY) => isoDate(iso).toLocaleDateString([], {...options, timeZone:'UTC'});
const personName = value => String(value || '').trim().replace(/\s+/g, ' ').toLowerCase();
const plural = (count, word) => count + ' ' + word + (count === 1 ? '' : 's');

function planDates(start, count) {
  // Mirrors the server: the chosen first day, then the following weekdays.
  const days = [start];
  for (let current = start; days.length < count;) {
    current = addDays(current, 1);
    if (!isWeekend(current)) days.push(current);
  }
  return days;
}

function stepSchoolDay(iso, step) {
  let next = addDays(iso, step);
  while (isWeekend(next)) next = addDays(next, step);
  return next;
}

function laterDays(entry) {
  return (entry?.series?.days || []).filter(day => day.day > entry.day && day.cancelled === entry.cancelled);
}

function seriesNote(entry) {
  const series = entry.series;
  if (!series) return '';
  return 'Day ' + series.position + ' of ' + series.total + ' · ' + dayLabel(series.first_day) + ' – ' + dayLabel(series.last_day);
}

function clearCoverageRows() {
  coverageEntries = []; coverageLoadedDay = null;
  $('coverage-rows').innerHTML = '<tr><td colspan="5" class="empty">Loading planned absences…</td></tr>';
  $('coverage-upcoming-list').innerHTML = '';
  ['coverage-planned','coverage-covered','coverage-unassigned'].forEach(id => $(id).textContent = '—');
}

function coverageNotice(message, error = false) {
  $('coverage-message').textContent = message;
  $('coverage-message').dataset.error = String(error);
}

function clearCoverage() {
  coverageVersion++; coverageAuditVersion++; coverageDialogVersion++; coverageCheckVersion++;
  coverageEntries = []; coverageLoadedDay = null; coverageEditing = null; coverageToday = null;
  if ($('coverage-dialog').open) $('coverage-dialog').close();
  $('coverage-form').reset();
  $('coverage-day').value = '';
  $('coverage-cancelled').checked = false;
  ['coverage-rows','coverage-teacher','coverage-audit-list','coverage-upcoming-list','substitute-options'].forEach(id => $(id).replaceChildren());
  setCoverageView('day');
  $('coverage-audit').hidden = true;
  $('coverage-audit-title').textContent = 'Coverage changes';
  $('coverage-sync').textContent = 'Waiting for server';
  $('coverage-summary-text').textContent = 'Loading coverage…';
  coverageNotice('');
  ['coverage-planned','coverage-covered','coverage-unassigned'].forEach(id => $(id).textContent = '—');
}

function setCoverageView(view) {
  coverageView = view;
  const upcoming = view === 'upcoming';
  [['coverage-view-day', !upcoming], ['coverage-view-upcoming', upcoming]].forEach(([id, selected]) => {
    $(id).className = 'segment' + (selected ? ' selected' : '');
    $(id).setAttribute('aria-pressed', String(selected));
  });
  $('coverage-day-panel').hidden = upcoming;
  $('coverage-scroll-hint').hidden = upcoming;
  $('coverage-upcoming').hidden = !upcoming;
  $('coverage-cancelled-label').hidden = upcoming;
  $('coverage-day-label').textContent = upcoming ? 'Starting' : 'School date';
  $('coverage-planned-note').textContent = upcoming ? 'In the next two weeks' : 'For the selected school date';
}

function dayRow(entry, bookings) {
  const status = entry.cancelled ? 'Cancelled' : entry.substitute_name ? 'Assigned' : 'Needs cover';
  const current = entry.presence === 'unrecorded' ? 'Not recorded' : entry.presence === 'in' ? 'In' : 'Out';
  const others = entry.cancelled || !entry.substitute_name ? [] :
    (bookings.get(personName(entry.substitute_name)) || []).filter(other => other.id !== entry.id);
  const warning = others.length ? '<small class="warning-text">Also covering ' + esc(others.map(other => other.name).join(', ')) + '</small>' : '';
  const scanWarning = !entry.cancelled && entry.presence === 'in' && entry.day === coverageToday
    ? '<small class="warning-text">Recorded IN while planned out</small>' : '';
  const actions = entry.cancelled
    ? '<button class="text-button" data-coverage-action="restore" data-absence="' + entry.id + '">Restore</button>'
    : '<button class="text-button" data-coverage-action="edit" data-absence="' + entry.id + '">Edit cover</button><button class="text-button" data-coverage-action="cancel" data-absence="' + entry.id + '">Cancel</button>';
  return '<tr><td><strong>' + esc(entry.name) + '</strong><small>' + esc(entry.teacher_id) + (entry.active ? '' : ' · Inactive') + '</small>' +
    (entry.series ? '<small class="series-note">' + esc(seriesNote(entry)) + '</small>' : '') + '</td>' +
    '<td>' + esc(entry.substitute_name || 'Not assigned') + '<small class="' + (status === 'Needs cover' ? 'needs-text' : '') + '">' + status + '</small>' + warning + '</td>' +
    '<td><span class="status ' + (entry.presence === 'in' ? 'inside' : entry.presence === 'out' ? 'outside' : '') + '">' + current + '</span>' + scanWarning + '</td>' +
    '<td>' + esc(dateTime(entry.updated_at)) + '<small>' + esc(entry.updated_by) + '</small></td>' +
    '<td class="coverage-actions">' + actions + '<button class="text-button" data-coverage-action="history" data-absence="' + entry.id + '">History</button></td></tr>';
}

function substituteBookings(entries) {
  const bookings = new Map();
  entries.filter(entry => !entry.cancelled && entry.substitute_name).forEach(entry => {
    const key = personName(entry.substitute_name);
    bookings.set(key, [...(bookings.get(key) || []), entry]);
  });
  return bookings;
}

function renderUpcoming(data) {
  $('coverage-upcoming-list').innerHTML = data.days.map(day => {
    const bookings = substituteBookings(day.entries);
    const items = day.entries.map(entry => {
      const double = entry.substitute_name && bookings.get(personName(entry.substitute_name)).length > 1;
      return '<li><span><strong>' + esc(entry.name) + '</strong><small>' + esc(seriesNote(entry) || entry.teacher_id) + '</small></span>' +
        (entry.substitute_name
          ? '<span class="upcoming-sub">' + esc(entry.substitute_name) + (double ? '<small class="warning-text">Double-booked this day</small>' : '') + '</span>'
          : '<span class="status needs">Needs cover</span>') + '</li>';
    }).join('');
    return '<section class="upcoming-day"><div class="upcoming-heading"><div><strong>' + esc(dayLabel(day.day, {weekday:'long', month:'short', day:'numeric'})) +
      (day.day === data.today ? ' · Today' : '') + '</strong><small>' + plural(day.planned, 'absence') + ' · ' +
      (day.unassigned ? day.unassigned + ' need cover' : 'all covered') + '</small></div>' +
      '<button class="text-button" data-open-day="' + day.day + '">Open day</button></div><ul>' + items + '</ul></section>';
  }).join('') || '<p class="empty">No planned absences in these two weeks.</p>';
}

async function refreshCoverage() {
  if (role !== 'admin' || !connected) return;
  const version = ++coverageVersion;
  const day = page === 'coverage' ? $('coverage-day').value : '';
  const upcoming = Boolean(day) && coverageView === 'upcoming';
  const params = new URLSearchParams();
  if (day) {
    if (upcoming) { params.set('start', day); params.set('end', addDays(day, UPCOMING_DAYS - 1)); }
    else params.set('day', day);
    if (coverageLoadedDay !== coverageView + ':' + day) clearCoverageRows();
  }
  if (day && !upcoming && $('coverage-cancelled').checked) params.set('include_cancelled', 'true');
  try {
    const data = await (await api((upcoming ? '/absences/range?' : '/absences?') + params)).json();
    if (version !== coverageVersion || role !== 'admin' || !connected) return;
    coverageToday = data.today;
    if (!$('coverage-day').value) $('coverage-day').value = data.today;
    if ($('coverage-message').dataset.error === 'true') coverageNotice('');
    if (page === 'dashboard') {
      $('coverage-summary-text').textContent = data.planned + ' planned · ' + data.covered + ' assigned · ' + data.unassigned + ' need cover';
    }
    $('coverage-planned').textContent = data.planned;
    $('coverage-covered').textContent = data.covered;
    $('coverage-unassigned').textContent = data.unassigned;
    $('coverage-sync').textContent = 'Updated ' + new Date().toLocaleTimeString([], {hour:'numeric',minute:'2-digit'});
    if (upcoming) {
      coverageEntries = []; coverageLoadedDay = 'upcoming:' + data.start;
      renderUpcoming(data);
      return;
    }
    coverageEntries = data.entries;
    coverageLoadedDay = 'day:' + data.day;
    const bookings = substituteBookings(coverageEntries);
    $('coverage-rows').innerHTML = coverageEntries.map(entry => dayRow(entry, bookings)).join('') ||
      '<tr><td colspan="5" class="empty">No planned absences for this date. Use Plan absence to add one.</td></tr>';
  } catch (error) {
    if (version !== coverageVersion || role !== 'admin' || !connected) return;
    $('coverage-sync').textContent = 'Coverage may be stale';
    coverageNotice('Could not refresh planned coverage. ' + error.message, true);
    $('coverage-summary-text').textContent = 'Coverage unavailable — open Absences & cover to retry.';
  }
}

function renderCoveragePreview() {
  if (coverageAction !== 'create') { $('coverage-preview').textContent = ''; return; }
  const start = $('coverage-form-day').value, count = Number($('coverage-days').value);
  $('coverage-preview').dataset.warning = 'false';
  if (!start) { $('coverage-preview').textContent = 'Choose the first day out.'; return; }
  if (!Number.isInteger(count) || count < 1 || count > MAX_PLAN_DAYS) {
    $('coverage-preview').textContent = 'Enter 1 to ' + MAX_PLAN_DAYS + ' school days.';
    $('coverage-preview').dataset.warning = 'true';
    return;
  }
  const days = planDates(start, count);
  const weekendStart = isWeekend(start) ? ' ' + dayLabel(start, {weekday:'long'}) + ' is a weekend day — check the first day out.' : '';
  $('coverage-preview').dataset.warning = String(Boolean(weekendStart));
  $('coverage-preview').textContent = count === 1
    ? 'Out ' + dayLabel(start, {weekday:'long', month:'long', day:'numeric'}) + '.' + weekendStart
    : 'Out ' + dayLabel(days[0]) + ' through ' + dayLabel(days[days.length - 1]) + ' · ' + count + ' school days, weekends skipped' +
      (count <= 10 ? ' (' + days.map(day => dayLabel(day, {weekday:'short'}) + ' ' + isoDate(day).getUTCDate()).join(', ') + ').' : '.') + weekendStart;
  document.querySelectorAll('#coverage-days-picks [data-days]').forEach(button =>
    button.className = 'chip' + (Number(button.dataset.days) === count ? ' selected' : ''));
}

function renderCoverageScope(entry, action) {
  const later = laterDays(entry);
  $('coverage-scope').hidden = !later.length;
  if (!later.length) return;
  const last = later[later.length - 1].day;
  $('coverage-scope-day-text').textContent = 'Only ' + dayLabel(entry.day);
  $('coverage-scope-following-text').textContent = dayLabel(entry.day) + ' and ' + plural(later.length, 'later day') +
    ' (through ' + dayLabel(last) + ')';
  // Assigning cover usually spans the rest of a plan; cancelling or restoring starts narrow.
  const following = action === 'edit';
  $('coverage-scope-following').checked = following;
  $('coverage-scope-day').checked = !following;
}

function coverageDialogDates() {
  if (coverageAction === 'create') {
    const start = $('coverage-form-day').value, count = Number($('coverage-days').value);
    return start && Number.isInteger(count) && count >= 1 && count <= MAX_PLAN_DAYS ? planDates(start, count) : [];
  }
  if (!coverageEditing) return [];
  return [coverageEditing.day, ...($('coverage-scope-following').checked ? laterDays(coverageEditing).map(day => day.day) : [])];
}

async function checkCoverageConflicts() {
  const version = ++coverageCheckVersion;
  $('coverage-conflict').textContent = '';
  const dates = coverageDialogDates();
  const name = $('coverage-substitute').value.trim();
  const teacher = coverageEditing ? coverageEditing.teacher_pk : Number($('coverage-teacher').value);
  if (!dates.length || coverageAction === 'cancel' || (!name && (coverageAction !== 'create' || !teacher))) return;
  const start = dates[0], end = [...dates].sort().pop();
  try {
    const data = await (await api('/absences/range?start=' + start + '&end=' + (end < addDays(start, 61) ? end : addDays(start, 61)))).json();
    if (version !== coverageCheckVersion || !$('coverage-dialog').open) return;
    const wanted = new Set(dates), warnings = [];
    data.days.filter(day => wanted.has(day.day)).forEach(day => day.entries.forEach(other => {
      if (coverageAction === 'create' && other.teacher_pk === teacher) {
        warnings.push(other.name + ' already has an absence on ' + dayLabel(day.day) + '; saving will be refused.');
      } else if (name && other.teacher_pk !== teacher && personName(other.substitute_name) === personName(name)) {
        warnings.push(other.substitute_name + ' is already covering ' + other.name + ' on ' + dayLabel(day.day) + '.');
      }
    }));
    $('coverage-conflict').textContent = warnings.slice(0, 3).join(' ') + (warnings.length > 3 ? ' (+' + (warnings.length - 3) + ' more)' : '');
  } catch { /* Advisory only: the save still validates on the server. */ }
}

function scheduleCoverageCheck() {
  clearTimeout(coverageCheckTimer);
  coverageCheckTimer = setTimeout(checkCoverageConflicts, 250);
}

async function loadSubstituteSuggestions() {
  try {
    const names = await (await api('/substitutes')).json();
    if (role !== 'admin' || !connected) return;
    $('substitute-options').innerHTML = names.map(item => '<option value="' + esc(item.name) + '"></option>').join('');
  } catch { /* Suggestions are optional; typing a name still works. */ }
}

function openCoverage(action, entry = null) {
  coverageDialogVersion++; coverageCheckVersion++;
  $('coverage-save').disabled = false;
  coverageAction = action; coverageEditing = entry ? {...entry} : null;
  $('coverage-form-error').textContent = '';
  $('coverage-conflict').textContent = '';
  const staffOptions = directoryStaff.filter(person => person.active || person.id === entry?.teacher_pk);
  $('coverage-teacher').innerHTML = '<option value="">Choose a staff member</option>' + staffOptions.map(person => '<option value="' + person.id + '">' + esc(person.name) + ' · ' + esc(person.teacher_id) + '</option>').join('');
  $('coverage-teacher').value = entry ? entry.teacher_pk : '';
  $('coverage-teacher').disabled = action !== 'create';
  $('coverage-form-day').value = entry ? entry.day : $('coverage-day').value;
  $('coverage-form-day').disabled = action !== 'create';
  $('coverage-form-day-label').textContent = action === 'create' ? 'First day out' : 'School date';
  $('coverage-days').value = '1';
  $('coverage-days').disabled = action !== 'create';
  $('coverage-days-field').hidden = action !== 'create';
  $('coverage-days-picks').hidden = action !== 'create';
  $('coverage-substitute').value = entry?.substitute_name || '';
  $('coverage-substitute').disabled = action === 'cancel';
  if (action === 'create') $('coverage-scope').hidden = true; else renderCoverageScope(entry, action);
  renderCoveragePreview();
  const titles = {create:'Plan an absence', edit:'Edit substitute coverage', cancel:'Cancel planned absence', restore:'Restore planned absence'};
  const buttons = {create:'Save absence', edit:'Save cover', cancel:'Cancel absence', restore:'Restore absence'};
  $('coverage-dialog-title').textContent = titles[action];
  $('coverage-save').textContent = buttons[action];
  $('coverage-save').className = action === 'cancel' ? 'primary danger' : 'primary';
  $('coverage-dialog-description').textContent = action === 'cancel'
    ? 'Review the staff member and dates. Cancellation stays in the coverage history.'
    : action === 'create' ? 'Choose the first day out and how many school days. You can assign cover now or later.'
    : 'This records planned coverage. Scan status is recorded separately.';
  $('coverage-dialog').showModal();
  (action === 'create' ? $('coverage-teacher') : $('coverage-save')).focus();
  if (action !== 'cancel') loadSubstituteSuggestions();
  scheduleCoverageCheck();
}

async function showCoverageHistory(entry) {
  const version = ++coverageAuditVersion;
  try {
    const changes = await (await api('/absences/' + entry.id + '/changes')).json();
    if (version !== coverageAuditVersion || role !== 'admin' || !connected) return;
    $('coverage-audit-title').textContent = entry.name + ' · ' + entry.day;
    $('coverage-audit-list').innerHTML = changes.map(change => '<li><strong>' + esc(change.action) + '</strong> · ' + esc(change.actor) + '<small>' + esc(dateTime(change.occurred_at)) + ' · ' + esc(change.substitute_name || 'No substitute assigned') + '</small></li>').join('');
    $('coverage-audit').hidden = false;
    $('coverage-audit').scrollIntoView({block:'nearest'});
  } catch (error) { if (version === coverageAuditVersion && connected) coverageNotice(error.message, true); }
}

function savedMessage(action, result, count) {
  const days = plural(count, 'school day');
  if (action === 'create') return 'Planned ' + days + ' for ' + result.name + (result.substitute_name ? ' with ' + result.substitute_name + '.' : '. Cover is still needed.');
  if (action === 'cancel') return 'Absence cancelled for ' + days + '. The entries and history are preserved.';
  if (action === 'restore') return 'Absence restored for ' + days + '.';
  return 'Cover saved for ' + result.name + ' on ' + days + '.';
}

document.addEventListener('DOMContentLoaded', () => {
  $('coverage-add').onclick = () => openCoverage('create');
  $('coverage-dialog-close').onclick = () => { coverageDialogVersion++; coverageCheckVersion++; $('coverage-dialog').close(); };
  $('coverage-dialog').addEventListener('cancel', () => { coverageDialogVersion++; coverageCheckVersion++; });
  $('coverage-audit-close').onclick = () => { coverageAuditVersion++; $('coverage-audit').hidden = true; };
  const changeFilter = () => {
    coverageAuditVersion++; $('coverage-audit').hidden = true; coverageNotice('');
    clearCoverageRows(); refreshCoverage();
  };
  const moveTo = day => { $('coverage-day').value = day; changeFilter(); };
  const step = direction => { const from = $('coverage-day').value || coverageToday; if (from) moveTo(stepSchoolDay(from, direction)); };
  $('coverage-day').onchange = changeFilter;
  $('coverage-cancelled').onchange = changeFilter;
  $('coverage-prev').onclick = () => step(-1);
  $('coverage-next').onclick = () => step(1);
  $('coverage-today').onclick = () => { if (coverageToday) moveTo(coverageToday); };
  $('coverage-view-day').onclick = () => { setCoverageView('day'); changeFilter(); };
  $('coverage-view-upcoming').onclick = () => { setCoverageView('upcoming'); changeFilter(); };
  $('coverage-upcoming-list').onclick = event => {
    const button = event.target.closest('button[data-open-day]');
    if (!button) return;
    setCoverageView('day'); moveTo(button.dataset.openDay);
  };
  $('coverage-days-picks').onclick = event => {
    const button = event.target.closest('button[data-days]');
    if (!button) return;
    $('coverage-days').value = button.dataset.days;
    renderCoveragePreview(); scheduleCoverageCheck();
  };
  ['coverage-form-day','coverage-days'].forEach(id => $(id).addEventListener('input', () => { renderCoveragePreview(); scheduleCoverageCheck(); }));
  ['coverage-teacher','coverage-scope-day','coverage-scope-following'].forEach(id => $(id).addEventListener('change', scheduleCoverageCheck));
  $('coverage-substitute').addEventListener('input', scheduleCoverageCheck);
  $('coverage-rows').onclick = event => {
    const button = event.target.closest('button[data-absence]');
    if (!button) return;
    const entry = coverageEntries.find(item => item.id === Number(button.dataset.absence));
    if (!entry) return;
    if (button.dataset.coverageAction === 'history') showCoverageHistory(entry);
    else openCoverage(button.dataset.coverageAction, entry);
  };
  $('coverage-form').onsubmit = async event => {
    event.preventDefault();
    const action = coverageAction, entry = coverageEditing;
    const dialogVersion = coverageDialogVersion;
    $('coverage-save').disabled = true; $('coverage-form-error').textContent = '';
    try {
      const payload = {substitute_name: $('coverage-substitute').value.trim() || null};
      if (entry) {
        payload.version = entry.version; payload.cancelled = action === 'cancel';
        if (!$('coverage-scope').hidden && $('coverage-scope-following').checked) {
          payload.scope = 'following';
          payload.versions = Object.fromEntries(laterDays(entry).map(day => [day.id, day.version]));
        }
      } else {
        payload.teacher_pk = Number($('coverage-teacher').value); payload.day = $('coverage-form-day').value;
        payload.school_days = Number($('coverage-days').value);
      }
      const result = await (await api('/absences' + (entry ? '/' + entry.id : ''), {
        method: entry ? 'PATCH' : 'POST', body: JSON.stringify(payload)
      })).json();
      if (!connected || role !== 'admin' || dialogVersion !== coverageDialogVersion) return;
      $('coverage-dialog').close(); coverageCheckVersion++;
      $('coverage-day').value = result.day;
      if (result.cancelled) $('coverage-cancelled').checked = true;
      setCoverageView('day');
      navigate('coverage');
      const count = entry ? Math.max(result.changed_days ?? 1, 1) : (result.series ? result.series.total : 1);
      coverageNotice(savedMessage(action, result, count));
      await refreshCoverage();
    } catch (error) {
      if (connected && dialogVersion === coverageDialogVersion) $('coverage-form-error').textContent = error.message + (error.status ? '' : ' Refresh this date before retrying; the save was not confirmed.');
    } finally { if (dialogVersion === coverageDialogVersion) $('coverage-save').disabled = false; }
  };
});
