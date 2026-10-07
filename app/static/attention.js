// Overview attention queue. The server lists today's exceptions; each action opens a review
// dialog or view, so nothing is changed until the office confirms it.
let attentionData = null, attentionVersion = 0, attentionExpanded = false, attentionHtml = '';
const ATTENTION_PREVIEW = 6;

function clearAttention() {
  attentionVersion++; attentionData = null; attentionExpanded = false; attentionHtml = '';
  $('attention-list').innerHTML = '<li class="empty">Checking today\'s records…</li>';
  $('attention-count').hidden = true;
  $('attention-more').hidden = true;
}

function attentionLookup() {
  return {
    planned: new Map((attentionData?.planned_today || []).map(entry => [entry.teacher_pk, entry])),
    notArrived: new Set(attentionData?.not_arrived || [])
  };
}

function renderAttention() {
  const items = attentionData?.items || [];
  const shown = attentionExpanded ? items : items.slice(0, ATTENTION_PREVIEW);
  const open = items.filter(entry => entry.tone !== 'info').length;
  $('attention-count').textContent = open;
  $('attention-count').hidden = !open;
  $('attention-more').hidden = items.length <= ATTENTION_PREVIEW;
  $('attention-more').textContent = attentionExpanded ? 'Show fewer' : 'Show all ' + items.length;
  const html = shown.map(entry => '<li class="attention-item ' + esc(entry.tone) + '"><span class="attention-dot" aria-hidden="true"></span>' +
    '<div class="attention-text"><strong>' + esc(entry.title) + '</strong><p>' + esc(entry.detail) + '</p></div><div class="attention-actions">' +
    entry.actions.map((action, index) => '<button class="' + (index ? 'text-button' : 'secondary') + '" data-attention="' + esc(entry.id) +
      '" data-action="' + index + '">' + esc(action.label) + '</button>').join('') + '</div></li>').join('') ||
    '<li class="empty all-clear">All clear. Nothing needs attention right now.</li>';
  // Skip identical re-renders so a five-second refresh never swaps a button mid-click.
  if (html !== attentionHtml) { attentionHtml = html; $('attention-list').innerHTML = html; }
}

async function refreshAttention() {
  if (role !== 'admin' || !connected) return;
  const version = ++attentionVersion;
  try {
    const data = await (await api('/attention')).json();
    if (version !== attentionVersion || role !== 'admin' || !connected) return;
    attentionData = data;
    renderAttention();
    renderRoster();
  } catch (error) {
    if (version !== attentionVersion || role !== 'admin' || !connected) return;
    attentionHtml = '';
    $('attention-list').innerHTML = '<li class="empty">Could not check today\'s exceptions. ' + esc(error.message) + '</li>';
  }
}

async function openAbsenceFromAttention(action) {
  const data = await (await api('/absences?day=' + encodeURIComponent(action.day))).json();
  const entry = data.entries.find(item => item.id === action.absence_id);
  if (!entry) throw new Error('That absence has already changed. The list will refresh.');
  openCoverage(action.type === 'cancel_absence' ? 'cancel' : 'edit', entry);
}

async function runAttentionAction(action) {
  if (action.type === 'edit_cover' || action.type === 'cancel_absence') return openAbsenceFromAttention(action);
  if (action.type === 'correct') {
    const person = directoryStaff.find(item => item.id === action.teacher_pk);
    if (!person) throw new Error('Staff list is still loading. Try again in a moment.');
    return openCorrection(person, {direction: action.direction, reason: action.reason || ''});
  }
  if (action.type === 'open_day') {
    setCoverageView('day');
    $('coverage-day').value = action.day;
    clearCoverageRows();
    return navigate('coverage');
  }
  if (action.type === 'show_not_arrived') {
    setRosterFilter('not-arrived');
    $('roster-panel').scrollIntoView({block:'start', behavior:'smooth'});
  }
}

document.addEventListener('DOMContentLoaded', () => {
  $('attention-more').onclick = () => { attentionExpanded = !attentionExpanded; renderAttention(); };
  $('attention-list').onclick = async event => {
    const button = event.target.closest('button[data-attention]');
    if (!button) return;
    const entry = attentionData?.items.find(item => item.id === button.dataset.attention);
    const action = entry?.actions[Number(button.dataset.action)];
    if (!action) return;
    button.disabled = true;
    try { await runAttentionAction(action); }
    catch (error) { showToast(error.message); refreshAttention(); }
    finally { button.disabled = false; }
  };
});
