// Setup checklist and batch badge printing. The server returns each new badge code once, with
// its QR and Code 128 patterns; this screen draws them for printing and never stores them, so
// clearing the sheet or signing out discards them for good.
let setupData = null, setupVersion = 0, setupHtml = '', setupOpenedForEmptyRoster = false;
let printPicked = new Set(), printReview = null, printDialogVersion = 0, badgeSheet = [], sheetGeneration = 0;
const STEP_STATUS = {done:'Ready', todo:'To do', warning:'Check', info:'Note'};
const count = (n, word) => n + ' ' + word + (n === 1 ? '' : 's');
const shortDate = epoch => new Date(epoch * 1000).toLocaleDateString([], {month:'short', day:'numeric', year:'numeric'});

function clearSetup() {
  setupVersion++; sheetGeneration++;
  setupData = null; setupHtml = ''; setupOpenedForEmptyRoster = false;
  $('setup-steps').innerHTML = '<li class="empty">Checking setup…</li>';
  $('setup-count').hidden = true; $('setup-sync').textContent = 'Waiting for server';
  $('badge-summary').textContent = '';
  closePrintDialog(); clearBadgeSheet();
}

function stepHtml(item, index) {
  const help = item.help.map(entry => '<li>' + esc(entry.text) + (entry.command ? '<code>' + esc(entry.command) + '</code>' : '') + '</li>').join('');
  return '<li class="panel setup-step ' + esc(item.status) + '"><span class="step-marker" aria-hidden="true">' +
    (item.status === 'done' ? '✓' : index + 1) + '</span><div class="step-body"><div class="step-head"><h2>' + esc(item.title) +
    '</h2><span class="step-status">' + esc(STEP_STATUS[item.status] || item.status) + '</span></div><p>' + esc(item.detail) + '</p>' +
    (item.lines.length ? '<ul class="step-lines">' + item.lines.map(line => '<li>' + esc(line) + '</li>').join('') + '</ul>' : '') +
    (help ? '<details class="step-help"><summary>How to do this</summary><ul>' + help + '</ul></details>' : '') +
    (item.actions.length ? '<div class="step-actions">' + item.actions.map((action, i) => '<button class="' + (i ? 'text-button' : 'secondary') +
      '" data-setup-step="' + esc(item.key) + '" data-action="' + i + '">' + esc(action.label) + '</button>').join('') + '</div>' : '') +
    '</div></li>';
}

function renderSetup() {
  const remaining = setupData?.remaining || 0, missing = setupData?.badges.missing.length || 0;
  $('setup-count').textContent = remaining;
  $('setup-count').hidden = !remaining;
  $('badge-summary').textContent = !setupData?.staff.active ? '' : missing
    ? count(missing, 'active staff member') + (missing === 1 ? ' has' : ' have') + ' no badge on record.'
    : 'Every active staff member has a badge on record.';
  const html = (setupData?.steps || []).map(stepHtml).join('');
  // Identical refreshes leave the list alone so an open "How to do this" stays open.
  if (html !== setupHtml) { setupHtml = html; $('setup-steps').innerHTML = html; }
}

async function refreshSetup() {
  if (role !== 'admin' || !connected) return;
  const version = ++setupVersion;
  try {
    const data = await (await api('/setup')).json();
    if (version !== setupVersion || role !== 'admin' || !connected) return;
    setupData = data;
    renderSetup();
    $('setup-sync').textContent = 'Checked ' + new Date().toLocaleTimeString([], {hour:'numeric', minute:'2-digit'});
    // A brand-new installation opens the checklist instead of an empty overview, once per sign-in.
    if (!setupOpenedForEmptyRoster && !data.staff.active && page === 'dashboard') {
      setupOpenedForEmptyRoster = true;
      navigate('setup');
    }
  } catch (error) {
    if (version !== setupVersion || role !== 'admin' || !connected) return;
    $('setup-sync').textContent = 'Could not check setup. ' + error.message;
    if (!setupData) { setupHtml = ''; $('setup-steps').innerHTML = '<li class="empty">Could not check setup. ' + esc(error.message) + '</li>'; }
  }
}

function runSetupAction(action) {
  if (action.type === 'page') return navigate(action.page);
  if (action.type === 'print_missing') return openPrintDialog('missing');
  if (action.type === 'print') return openPrintDialog('none');
}

