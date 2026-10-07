let coverageEntries = [], coverageVersion = 0, coverageAuditVersion = 0;
let coverageEditing = null, coverageAction = 'create';
let coverageLoadedDay = null, coverageDialogVersion = 0;

function clearCoverageRows() {
  coverageEntries = []; coverageLoadedDay = null;
  $('coverage-rows').innerHTML = '<tr><td colspan="5" class="empty">Loading planned absences…</td></tr>';
  ['coverage-planned','coverage-covered','coverage-unassigned'].forEach(id => $(id).textContent = '—');
}

function coverageNotice(message, error = false) {
  $('coverage-message').textContent = message;
  $('coverage-message').dataset.error = String(error);
}

function clearCoverage() {
  coverageVersion++; coverageAuditVersion++; coverageDialogVersion++;
  coverageEntries = []; coverageLoadedDay = null; coverageEditing = null;
  if ($('coverage-dialog').open) $('coverage-dialog').close();
  $('coverage-form').reset();
  $('coverage-day').value = '';
  $('coverage-cancelled').checked = false;
  ['coverage-rows','coverage-teacher','coverage-audit-list'].forEach(id => $(id).replaceChildren());
  $('coverage-audit').hidden = true;
  $('coverage-audit-title').textContent = 'Coverage changes';
  $('coverage-sync').textContent = 'Waiting for server';
  $('coverage-summary-text').textContent = 'Loading coverage…';
  coverageNotice('');
  ['coverage-planned','coverage-covered','coverage-unassigned'].forEach(id => $(id).textContent = '—');
}

async function refreshCoverage() {
  if (role !== 'admin' || !connected) return;
  const version = ++coverageVersion;
  const params = new URLSearchParams();
  if (page === 'coverage' && $('coverage-day').value) {
    params.set('day', $('coverage-day').value);
    if (coverageLoadedDay !== $('coverage-day').value) clearCoverageRows();
  }
  if (page === 'coverage' && $('coverage-cancelled').checked) params.set('include_cancelled', 'true');
  try {
    const data = await (await api('/absences?' + params)).json();
    if (version !== coverageVersion || role !== 'admin' || !connected) return;
    if (!$('coverage-day').value) $('coverage-day').value = data.today;
    coverageEntries = data.entries;
    coverageLoadedDay = data.day;
    if ($('coverage-message').dataset.error === 'true') coverageNotice('');
    if (page === 'dashboard') {
      $('coverage-summary-text').textContent = data.planned + ' planned · ' + data.covered + ' assigned · ' + data.unassigned + ' need cover';
    }
    $('coverage-planned').textContent = data.planned;
    $('coverage-covered').textContent = data.covered;
    $('coverage-unassigned').textContent = data.unassigned;
    $('coverage-sync').textContent = 'Updated ' + new Date().toLocaleTimeString([], {hour:'numeric',minute:'2-digit'});
    $('coverage-rows').innerHTML = coverageEntries.map(entry => {
      const status = entry.cancelled ? 'Cancelled' : entry.substitute_name ? 'Assigned' : 'Needs cover';
      const current = entry.presence === 'unrecorded' ? 'Not recorded' : entry.presence === 'in' ? 'In' : 'Out';
      const actions = entry.cancelled
        ? '<button class="text-button" data-coverage-action="restore" data-absence="' + entry.id + '">Restore</button>'
        : '<button class="text-button" data-coverage-action="edit" data-absence="' + entry.id + '">Edit cover</button><button class="text-button" data-coverage-action="cancel" data-absence="' + entry.id + '">Cancel</button>';
      return '<tr><td><strong>' + esc(entry.name) + '</strong><small>' + esc(entry.teacher_id) + (entry.active ? '' : ' · Inactive') + '</small></td><td>' + esc(entry.substitute_name || 'Not assigned') + '<small>' + status + '</small></td><td><span class="status ' + (entry.presence === 'in' ? 'inside' : entry.presence === 'out' ? 'outside' : '') + '">' + current + '</span></td><td>' + esc(dateTime(entry.updated_at)) + '<small>' + esc(entry.updated_by) + '</small></td><td class="coverage-actions">' + actions + '<button class="text-button" data-coverage-action="history" data-absence="' + entry.id + '">History</button></td></tr>';
    }).join('') || '<tr><td colspan="5" class="empty">No planned absences for this date. Use Plan absence to add one.</td></tr>';
  } catch (error) {
    if (version !== coverageVersion || role !== 'admin' || !connected) return;
    $('coverage-sync').textContent = 'Coverage may be stale';
    coverageNotice('Could not refresh planned coverage. ' + error.message, true);
    $('coverage-summary-text').textContent = 'Coverage unavailable — open Absences & cover to retry.';
  }
}

