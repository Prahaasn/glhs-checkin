// Review dialogs for office exceptions. They replace browser prompt()/confirm() with an explicit
// person, status, reason, and final action, and they report errors where the office is looking.
let correctionTarget = null, correctionAttempt = null, correctionDialogVersion = 0;
let confirmRun = null, confirmDialogVersion = 0, toastTimer = null;

function showToast(message) {
  clearTimeout(toastTimer);
  $('toast').textContent = message;
  $('toast').hidden = false;
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 6000);
}

function recordedStatus(person) {
  if (person.presence === 'unrecorded') return 'Not recorded (no scan yet)';
  return (person.presence === 'in' ? 'IN' : 'OUT') + ' since ' + dateTime(person.last_seen);
}

function correctionDirection() {
  return $('correction-in').checked ? 'in' : $('correction-out').checked ? 'out' : null;
}

function renderCorrectionSummary() {
  const person = correctionTarget, direction = correctionDirection();
  if (!person || !direction) { $('correction-summary').textContent = 'Choose IN or OUT.'; return; }
  const status = direction.toUpperCase();
  $('correction-summary').textContent = 'Records ' + person.name + ' as ' + status + ' now. Activity will show your name and this reason.' +
    (person.presence === direction ? ' They are already recorded ' + status + ', so this adds a note without changing status.' : '');
  document.querySelectorAll('#correction-picks [data-reason]').forEach(button =>
    button.className = 'chip' + (button.dataset.reason === $('correction-reason').value.trim() ? ' selected' : ''));
}

function openCorrection(person, options = {}) {
  if (!person) return;
  correctionDialogVersion++;
  correctionTarget = person; correctionAttempt = null;
  // Suggest the opposite of the recorded status; the office still confirms explicitly.
  const suggested = options.direction || (person.presence === 'in' ? 'out' : 'in');
  $('correction-person').textContent = person.name + ' · ' + person.teacher_id;
  $('correction-current').textContent = 'Currently recorded: ' + recordedStatus(person);
  $('correction-in').checked = suggested === 'in';
  $('correction-out').checked = suggested === 'out';
  $('correction-reason').value = options.reason || '';
  $('correction-error').textContent = '';
  $('correction-save').disabled = false;
  renderCorrectionSummary();
  $('correction-dialog').showModal();
  (options.reason ? $('correction-save') : $('correction-reason')).focus();
}

function closeCorrection() {
  correctionDialogVersion++; correctionTarget = null; correctionAttempt = null;
  if ($('correction-dialog').open) $('correction-dialog').close();
}

async function saveCorrection() {
  const person = correctionTarget, version = correctionDialogVersion;
  const direction = correctionDirection(), reason = $('correction-reason').value.trim();
  if (!person) return;
  if (!direction) { $('correction-error').textContent = 'Choose IN or OUT. No correction was saved.'; return; }
  if (reason.length < 3) { $('correction-error').textContent = 'Enter a reason of at least 3 characters. No correction was saved.'; return; }
  // Like scanner retries, an unconfirmed attempt keeps its request ID so it cannot be recorded twice.
  const retrying = correctionAttempt && correctionAttempt.direction === direction && correctionAttempt.reason === reason;
  const attempt = retrying ? correctionAttempt : {direction, reason, request_id: uuid()};
  correctionAttempt = attempt;
  $('correction-save').disabled = true; $('correction-error').textContent = '';
  try {
    const result = await (await api('/teachers/' + person.id + '/correction', {method:'POST', body:JSON.stringify(attempt)})).json();
    if (version !== correctionDialogVersion || !connected) return;
    closeCorrection();
    showToast(result.name + (result.changed ? ' is now recorded ' : ' was already recorded ') + direction.toUpperCase() + '. Correction saved to Activity.');
    refresh();
  } catch (error) {
    if (version !== correctionDialogVersion || !connected) return;
    const definite = error.status && error.status < 500;
    if (definite) correctionAttempt = null;
    $('correction-error').textContent = error.message + (definite ? '' : ' The correction was not confirmed. Select Record correction again to retry it safely.');
  } finally { if (version === correctionDialogVersion) $('correction-save').disabled = false; }
}

function confirmAction({title, body, confirm = 'Confirm', danger = false, eyebrow = 'PLEASE CONFIRM', run}) {
  confirmDialogVersion++; confirmRun = run;
  $('confirm-eyebrow').textContent = eyebrow;
  $('confirm-title').textContent = title;
  $('confirm-body').textContent = body;
  $('confirm-ok').textContent = confirm;
  $('confirm-ok').className = 'primary' + (danger ? ' danger' : '');
  $('confirm-ok').disabled = false;
  $('confirm-error').textContent = '';
  $('confirm-dialog').showModal();
  $('confirm-cancel').focus();
}

function closeConfirm() {
  confirmDialogVersion++; confirmRun = null;
  if ($('confirm-dialog').open) $('confirm-dialog').close();
}

async function runConfirmed() {
  const run = confirmRun, version = confirmDialogVersion;
  if (!run) return;
  $('confirm-ok').disabled = true; $('confirm-error').textContent = '';
  try {
    await run();
    if (version === confirmDialogVersion) closeConfirm();
  } catch (error) {
    if (version === confirmDialogVersion && connected) $('confirm-error').textContent = error.message;
  } finally { if (version === confirmDialogVersion) $('confirm-ok').disabled = false; }
}

function clearDialogs() {
  closeCorrection(); closeConfirm();
  clearTimeout(toastTimer); $('toast').hidden = true; $('toast').textContent = '';
}

document.addEventListener('DOMContentLoaded', () => {
  $('correction-form').onsubmit = event => { event.preventDefault(); saveCorrection(); };
  $('correction-close').onclick = closeCorrection;
  $('correction-dialog').addEventListener('cancel', () => { correctionDialogVersion++; correctionTarget = null; });
  ['correction-in','correction-out'].forEach(id => $(id).addEventListener('change', renderCorrectionSummary));
  $('correction-reason').addEventListener('input', renderCorrectionSummary);
  $('correction-picks').onclick = event => {
    const button = event.target.closest('button[data-reason]');
    if (!button) return;
    $('correction-reason').value = button.dataset.reason;
    renderCorrectionSummary();
  };
  $('confirm-form').onsubmit = event => { event.preventDefault(); runConfirmed(); };
  $('confirm-cancel').onclick = closeConfirm;
  $('confirm-dialog').addEventListener('cancel', () => { confirmDialogVersion++; confirmRun = null; });
});