// Batch printing: choose people, review how many working badges are replaced, then issue.
const activeStaff = () => directoryStaff.filter(person => person.active);

function openPrintDialog(pick = 'missing') {
  if (!activeStaff().length) {
    showToast(directoryStaff.length ? 'There are no active staff to print badges for.' : 'Staff list is still loading. Try again in a moment.');
    return;
  }
  printDialogVersion++;
  $('print-search').value = ''; $('print-error').textContent = '';
  pickPrint(pick);
  $('print-dialog').showModal();
  $('print-search').focus();
}

function closePrintDialog() {
  printDialogVersion++; printPicked = new Set(); printReview = null;
  if ($('print-dialog').open) $('print-dialog').close();
}

function pickPrint(pick) {
  const people = activeStaff();
  printPicked = new Set((pick === 'all' ? people : pick === 'missing' ? people.filter(person => !person.badge_issued_at) : []).map(person => person.id));
  renderPrintList();
}

function printSelection() {
  const people = activeStaff().filter(person => printPicked.has(person.id));
  return {people, replacing: people.filter(person => person.badge_issued_at)};
}

function renderPrintList() {
  const query = $('print-search').value.trim().toLowerCase();
  const shown = activeStaff().filter(person => !query || person.name.toLowerCase().includes(query) || person.teacher_id.toLowerCase().includes(query));
  $('print-list').innerHTML = shown.map(person => '<li><label><input type="checkbox" data-print-pick="' + person.id + '"' +
    (printPicked.has(person.id) ? ' checked' : '') + '><span>' + esc(person.name) + '<small>' + esc(person.teacher_id) + '</small></span><small>' +
    (person.badge_issued_at ? 'Badge issued ' + esc(shortDate(person.badge_issued_at)) : 'No badge on record') + '</small></label></li>').join('') ||
    '<li class="empty">No active staff match.</li>';
  renderPrintSummary();
}

function renderPrintSummary() {
  const {people, replacing} = printSelection();
  // Issue sends exactly what this summary showed. If another desk changes a badge after this, the server
  // refuses the whole batch instead of revoking a badge the office never saw.
  printReview = {teacher_pks: people.map(person => person.id),
    reviewed_badges: Object.fromEntries(people.map(person => [person.id, person.badge_issued_at || null]))};
  $('print-summary').textContent = !people.length ? 'Select at least one staff member.' :
    count(people.length, 'new badge') + ' will be drawn on a sheet for you to print now.' +
    (replacing.length ? ' ' + count(replacing.length, 'badge') + ' they carry now will stop working immediately.' :
      ' None of them has a badge on record; any older badge they still carry stops working.');
  $('print-summary').dataset.warning = String(replacing.length > 0);
  $('print-issue').textContent = people.length ? (replacing.length ? 'Replace and issue ' : 'Issue ') + count(people.length, 'badge') : 'Issue badges';
  $('print-issue').className = 'primary' + (replacing.length ? ' danger' : '');
  $('print-issue').disabled = !people.length;
}

async function issueBadges() {
  const review = printReview, version = printDialogVersion, generation = sheetGeneration;
  if (!review?.teacher_pks.length) { $('print-error').textContent = 'Select at least one staff member. No badges were issued.'; return; }
  $('print-issue').disabled = true; $('print-error').textContent = '';
  try {
    const result = await (await api('/badges/batch', {method:'POST', body:JSON.stringify(review)})).json();
    // Codes exist only in this response, so keep them even if the dialog was closed meanwhile.
    if (!addToBadgeSheet(result.issued, generation)) return;
    if (version === printDialogVersion) closePrintDialog();
    showToast(count(result.issued.length, 'badge') + ' issued. Print the sheet now; the codes are not shown again.');
    if (page !== 'teachers') navigate('teachers'); else refresh();
    $('badge-sheet-panel').scrollIntoView({block:'start'});
  } catch (error) {
    if (version !== printDialogVersion || !connected) return;
    const definite = error.status && error.status < 500;
    $('print-error').textContent = error.message + (definite ? '' :
      ' The server did not confirm. Close this, check each person\'s badge date on Staff & badges, and issue again if needed.');
    // Reload the staff list and redraw, so the next click reviews current badges rather than the old view.
    if (definite) { await refresh(); if (version === printDialogVersion) renderPrintList(); }
  } finally { if (version === printDialogVersion) renderPrintSummary(); }
}