function openCoverage(action, entry = null) {
  coverageDialogVersion++;
  $('coverage-save').disabled = false;
  coverageAction = action; coverageEditing = entry ? {...entry} : null;
  $('coverage-form-error').textContent = '';
  const staffOptions = directoryStaff.filter(person => person.active || person.id === entry?.teacher_pk);
  $('coverage-teacher').innerHTML = '<option value="">Choose a staff member</option>' + staffOptions.map(person => '<option value="' + person.id + '">' + esc(person.name) + ' · ' + esc(person.teacher_id) + '</option>').join('');
  $('coverage-teacher').value = entry ? entry.teacher_pk : '';
  $('coverage-teacher').disabled = action !== 'create';
  $('coverage-form-day').value = entry ? entry.day : $('coverage-day').value;
  $('coverage-form-day').disabled = action !== 'create';
  $('coverage-substitute').value = entry?.substitute_name || '';
  $('coverage-substitute').disabled = action === 'cancel';
  const titles = {create:'Plan an absence', edit:'Edit substitute coverage', cancel:'Cancel planned absence', restore:'Restore planned absence'};
  const buttons = {create:'Save absence', edit:'Save cover', cancel:'Cancel absence', restore:'Restore absence'};
  $('coverage-dialog-title').textContent = titles[action];
  $('coverage-save').textContent = buttons[action];
  $('coverage-save').className = action === 'cancel' ? 'primary danger' : 'primary';
  $('coverage-dialog-description').textContent = action === 'cancel'
    ? 'Review the staff member and date. Cancellation stays in the coverage history.'
    : 'This records planned coverage. Scan status is recorded separately.';
  $('coverage-dialog').showModal();
  (action === 'create' ? $('coverage-teacher') : $('coverage-save')).focus();
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

document.addEventListener('DOMContentLoaded', () => {
  $('coverage-add').onclick = () => openCoverage('create');
  $('coverage-dialog-close').onclick = () => { coverageDialogVersion++; $('coverage-dialog').close(); };
  $('coverage-dialog').addEventListener('cancel', () => { coverageDialogVersion++; });
  $('coverage-audit-close').onclick = () => { coverageAuditVersion++; $('coverage-audit').hidden = true; };
  const changeFilter = () => {
    coverageAuditVersion++; $('coverage-audit').hidden = true; coverageNotice('');
    clearCoverageRows(); refreshCoverage();
  };
  $('coverage-day').onchange = changeFilter;
  $('coverage-cancelled').onchange = changeFilter;
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
      if (entry) { payload.version = entry.version; payload.cancelled = action === 'cancel'; }
      else { payload.teacher_pk = Number($('coverage-teacher').value); payload.day = $('coverage-form-day').value; }
      const result = await (await api('/absences' + (entry ? '/' + entry.id : ''), {
        method: entry ? 'PATCH' : 'POST', body: JSON.stringify(payload)
      })).json();
      if (!connected || role !== 'admin' || dialogVersion !== coverageDialogVersion) return;
      $('coverage-dialog').close(); $('coverage-day').value = result.day;
      if (result.cancelled) $('coverage-cancelled').checked = true;
      navigate('coverage');
      coverageNotice(result.cancelled ? 'Absence cancelled. The entry and history are preserved.' : 'Planned coverage saved for ' + result.name + '.');
      await refreshCoverage();
    } catch (error) {
      if (connected && dialogVersion === coverageDialogVersion) $('coverage-form-error').textContent = error.message + (error.status ? '' : ' Refresh this date before retrying; the save was not confirmed.');
    } finally { if (dialogVersion === coverageDialogVersion) $('coverage-save').disabled = false; }
  };
});