// The sheet keeps every unprinted card until it is cleared; reissuing someone swaps their card.
function badgeCardHtml(badge) {
  const size = badge.qr.length, quiet = 10, width = badge.code128.length + quiet * 2;
  let qr = '', bars = '';
  badge.qr.forEach((row, y) => { for (let x = 0; x < row.length; x++) if (row[x] === '1') qr += 'M' + x + ' ' + y + 'h1v1h-1z'; });
  for (let i = 0; i < badge.code128.length;) {
    if (badge.code128[i] !== '1') { i++; continue; }
    let end = i;
    while (badge.code128[end] === '1') end++;
    bars += 'M' + (i + quiet) + ' 0h' + (end - i) + 'v1h-' + (end - i) + 'z';
    i = end;
  }
  const demo = badge.teacher_id.startsWith('DEMO-') ? ' · FICTIONAL DEMO' : '';
  return '<article class="badge-card"><div class="badge-text"><div class="badge-school">GREEN LEVEL HIGH SCHOOL · STAFF BADGE</div>' +
    '<strong class="badge-name">' + esc(badge.name) + '</strong><span class="badge-id">' + esc(badge.teacher_id) + demo + '</span>' +
    '<svg class="badge-barcode" viewBox="0 0 ' + width + ' 1" preserveAspectRatio="none" shape-rendering="crispEdges" role="img" aria-label="Code 128 barcode">' +
    '<rect width="' + width + '" height="1" fill="#fff"/><path d="' + bars + '" fill="#000"/></svg>' +
    '<small class="badge-hint">Scan at the arrival or departure station and wait for the on-screen confirmation.</small></div>' +
    '<svg class="badge-qr" viewBox="0 0 ' + size + ' ' + size + '" shape-rendering="crispEdges" role="img" aria-label="QR code">' +
    '<rect width="' + size + '" height="' + size + '" fill="#fff"/><path d="' + qr + '" fill="#000"/></svg></article>';
}

function renderBadgeSheet() {
  const html = badgeSheet.length ? '<div class="badge-sheet">' + badgeSheet.map(badgeCardHtml).join('') + '</div>' : '';
  $('badge-preview').innerHTML = html;
  $('print-root').innerHTML = html;
  $('badge-sheet-panel').hidden = !badgeSheet.length;
  $('badge-sheet-note').textContent = badgeSheet.length ? count(badgeSheet.length, 'badge') + ' ready to print · 4 per letter page' : '';
  document.body.classList.toggle('has-badge-sheet', badgeSheet.length > 0);
}

// Returns false when the office signed out after asking for these badges; they are not shown.
function addToBadgeSheet(badges, generation) {
  if (generation !== sheetGeneration || role !== 'admin' || !connected) return false;
  const replaced = new Set(badges.map(badge => badge.id));
  badgeSheet = badgeSheet.filter(badge => !replaced.has(badge.id)).concat(badges);
  renderBadgeSheet();
  return true;
}

function clearBadgeSheet() {
  badgeSheet = [];
  renderBadgeSheet();
}

document.addEventListener('DOMContentLoaded', () => {
  $('setup-steps').onclick = event => {
    const button = event.target.closest('button[data-setup-step]');
    const item = setupData?.steps.find(entry => entry.key === button?.dataset.setupStep);
    const action = item?.actions[Number(button.dataset.action)];
    if (action) runSetupAction(action);
  };
  $('print-open').onclick = () => openPrintDialog('missing');
  $('print-form').onsubmit = event => { event.preventDefault(); issueBadges(); };
  $('print-close').onclick = closePrintDialog;
  $('print-dialog').addEventListener('cancel', () => { printDialogVersion++; });
  $('print-search').oninput = renderPrintList;
  $('print-picks').onclick = event => {
    const button = event.target.closest('button[data-pick]');
    if (button) pickPrint(button.dataset.pick);
  };
  $('print-list').onchange = event => {
    const id = Number(event.target.dataset.printPick);
    if (!id) return;
    if (event.target.checked) printPicked.add(id); else printPicked.delete(id);
    renderPrintSummary();
  };
  $('print').onclick = () => window.print();
  $('badge-sheet-clear').onclick = () => confirmAction({title:'Clear the badge sheet?',
    body:'Unprinted badges cannot be shown again. You would need to issue those badges again, which replaces them.',
    confirm:'Clear sheet', danger:true, run:async () => { clearBadgeSheet(); showToast('Badge sheet cleared.'); }});
});
