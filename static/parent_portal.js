/* ==============================================================
   PORTAIL PARENT — YIRIBA Vos Racines Digitalisées
   ============================================================== */

const _pp = { children: [], selectedChild: null };
const _PP_COLORS = ['#0E5C3F','#2F8F5B','#F2B705','#C94A35','#6B4E9B','#1565C0'];

/* -- Échappement HTML (anti-XSS) : toute donnée venant du back
   insérée via concaténation/innerHTML doit passer par esc() -- */
function _ppEsc(v) {
  return String(v == null ? '' : v)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function _ppGradeColor(pct) {
  if (pct >= 80) return 'var(--yiriba-vert)';
  if (pct >= 50) return 'var(--yiriba-vert-feuille)';
  if (pct >= 35) return 'var(--yiriba-jaune)';
  return 'var(--yiriba-rouge)';
}

function _ppAttBadge(s) {
  if (s === 'present') return '<span class="badge badge-active"><span class="badge-dot"></span>Pr\u00e9sent</span>';
  if (s === 'absent') return '<span class="badge badge-danger"><span class="badge-dot"></span>Absent</span>';
  if (s === 'late') return '<span class="badge badge-warning"><span class="badge-dot"></span>Retard</span>';
  if (s === 'excused') return '<span class="badge badge-info"><span class="badge-dot"></span>Justifi\u00e9</span>';
  return '<span class="badge">' + (s || '\u2014') + '</span>';
}

function _ppPeriodLabel(p) {
  var m = { T1: 'Trimestre 1', T2: 'Trimestre 2', T3: 'Trimestre 3', S1: 'Semestre 1', S2: 'Semestre 2' };
  return m[p] || p || '\u2014';
}

function _ppChildSelector() {
  var ch = _pp.children;
  var sel = _pp.selectedChild;
  if (ch.length <= 1) return '';
  var opts = ch.map(function(c) {
    return '<option value="' + c.id + '"' + (c.id === sel?.id ? ' selected' : '') + '>' + _ppEsc(c.first_name) + ' ' + _ppEsc(c.last_name) + ' \u2014 ' + (c.class_name || 'Non inscrit') + '</option>';
  }).join('');
  return '<div style="margin-bottom:16px;display:flex;align-items:center;gap:10px;">' +
    '<label style="font-size:13px;font-weight:600;color:var(--texte-secondaire);">Enfant :</label>' +
    '<select onchange="ppSwitchChild(this.value)" style="padding:8px 14px;border:1.5px solid var(--border);border-radius:8px;font-size:13px;background:white;cursor:pointer;">' + opts + '</select></div>';
}

function ppSwitchChild(sid) {
  _pp.selectedChild = _pp.children.find(function(c) { return c.id == sid; });
  var t = document.querySelector('.topbar-title')?.textContent || '';
  if (t.includes('Accueil') || t.includes('Portail')) loadParentDashboard();
  else if (t.includes('enfants')) loadParentChildren();
  else if (t.includes('sultat') || t.includes('note')) loadParentGrades();
  else if (t.includes('sence')) loadParentAttendance();
  else if (t.includes('ulletin')) loadParentBulletins();
  else if (t.includes('aiement')) loadParentPayments();
  else if (t.includes('colarit')) loadParentScolarite();
  else if (t.includes('evaluat') || t.includes('evoir')) loadParentEvaluations();
  else if (t.includes('ocument')) loadParentDocuments();
  else loadParentDashboard();
}

async function _ppLoadChildren() {
  var res = await api('/api/parent/my-children');
  var data = res?.ok ? await res.json() : {};
  _pp.children = data.children || [];
  if (_pp.children.length > 0 && !_pp.selectedChild) _pp.selectedChild = _pp.children[0];
  return _pp.children;
}

/* ==============================================================
   1. TABLEAU DE BORD PARENT (enrichi)
   ============================================================== */
async function loadParentDashboard() {
  var c = document.getElementById('main-content');
  var fn = state.user?.first_name || 'Parent';
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';

  try {
    var children = await _ppLoadChildren();
    var child = _pp.selectedChild;

    if (!child) {
      c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;">Bonjour, ' + fn + ' \ud83d\udc4b</h1><p style="color:var(--texte-secondaire);">Suivez la scolarit\u00e9 de vos enfants.</p></div>' +
        '<div class="card section-card" style="margin-top:16px;"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-children"></i></div><h4>Aucun enfant rattach\u00e9</h4><p>Contactez l\u2019\u00e9tablissement.</p></div></div>';
      return;
    }

    // Fetch all data in parallel
    var results = await Promise.all([
      api('/api/parent/children/' + child.id + '/summary'),
      api('/api/parent/children/' + child.id + '/grades'),
      api('/api/parent/children/' + child.id + '/attendance'),
      api('/api/parent/children/' + child.id + '/payments'),
      api('/api/parent/children/' + child.id + '/bulletins'),
      api('/api/academic-periods')
    ]);
    var summary = results[0]?.ok ? await results[0].json() : {};
    var gradesData = results[1]?.ok ? await results[1].json() : {};
    var attData = results[2]?.ok ? await results[2].json() : {};
    var payData = results[3]?.ok ? await results[3].json() : {};
    var bullData = results[4]?.ok ? await results[4].json() : {};
    var periods = results[5]?.ok ? (await results[5].json()).periods || [] : [];

    var grades = gradesData.grades || [];
    var att = attData.attendance || [];
    var bulletins = bullData.bulletins || [];

    var avg = summary.grades?.average || (grades.length > 0 ? (grades.reduce(function(s, g) { return s + (g.grade || 0); }, 0) / grades.length).toFixed(1) : '\u2014');
    var avgPct = avg !== '\u2014' ? Math.round(avg / 20 * 100) : 0;
    var presentCount = summary.attendance?.present ?? att.filter(function(a) { return a.status === 'present'; }).length;
    var absentCount = summary.attendance?.absent ?? att.filter(function(a) { return a.status === 'absent'; }).length;
    var lateCount = summary.attendance?.late ?? att.filter(function(a) { return a.status === 'late'; }).length;
    var unjustified = summary.attendance?.unjustified ?? 0;
    var attRate = att.length > 0 ? Math.round(presentCount / att.length * 100) : '\u2014';
    var balance = summary.payments?.balance ?? payData.balance ?? 0;
    var totalPaid = summary.payments?.total_paid ?? payData.total_paid ?? 0;
    var totalOwed = summary.payments?.total_owed ?? 0;
    var latestBull = bulletins[0] || null;
    var unreadNotifs = summary.unread_notifications || 0;

    // Build situation items
    var situationItems = [];
    if (unjustified > 0) situationItems.push({ icon: 'fa-user-xmark', color: 'var(--yiriba-rouge)', text: unjustified + ' absence(s) \u00e0 justifier', link: 'p-attendance' });
    if (balance > 0) situationItems.push({ icon: 'fa-money-bill-wave', color: 'var(--yiriba-jaune)', text: 'Reste \u00e0 payer : ' + balance.toLocaleString('fr-FR') + ' FCFA', link: 'p-payments' });
    if (unreadNotifs > 0) situationItems.push({ icon: 'fa-bell', color: 'var(--yiriba-vert-feuille)', text: unreadNotifs + ' notification(s) non lue(s)', link: 'p-notifications' });
    if (latestBull) situationItems.push({ icon: 'fa-file-lines', color: 'var(--yiriba-vert)', text: 'Bulletin ' + _ppPeriodLabel(latestBull.period) + ' disponible', link: 'p-bulletins' });
    if (situationItems.length === 0) situationItems.push({ icon: 'fa-check-circle', color: 'var(--yiriba-vert)', text: 'Aucun probl\u00e8me signal\u00e9', link: '' });

    var situationHtml = situationItems.map(function(item) {
      var click = item.link ? ' onclick="loadPage(\'' + item.link + '\')" style="cursor:pointer;"' : '';
      return '<div class="card section-card" style="padding:12px 16px;display:flex;align-items:center;gap:12px;border-left:4px solid ' + item.color + ';"' + click + '>' +
        '<div style="width:32px;height:32px;border-radius:8px;background:' + item.color + '15;display:grid;place-items:center;color:' + item.color + ';font-size:14px;flex-shrink:0;"><i class="fas ' + item.icon + '"></i></div>' +
        '<div style="font-size:13px;font-weight:600;">' + item.text + '</div></div>';
    }).join('');

    // Grades HTML
    var gradesHtml = '';
    if (grades.length > 0) {
      grades.slice(0, 5).forEach(function(g) {
        var pct = g.max_grade > 0 ? (g.grade / g.max_grade * 100) : 0;
        gradesHtml += '<div style="display:flex;align-items:center;justify-content:space-between;padding:10px 8px;border-radius:8px;">' +
          '<div><div style="font-size:13px;font-weight:600;">' + (g.evaluation_name || '\u2014') + '</div>' +
          '<div style="font-size:11px;color:var(--texte-secondaire);">' + _ppPeriodLabel(g.period) + '</div></div>' +
          '<span style="font-family:\'Sora\',sans-serif;font-size:16px;font-weight:700;color:' + _ppGradeColor(pct) + '">' + _ppEsc(g.grade) + '/' + (g.max_grade || 20) + '</span></div>';
      });
    } else {
      gradesHtml = '<div class="yiriba-empty" style="padding:20px;"><div class="empty-tree"><i class="fas fa-pen-fancy"></i></div><h4>Aucune note</h4></div>';
    }

    var bullHtml = '';
    if (latestBull) {
      bullHtml = '<div style="background:var(--surface-soft);border-radius:10px;padding:14px;">' +
        '<div style="font-size:12px;color:var(--texte-secondaire);margin-bottom:4px;">' + _ppPeriodLabel(latestBull.period) + '</div>' +
        '<div style="font-family:\'Sora\',sans-serif;font-size:24px;font-weight:700;color:var(--yiriba-vert);">' + (latestBull.overall_average || '\u2014') + '</div>' +
        '<div style="font-size:12px;color:var(--texte-secondaire);">Moyenne' + (latestBull.rank ? ' \u00b7 Rang ' + latestBull.rank : '') + '</div></div>';
    } else {
      bullHtml = '<div style="text-align:center;padding:8px;font-size:13px;color:var(--texte-secondaire);"><i class="fas fa-hourglass-half" style="color:var(--yiriba-jaune);"></i> En cours de pr\u00e9paration</div>';
    }

    var payColor = balance > 0 ? 'var(--yiriba-rouge)' : 'var(--yiriba-vert)';
    var payRest = balance > 0 ? ' \u00b7 Reste ' + balance.toLocaleString('fr-FR') + ' FCFA' : '';

    c.innerHTML =
      '<div class="welcome" style="background:linear-gradient(135deg,rgba(14,92,63,0.06) 0%,rgba(47,143,91,0.03) 50%,transparent 100%);position:relative;overflow:hidden;">' +
        '<h1 style="font-family:\'Sora\',sans-serif;font-size:clamp(24px,3vw,32px);">Bonjour, ' + fn + ' \ud83d\udc4b</h1>' +
        '<p style="color:var(--texte-secondaire);font-size:15px;margin-top:6px;">Suivez la scolarit\u00e9 de ' + (children.length > 1 ? 'vos enfants' : 'votre enfant') + '.</p></div>' +
      _ppChildSelector() +
      // Stats cards
      '<div class="indicator-row" style="margin-top:16px;">' +
        '<div class="indicator-card hero"><div class="indicator-icon" style="background:rgba(255,255,255,0.18)"><i class="fas fa-user-graduate"></i></div><div class="indicator-info"><h4>' + _ppEsc(child.first_name) + ' ' + _ppEsc(child.last_name) + '</h4><div class="indicator-val">' + (child.class_name || '\u2014') + '</div><div class="indicator-sub">Classe</div></div></div>' +
        '<div class="indicator-card"><div class="indicator-icon" style="color:var(--yiriba-jaune)"><i class="fas fa-chart-line"></i></div><div class="indicator-info"><h4>Moyenne</h4><div class="indicator-val" style="color:' + _ppGradeColor(avgPct) + '">' + avg + ' / 20</div><div class="indicator-sub">' + grades.length + ' note(s)</div></div></div>' +
        '<div class="indicator-card"><div class="indicator-icon" style="color:var(--yiriba-vert-feuille)"><i class="fas fa-clipboard-check"></i></div><div class="indicator-info"><h4>Pr\u00e9sence</h4><div class="indicator-val">' + attRate + (attRate !== '\u2014' ? '%' : '\u2014') + '</div><div class="indicator-sub">' + presentCount + ' pr\u00e9sent \u00b7 ' + lateCount + ' retard \u00b7 ' + absentCount + ' absent</div></div></div>' +
        '<div class="indicator-card"><div class="indicator-icon" style="color:' + payColor + '"><i class="fas fa-money-bill-wave"></i></div><div class="indicator-info"><h4>Scolarit\u00e9</h4><div class="indicator-val">' + totalPaid.toLocaleString('fr-FR') + ' FCFA</div><div class="indicator-sub">' + (balance > 0 ? 'Reste : ' + balance.toLocaleString('fr-FR') + ' FCFA' : '\u00c0 jour') + '</div></div></div>' +
      '</div>' +
      // Situation actuelle
      '<div style="margin-top:16px;"><div style="font-weight:700;font-size:14px;margin-bottom:10px;"><i class="fas fa-circle-info" style="color:var(--yiriba-vert);margin-right:8px;"></i>Situation actuelle</div>' +
        '<div style="display:flex;flex-direction:column;gap:8px;">' + situationHtml + '</div></div>' +
      // Two columns
      '<div style="display:grid;grid-template-columns:1.4fr 1fr;gap:16px;margin-top:16px;">' +
        '<div class="card section-card" style="padding:0;">' +
          '<div style="padding:18px 20px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;">' +
            '<h3 style="margin:0;font-size:15px;font-family:\'Sora\',sans-serif;"><i class="fas fa-pen-fancy" style="color:var(--yiriba-vert);margin-right:8px;"></i>Derni\u00e8res notes</h3>' +
            '<a style="font-size:13px;font-weight:600;color:var(--yiriba-vert-feuille);cursor:pointer;" onclick="loadPage(\'p-grades\')">Voir tout \u2192</a></div>' +
          '<div style="padding:8px 12px;">' + gradesHtml + '</div></div>' +
        '<div style="display:flex;flex-direction:column;gap:16px;">' +
          '<div class="card section-card" style="padding:20px;cursor:pointer;" onclick="loadPage(\'p-bulletins\')">' +
            '<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">' +
              '<div style="width:40px;height:40px;border-radius:10px;background:var(--yiriba-vert);display:grid;place-items:center;color:white;font-size:16px;"><i class="fas fa-file-lines"></i></div>' +
              '<div><div style="font-weight:700;font-size:14px;">Dernier bulletin</div><div style="font-size:12px;color:var(--texte-secondaire);">Consulter les r\u00e9sultats</div></div></div>' + bullHtml + '</div>' +
          '<div class="card section-card" style="padding:20px;cursor:pointer;" onclick="loadPage(\'p-payments\')">' +
            '<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">' +
              '<div style="width:40px;height:40px;border-radius:10px;background:var(--yiriba-jaune);display:grid;place-items:center;color:white;font-size:16px;"><i class="fas fa-money-bill-wave"></i></div>' +
              '<div><div style="font-weight:700;font-size:14px;">Paiements</div><div style="font-size:12px;color:var(--texte-secondaire);">Frais scolaires</div></div></div>' +
            '<div style="font-family:\'Sora\',sans-serif;font-size:22px;font-weight:700;color:' + payColor + ';">' + totalPaid.toLocaleString('fr-FR') + ' FCFA</div>' +
            '<div style="font-size:12px;color:var(--texte-secondaire);">Pay\u00e9' + payRest + '</div></div>' +
          '<div class="card section-card" style="padding:20px;">' +
            '<div style="font-weight:700;font-size:14px;margin-bottom:12px;"><i class="fas fa-bolt" style="color:var(--yiriba-jaune);margin-right:8px;"></i>Actions rapides</div>' +
            '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">' +
              '<button class="btn-add" style="justify-content:center;padding:10px;font-size:12px;border-radius:8px;" onclick="loadPage(\'p-grades\')"><i class="fas fa-pen-fancy"></i> Notes</button>' +
              '<button class="btn-secondary" style="justify-content:center;padding:10px;font-size:12px;border-radius:8px;" onclick="loadPage(\'p-bulletins\')"><i class="fas fa-file-lines"></i> Bulletins</button>' +
              '<button class="btn-secondary" style="justify-content:center;padding:10px;font-size:12px;border-radius:8px;" onclick="loadPage(\'p-attendance\')"><i class="fas fa-clipboard-check"></i> Pr\u00e9sences</button>' +
              '<button class="btn-secondary" style="justify-content:center;padding:10px;font-size:12px;border-radius:8px;" onclick="loadPage(\'p-payments\')"><i class="fas fa-money-bill-wave"></i> Paiements</button>' +
            '</div></div></div></div>';
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur de chargement</h4></div></div>';
  }
}

/* ==============================================================
   2. MES ENFANTS
   ============================================================== */
async function loadParentChildren() {
  var c = document.getElementById('main-content');
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';
  try {
    var children = await _ppLoadChildren();
    var cardsHtml = '';
    if (children.length > 0) {
      children.forEach(function(ch, i) {
        var color = _PP_COLORS[i % _PP_COLORS.length];
        cardsHtml += '<div class="card section-card" style="padding:0;overflow:hidden;">' +
          '<div style="background:linear-gradient(135deg,' + color + ',' + color + 'dd);padding:20px;color:white;">' +
            '<div style="display:flex;justify-content:space-between;align-items:flex-start;"><div><div style="font-family:\'Sora\',sans-serif;font-size:20px;font-weight:700;">' + _ppEsc(ch.first_name) + ' ' + _ppEsc(ch.last_name) + '</div>' +
            '<div style="font-size:12px;opacity:0.8;margin-top:4px;">' + (ch.class_name || 'Non inscrit') + ' \u00b7 #' + (ch.matricule || '\u2014') + '</div></div>' +
            '<div style="width:44px;height:44px;border-radius:50%;background:rgba(255,255,255,0.2);display:grid;place-items:center;font-size:18px;font-weight:700;">' + (ch.first_name||'?')[0] + (ch.last_name||'?')[0] + '</div></div></div>' +
          '<div style="padding:16px 20px;"><button class="btn-add" style="width:100%;justify-content:center;" onclick="ppSwitchChild(' + ch.id + ');loadPage(\'p-dashboard\');"><i class="fas fa-eye"></i> Voir le suivi</button></div></div>';
      });
    } else {
      cardsHtml = '<div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-children"></i></div><h4>Aucun enfant</h4><p>Contactez l\u2019\u00e9tablissement.</p></div>';
    }
    c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;">Mes enfants</h1><p style="color:var(--texte-secondaire);">' + children.length + ' enfant(s) rattach\u00e9(s) \u00e0 votre compte.</p></div>' +
      '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;margin-top:16px;">' + cardsHtml + '</div>';
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

/* ==============================================================
   3. RÉSULTATS / NOTES (avec sélecteur de période)
   ============================================================== */
async function loadParentGrades(periodId) {
  var c = document.getElementById('main-content');
  var child = _pp.selectedChild;
  if (!child) { c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-user-graduate"></i></div><h4>S\u00e9lectionnez un enfant</h4></div></div>'; return; }
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';
  try {
    await _ppLoadChildren();
    var url = '/api/parent/children/' + child.id + '/grades';
    if (periodId) url += '?academic_period_id=' + periodId;
    var results = await Promise.all([ api(url), api('/api/academic-periods') ]);
    var gradesData = results[0]?.ok ? await results[0].json() : {};
    var pData = results[1]?.ok ? await results[1].json() : {};
    var grades = gradesData.grades || [];
    var periods = pData.periods || [];
    var avg = grades.length > 0 ? (grades.reduce(function(s, g) { return s + (g.grade || 0); }, 0) / grades.length).toFixed(1) : '\u2014';

    // Group by subject
    var bySubject = {};
    grades.forEach(function(g) {
      var key = g.evaluation_name || '\u00c9valuation';
      if (!bySubject[key]) bySubject[key] = { name: key, grades: [], avg: 0, coef: g.coefficient || 1 };
      bySubject[key].grades.push(g);
    });
    Object.values(bySubject).forEach(function(s) {
      s.avg = s.grades.length > 0 ? (s.grades.reduce(function(a, g) { return a + (g.grade || 0); }, 0) / s.grades.length).toFixed(1) : '\u2014';
    });

    var periodOpts = '<option value="">Toutes les p\u00e9riodes</option>';
    periods.forEach(function(p) {
      var sel = (periodId && p.id == periodId) ? ' selected' : '';
      periodOpts += '<option value="' + p.id + '"' + sel + '>' + p.name + (p.status === 'active' ? ' (en cours)' : '') + '</option>';
    });

    var subjectCardsHtml = '';
    Object.values(bySubject).forEach(function(s) {
      var pct = s.avg !== '\u2014' ? Math.round(s.avg / 20 * 100) : 0;
      subjectCardsHtml += '<div class="card section-card" style="padding:16px;border-left:4px solid ' + _ppGradeColor(pct) + ';">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;"><span style="font-weight:700;font-size:14px;">' + _ppEsc(s.name) + '</span>' +
        '<span style="font-size:12px;color:var(--texte-secondaire);">' + s.grades.length + ' note(s) \u00b7 Coeff. ' + s.coef + '</span></div>' +
        '<div style="font-family:\'Sora\',sans-serif;font-size:24px;font-weight:700;color:' + _ppGradeColor(pct) + ';">' + s.avg + ' <span style="font-size:14px;color:var(--texte-secondaire);">/ 20</span></div></div>';
    });

    var tableHtml = '';
    if (grades.length > 0) {
      var rows = '';
      grades.forEach(function(g) {
        var pct = g.max_grade > 0 ? (g.grade / g.max_grade * 100) : 0;
        rows += '<tr><td style="font-weight:600;">' + (g.evaluation_name || '\u2014') + '</td>' +
          '<td><span style="font-family:\'Sora\',sans-serif;font-weight:700;color:' + _ppGradeColor(pct) + '">' + _ppEsc(g.grade) + '</span></td>' +
          '<td>/' + (g.max_grade || 20) + '</td><td>' + (g.coefficient || 1) + '</td><td>' + _ppPeriodLabel(g.period) + '</td></tr>';
      });
      tableHtml = '<div class="card section-card" style="margin-top:16px;padding:0;"><div class="yiriba-table-wrap" style="border:0;border-radius:0;">' +
        '<table class="yiriba-table"><thead><tr><th>\u00c9valuation</th><th>Note</th><th>Bar\u00e8me</th><th>Coeff.</th><th>P\u00e9riode</th></tr></thead>' +
        '<tbody>' + rows + '</tbody></table></div></div>';
    }

    c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;">R\u00e9sultats de ' + _ppEsc(child.first_name) + '</h1><p style="color:var(--texte-secondaire);">Situation scolaire compl\u00e8te.</p></div>' +
      _ppChildSelector() +
      '<div style="display:flex;align-items:center;gap:10px;margin:12px 0;padding:10px 16px;background:white;border:1px solid var(--border);border-radius:10px">' +
        '<i class="fas fa-calendar-days" style="color:var(--yiriba-vert)"></i>' +
        '<span style="font-size:13px;font-weight:600;color:var(--texte-primaire)">P\u00e9riode :</span>' +
        '<select onchange="loadParentGrades(this.value)" style="padding:6px 12px;border:1px solid var(--border);border-radius:6px;font-size:13px;background:white;cursor:pointer">' + periodOpts + '</select></div>' +
      '<div class="indicator-row" style="margin-top:8px;">' +
        '<div class="indicator-card hero"><div class="indicator-icon" style="background:rgba(255,255,255,0.18)"><i class="fas fa-chart-line"></i></div><div class="indicator-info"><h4>Moyenne</h4><div class="indicator-val">' + avg + ' / 20</div><div class="indicator-sub">' + grades.length + ' note(s) \u00b7 ' + Object.keys(bySubject).length + ' mati\u00e8re(s)</div></div></div></div>' +
      (subjectCardsHtml ? '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;margin-top:16px;">' + subjectCardsHtml + '</div>' : '') +
      tableHtml;
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

/* ==============================================================
   4. PRÉSENCES (avec justification)
   ============================================================== */
async function loadParentAttendance() {
  var c = document.getElementById('main-content');
  var child = _pp.selectedChild;
  if (!child) { c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-user-graduate"></i></div><h4>S\u00e9lectionnez un enfant</h4></div></div>'; return; }
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';
  try {
    await _ppLoadChildren();
    var res = await api('/api/parent/children/' + child.id + '/attendance');
    var att = res?.ok ? (await res.json()).attendance || [] : [];
    var presentCount = att.filter(function(a) { return a.status === 'present'; }).length;
    var absentCount = att.filter(function(a) { return a.status === 'absent'; }).length;
    var lateCount = att.filter(function(a) { return a.status === 'late'; }).length;
    var unjustified = att.filter(function(a) { return a.status === 'absent' && !a.is_justified; });
    var attRate = att.length > 0 ? Math.round(presentCount / att.length * 100) : '\u2014';

    var rowsHtml = '';
    att.forEach(function(a) {
      var justifyBtn = '';
      if (a.status === 'absent' && !a.is_justified) {
        justifyBtn = '<button class="btn-secondary" style="font-size:11px;padding:4px 10px;border-radius:6px;cursor:pointer;" onclick="ppJustifyAbsence(\'' + _ppEsc(a.date) + '\', \'' + child.id + '\')"><i class="fas fa-pen"></i> Justifier</button>';
      }
      var statusHtml = _ppAttBadge(a.status);
      if (a.is_justified) statusHtml += ' <span class="badge badge-active" style="font-size:10px;">Justifi\u00e9</span>';

      rowsHtml += '<tr><td style="font-weight:600;">' + (a.date || '\u2014') + '</td><td>' + statusHtml + '</td><td>' + (a.minutes_late ? a.minutes_late + ' min' : '\u2014') + '</td><td>' + justifyBtn + '</td></tr>';
    });

    var unjustifiedHtml = '';
    if (unjustified.length > 0) {
      unjustifiedHtml = '<div class="card section-card" style="margin-top:16px;padding:16px 20px;border-left:4px solid var(--yiriba-rouge);">' +
        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;"><i class="fas fa-exclamation-triangle" style="color:var(--yiriba-rouge);"></i>' +
        '<span style="font-weight:700;font-size:14px;">' + unjustified.length + ' absence(s) non justifi\u00e9e(s)</span></div>' +
        '<p style="font-size:13px;color:var(--texte-secondaire);">Veuillez justifier les absences ci-dessous ou contacter l\u2019\u00e9tablissement.</p></div>';
    }

    var tableHtml = '';
    if (att.length > 0) {
      tableHtml = '<div class="card section-card" style="margin-top:16px;padding:0;"><div class="yiriba-table-wrap" style="border:0;border-radius:0;">' +
        '<table class="yiriba-table"><thead><tr><th>Date</th><th>Statut</th><th>Retard</th><th>Action</th></tr></thead>' +
        '<tbody>' + rowsHtml + '</tbody></table></div></div>';
    } else {
      tableHtml = '<div class="card section-card" style="margin-top:16px;"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-clipboard-check"></i></div><h4>Aucune pr\u00e9sence</h4></div></div>';
    }

    c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;">Pr\u00e9sences de ' + _ppEsc(child.first_name) + '</h1><p style="color:var(--texte-secondaire);">Suivi des pr\u00e9sences et absences.</p></div>' +
      _ppChildSelector() +
      '<div class="indicator-row" style="margin-top:8px;">' +
        '<div class="indicator-card hero"><div class="indicator-icon" style="background:rgba(255,255,255,0.18)"><i class="fas fa-clipboard-check"></i></div><div class="indicator-info"><h4>Pr\u00e9sence</h4><div class="indicator-val">' + attRate + (attRate !== '\u2014' ? '%' : '\u2014') + '</div><div class="indicator-sub">' + presentCount + ' pr\u00e9sent \u00b7 ' + lateCount + ' retard \u00b7 ' + absentCount + ' absent</div></div></div></div>' +
      unjustifiedHtml + tableHtml;
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

// Justify absence modal
function ppJustifyAbsence(absenceDate, studentId) {
  showModal('Justifier l\u2019absence',
    '<div class="modal-form">' +
      '<div style="padding:12px 16px;background:var(--surface-soft);border-radius:8px;margin-bottom:16px;">' +
        '<div style="font-size:13px;color:var(--texte-secondaire);">Absence du</div>' +
        '<div style="font-weight:700;font-size:16px;">' + absenceDate + '</div></div>' +
      '<div class="form-group"><label>Motif de la justification</label>' +
        '<textarea id="pp-justify-text" rows="4" placeholder="D\u00e9crivez le motif de l\u2019absence..." style="width:100%;padding:10px;border:1.5px solid var(--border);border-radius:8px;font-size:14px;resize:vertical;"></textarea></div>' +
      '<div style="display:flex;gap:8px;justify-content:flex-end;">' +
        '<button class="btn-secondary" onclick="closeModal()">Annuler</button>' +
        '<button class="btn-add" onclick="ppSubmitJustification(\'' + studentId + '\', \'' + absenceDate + '\')"><i class="fas fa-check"></i> Envoyer</button></div></div>');
}

async function ppSubmitJustification(studentId, date) {
  var text = document.getElementById('pp-justify-text')?.value?.trim();
  if (!text) { showToast('Veuillez saisir un motif', 'error'); return; }
  try {
    var res = await api('/api/parent/children/' + studentId + '/justify-absence', {
      method: 'POST',
      body: JSON.stringify({ date: date, justification: text })
    });
    if (res?.ok) {
      closeModal();
      showToast('Justification envoy\u00e9e avec succ\u00e8s');
      loadParentAttendance();
    } else {
      var err = await res?.json?.();
      showToast(err?.detail || 'Erreur', 'error');
    }
  } catch(e) { showToast('Erreur r\u00e9seau', 'error'); }
}

/* ==============================================================
   5. BULLETINS
   ============================================================== */
async function loadParentBulletins() {
  var c = document.getElementById('main-content');
  var child = _pp.selectedChild;
  if (!child) { c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-user-graduate"></i></div><h4>S\u00e9lectionnez un enfant</h4></div></div>'; return; }
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';
  try {
    await _ppLoadChildren();
    var res = await api('/api/parent/children/' + child.id + '/bulletins');
    var bulletins = res?.ok ? (await res.json()).bulletins || [] : [];

    var cardsHtml = '';
    if (bulletins.length > 0) {
      bulletins.forEach(function(b) {
        var data = b.data || {};
        var subjectsHtml = '';
        if (data.subjects) {
          Object.entries(data.subjects).forEach(function(entry) {
            var name = entry[0];
            var info = entry[1];
            subjectsHtml += '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);font-size:13px;">' +
              '<span>' + name + '</span><span style="font-weight:600;">' + (info.average || '\u2014') + '</span></div>';
          });
        }
        cardsHtml += '<div class="card section-card" style="padding:0;overflow:hidden;">' +
          '<div style="background:linear-gradient(135deg,var(--yiriba-vert),#063B2A);padding:20px;color:white;">' +
            '<div style="display:flex;justify-content:space-between;align-items:flex-start;">' +
              '<div><div style="font-size:12px;opacity:0.7;text-transform:uppercase;letter-spacing:1px;">' + (b.academic_year || '2025-2026') + '</div>' +
              '<div style="font-family:\'Sora\',sans-serif;font-size:18px;font-weight:700;margin-top:4px;">' + _ppPeriodLabel(b.period) + '</div></div>' +
              '<span class="badge" style="background:rgba(255,255,255,0.2);color:white;font-size:11px;">Publi\u00e9</span></div>' +
            '<div style="font-family:\'Sora\',sans-serif;font-size:32px;font-weight:700;margin-top:12px;">' + (b.overall_average || '\u2014') + ' <span style="font-size:16px;opacity:0.6;">/ 20</span></div></div>' +
          '<div style="padding:16px 20px;">' +
            '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:13px;margin-bottom:12px;">' +
              '<div><span style="color:var(--texte-secondaire);">Rang</span><div style="font-weight:700;font-size:16px;margin-top:2px;">' + (b.rank || '\u2014') + (b.total_students ? ' / ' + b.total_students : '') + '</div></div>' +
              '<div><span style="color:var(--texte-secondaire);">D\u00e9cision</span><div style="font-weight:700;font-size:16px;margin-top:2px;">' + (b.decision || '\u2014') + '</div></div></div>' +
            (subjectsHtml ? '<div style="margin-top:8px;"><div style="font-weight:600;font-size:12px;color:var(--texte-secondaire);margin-bottom:6px;">D\u00e9tail par mati\u00e8re</div>' + subjectsHtml + '</div>' : '') +
          '</div></div>';
      });
    } else {
      cardsHtml = '<div class="card section-card" style="margin-top:16px;"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-file-lines"></i></div><h4>Aucun bulletin</h4><p>Les bulletins seront publi\u00e9s par l\u2019administration.</p></div></div>';
    }
    c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;">Bulletins de ' + _ppEsc(child.first_name) + '</h1><p style="color:var(--texte-secondaire);">Consultez les bulletins.</p></div>' +
      _ppChildSelector() +
      '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(350px,1fr));gap:16px;margin-top:16px;">' + cardsHtml + '</div>';
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

/* ==============================================================
   6. PAIEMENTS / SCOLARITÉ
   ============================================================== */
async function loadParentPayments() {
  var c = document.getElementById('main-content');
  var child = _pp.selectedChild;
  if (!child) { c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-user-graduate"></i></div><h4>S\u00e9lectionnez un enfant</h4></div></div>'; return; }
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';
  try {
    await _ppLoadChildren();
    var res = await api('/api/parent/children/' + child.id + '/payments');
    var data = res?.ok ? await res.json() : {};
    var payments = data.payments || [];
    var totalPaid = data.total_paid || 0;
    var totalOwed = data.total_owed || 0;
    var balance = data.balance || 0;

    var statusHtml = '';
    if (balance <= 0) statusHtml = '<span class="badge badge-active" style="font-size:12px;"><span class="badge-dot"></span>\u00c0 jour</span>';
    else if (totalPaid > 0) statusHtml = '<span class="badge badge-warning" style="font-size:12px;"><span class="badge-dot"></span>Paiement partiel</span>';
    else statusHtml = '<span class="badge badge-danger" style="font-size:12px;"><span class="badge-dot"></span>\u00c0 payer</span>';

    var rowsHtml = '';
    payments.forEach(function(p) {
      rowsHtml += '<tr><td style="font-weight:700;">' + (p.amount || 0).toLocaleString('fr-FR') + ' FCFA</td><td>' + (p.method || '\u2014') + '</td><td>' + (p.date || '\u2014') + '</td><td><span class="badge badge-active">Confirm\u00e9</span></td><td><a href="/api/payments/' + p.id + '/receipt?token=' + (state.token || '') + '" target="_blank" style="color:var(--yiriba-vert);text-decoration:none;font-size:13px;"><i class="fas fa-receipt"></i> Re\u00e7u</a></td></tr>';
    });

    // D\u00e9tail des frais (d\u00fb / pay\u00e9 / reste par obligation)
    var items = data.items || [];
    var feesHtml = '';
    if (items.length > 0) {
      var feeRows = items.map(function(i) {
        var stBadge = i.status === 'paid'
          ? '<span class="badge badge-active"><span class="badge-dot"></span>Pay\u00e9</span>'
          : (i.status === 'partial'
            ? '<span class="badge badge-warning"><span class="badge-dot"></span>Partiel</span>'
            : '<span class="badge badge-danger"><span class="badge-dot"></span>Non pay\u00e9</span>');
        var due = i.due_date ? '<div style="font-size:11px;color:var(--texte-secondaire);">\u00c9ch\u00e9ance : ' + i.due_date + (i.overdue ? ' <span style="color:var(--yiriba-rouge);font-weight:700;">(d\u00e9pass\u00e9e)</span>' : '') + '</div>' : '';
        return '<tr><td style="font-weight:600;">' + i.name + due + '</td><td>' + (i.amount || 0).toLocaleString('fr-FR') + ' FCFA</td><td>' + (i.paid || 0).toLocaleString('fr-FR') + ' FCFA</td><td style="font-weight:700;color:' + (i.balance > 0 ? 'var(--yiriba-rouge)' : 'var(--yiriba-vert)') + ';">' + (i.balance || 0).toLocaleString('fr-FR') + ' FCFA</td><td>' + stBadge + '</td></tr>';
      }).join('');
      feesHtml = '<div class="card section-card" style="margin-top:16px;padding:0;"><div style="padding:16px 20px;border-bottom:1px solid var(--border);font-weight:700;font-size:15px;font-family:\'Sora\',sans-serif;"><i class="fas fa-file-invoice-dollar" style="color:var(--yiriba-vert);margin-right:8px;"></i>D\u00e9tail des frais</div>' +
        '<div class="yiriba-table-wrap" style="border:0;border-radius:0;"><table class="yiriba-table"><thead><tr><th>Frais</th><th>Montant d\u00fb</th><th>Pay\u00e9</th><th>Reste</th><th>Statut</th></tr></thead>' +
        '<tbody>' + feeRows + '</tbody></table></div></div>';
    }

    var overdueHtml = '';
    if ((data.overdue || []).length > 0) {
      overdueHtml = '<div class="card section-card" style="margin-top:12px;padding:14px 20px;border-left:4px solid var(--yiriba-rouge);"><div style="font-weight:700;font-size:13px;color:var(--yiriba-rouge);margin-bottom:6px;"><i class="fas fa-triangle-exclamation"></i> ' + data.overdue.length + ' \u00e9ch\u00e9ance(s) d\u00e9pass\u00e9e(s)</div>' +
        data.overdue.map(function(o) { return '<div style="font-size:12px;">\u2022 ' + _ppEsc(o.name) + ' — reste ' + (o.balance || 0).toLocaleString('fr-FR') + ' FCFA (\u00e9ch\u00e9ance ' + (o.due_date || '?') + ')</div>'; }).join('') + '</div>';
    }

    var tableHtml = '';
    if (payments.length > 0) {
      tableHtml = '<div class="card section-card" style="margin-top:16px;padding:0;"><div style="padding:16px 20px;border-bottom:1px solid var(--border);font-weight:700;font-size:15px;font-family:\'Sora\',sans-serif;"><i class="fas fa-history" style="color:var(--yiriba-vert);margin-right:8px;"></i>Historique des paiements</div>' +
        '<div class="yiriba-table-wrap" style="border:0;border-radius:0;"><table class="yiriba-table"><thead><tr><th>Montant</th><th>M\u00e9thode</th><th>Date</th><th>Statut</th><th>Re\u00e7u</th></tr></thead>' +
        '<tbody>' + rowsHtml + '</tbody></table></div></div>';
    }

    c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;">Scolarit\u00e9 de ' + _ppEsc(child.first_name) + '</h1><p style="color:var(--texte-secondaire);">Situation financi\u00e8re.</p></div>' +
      _ppChildSelector() +
      '<div class="indicator-row" style="margin-top:8px;">' +
        '<div class="indicator-card hero"><div class="indicator-icon" style="background:rgba(255,255,255,0.18)"><i class="fas fa-money-bill-wave"></i></div><div class="indicator-info"><h4>Total \u00e0 payer</h4><div class="indicator-val">' + totalOwed.toLocaleString('fr-FR') + ' FCFA</div></div></div>' +
        '<div class="indicator-card"><div class="indicator-icon" style="color:var(--yiriba-vert)"><i class="fas fa-check-circle"></i></div><div class="indicator-info"><h4>D\u00e9j\u00e0 pay\u00e9</h4><div class="indicator-val">' + totalPaid.toLocaleString('fr-FR') + ' FCFA</div></div></div>' +
        '<div class="indicator-card"><div class="indicator-icon" style="color:var(--yiriba-jaune)"><i class="fas fa-clock"></i></div><div class="indicator-info"><h4>Reste \u00e0 payer</h4><div class="indicator-val" style="color:' + (balance > 0 ? 'var(--yiriba-rouge)' : 'var(--yiriba-vert)') + ';">' + balance.toLocaleString('fr-FR') + ' FCFA</div></div></div>' +
        '<div class="indicator-card"><div class="indicator-icon"><i class="fas fa-flag"></i></div><div class="indicator-info"><h4>Statut</h4><div class="indicator-val" style="font-size:14px;">' + statusHtml + '</div></div></div></div>' +
      overdueHtml + feesHtml + tableHtml;
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

/* ==============================================================
   7. EMPLOI DU TEMPS (planning réel de la classe)
   ============================================================== */
var _ppTTView = 'week';
async function loadParentTimetable() {
  var c = document.getElementById('main-content');
  var child = _pp.selectedChild;
  if (!child) { c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-user-graduate"></i></div><h4>S\u00e9lectionnez un enfant</h4></div></div>'; return; }
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';
  try {
    await _ppLoadChildren();
    var res = await api('/api/parent/children/' + child.id + '/timetable');
    var data = res?.ok ? await res.json() : {};
    var entries = data.timetable || [];
    var days = ['Lundi','Mardi','Mercredi','Jeudi','Vendredi','Samedi'];
    var dayMap = {};
    entries.forEach(function(e) { (dayMap[e.day] = dayMap[e.day] || []).push(e); });

    var body = '';
    if (entries.length > 0) {
      if (_ppTTView === 'day') {
        // Vue journée : liste chronologique
        var todayName = days[(new Date().getDay() + 6) % 7];
        var list = dayMap[todayName] || [];
        var rows = list.length > 0 ? list.map(function(e) {
          return '<div style="display:flex;align-items:center;gap:14px;padding:12px 16px;border-bottom:1px solid var(--border);">' +
            '<div style="width:90px;flex-shrink:0;font-weight:700;font-family:\'Sora\',sans-serif;">' + _ppEsc(e.start_time) + '</div>' +
            '<div style="flex:1;"><div style="font-weight:600;font-size:14px;">' + (e.subject || '\u2014') + '</div>' +
            '<div style="font-size:12px;color:var(--texte-secondaire);">' + (e.teacher || '') + (e.room ? ' \u00b7 Salle ' + e.room : '') + '</div></div></div>';
        }).join('') : '<div class="yiriba-empty" style="padding:30px;"><div class="empty-tree"><i class="fas fa-calendar-day"></i></div><h4>Aucun cours le ' + todayName + '</h4></div>';
        body = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">' +
          '<div style="font-weight:700;font-size:14px;"><i class="fas fa-calendar-day" style="color:var(--yiriba-vert);margin-right:8px;"></i>' + todayName + '</div>' +
          '<button class="btn-secondary" style="font-size:12px;padding:6px 12px;border-radius:6px;cursor:pointer;" onclick="_ppTTView=\'week\';loadParentTimetable();"><i class="fas fa-table-cells"></i> Vue semaine</button></div>' +
          '<div class="card section-card" style="padding:0;">' + rows + '</div>';
      } else {
        // Vue semaine : grille jour x créneau
        var slots = [];
        entries.forEach(function(e) { if (slots.indexOf(e.start_time) < 0) slots.push(e.start_time); });
        slots.sort();
        var head = '<tr><th style="min-width:60px;">Heure</th>' + days.map(function(d) { return '<th>' + d + '</th>'; }).join('') + '</tr>';
        var gridRows = slots.map(function(s) {
          var tds = days.map(function(d) {
            var evs = (dayMap[d] || []).filter(function(e) { return e.start_time === s; });
            if (evs.length === 0) return '<td style="background:var(--surface-soft);opacity:0.4;"></td>';
            return '<td>' + evs.map(function(e) {
              return '<div style="background:var(--yiriba-vert);color:white;border-radius:8px;padding:6px 8px;margin:2px 0;font-size:11px;line-height:1.3;">' +
                '<div style="font-weight:700;">' + (e.subject || '\u2014') + '</div>' +
                '<div style="opacity:0.85;font-size:10px;">' + _ppEsc(e.start_time) + '\u2013' + _ppEsc(e.end_time) + '</div>' +
                (e.teacher && e.teacher !== 'Non assign\u00e9' ? '<div style="opacity:0.85;font-size:10px;">' + _ppEsc(e.teacher) + '</div>' : '') +
                (e.room ? '<div style="opacity:0.85;font-size:10px;">Salle ' + _ppEsc(e.room) + '</div>' : '') +
              '</div>';
            }).join('') + '</td>';
          });
          return '<tr><td style="font-weight:600;font-size:12px;white-space:nowrap;">' + s + '</td>' + tds.join('') + '</tr>';
        }).join('');
        body = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">' +
          '<div style="font-weight:700;font-size:14px;"><i class="fas fa-calendar-week" style="color:var(--yiriba-vert);margin-right:8px;"></i>Semaine</div>' +
          '<button class="btn-secondary" style="font-size:12px;padding:6px 12px;border-radius:6px;cursor:pointer;" onclick="_ppTTView=\'day\';loadParentTimetable();"><i class="fas fa-calendar-day"></i> Vue jour</button></div>' +
          '<div class="card section-card" style="padding:0;overflow-x:auto;"><table class="yiriba-table" style="min-width:760px;"><thead>' + head + '</thead><tbody>' + gridRows + '</tbody></table></div>';
      }
    } else {
      body = '<div class="card section-card" style="margin-top:16px;"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-calendar-days"></i></div><h4>Aucun cours planifi\u00e9</h4><p>L\u2019\u00e9tablissement n\u2019a pas encore publi\u00e9 d\u2019emploi du temps pour cette classe.</p></div></div>';
    }

    c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;">Emploi du temps de ' + _ppEsc(child.first_name) + '</h1><p style="color:var(--texte-secondaire);">Planning de la classe ' + (child.class_name || '') + '.</p></div>' +
      _ppChildSelector() + '<div style="margin-top:16px;">' + body + '</div>';
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

/* ==============================================================
   7b. SCOLARITÉ — situation détaillée
   ============================================================== */
async function loadParentScolarite() {
  var c = document.getElementById('main-content');
  var child = _pp.selectedChild;
  if (!child) { c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-user-graduate"></i></div><h4>S\u00e9lectionnez un enfant</h4></div></div>'; return; }
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';
  try {
    await _ppLoadChildren();
    var results = await Promise.all([
      api('/api/parent/children/' + child.id + '/summary'),
      api('/api/parent/children/' + child.id + '/grades'),
      api('/api/parent/children/' + child.id + '/attendance'),
      api('/api/parent/children/' + child.id + '/payments')
    ]);
    var summary = results[0]?.ok ? await results[0].json() : {};
    var gData = results[1]?.ok ? await results[1].json() : {};
    var aData = results[2]?.ok ? await results[2].json() : {};
    var pData = results[3]?.ok ? await results[3].json() : {};

    var grades = gData.grades || [];
    var att = aData.attendance || [];
    var avg = summary.grades?.average ?? (grades.length > 0 ? (grades.reduce(function(s, g) { return s + (g.grade || 0); }, 0) / grades.length).toFixed(1) : null);
    var present = summary.attendance?.present ?? att.filter(function(a) { return a.status === 'present'; }).length;
    var absent = summary.attendance?.absent ?? att.filter(function(a) { return a.status === 'absent'; }).length;
    var late = summary.attendance?.late ?? att.filter(function(a) { return a.status === 'late'; }).length;
    var attTotal = summary.attendance?.total ?? att.length;
    var attRate = attTotal > 0 ? Math.round(present / attTotal * 100) : null;
    var totalPaid = summary.payments?.total_paid ?? pData.total_paid ?? 0;
    var totalOwed = summary.payments?.total_owed ?? pData.total_owed ?? 0;
    var balance = summary.payments?.balance ?? pData.balance ?? 0;

    // Moyennes par matière
    var bySubject = {};
    grades.forEach(function(g) {
      var subj = g.subject || 'Autre';
      if (!bySubject[subj]) bySubject[subj] = { sum: 0, n: 0, coef: g.coefficient || 1 };
      bySubject[subj].sum += (g.grade || 0);
      bySubject[subj].n += 1;
    });
    var best = null, weakest = null;
    Object.entries(bySubject).forEach(function(e) {
      var m = e[1].sum / e[1].n;
      if (!best || m > best.avg) best = { name: e[0], avg: m };
      if (!weakest || m < weakest.avg) weakest = { name: e[0], avg: m };
    });

    var finStatus = balance <= 0 ? '<span class="badge badge-active"><span class="badge-dot"></span>\u00c0 jour</span>'
      : (totalPaid > 0 ? '<span class="badge badge-warning"><span class="badge-dot"></span>Partiellement pay\u00e9</span>'
        : '<span class="badge badge-danger"><span class="badge-dot"></span>\u00c0 payer</span>');

    function row(label, val) {
      return '<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);font-size:13px;"><span style="color:var(--texte-secondaire);">' + label + '</span><span style="font-weight:600;">' + (val ?? '\u2014') + '</span></div>';
    }
    function section(title, icon, inner) {
      return '<div class="card section-card" style="padding:0;overflow:hidden;">' +
        '<div style="padding:14px 20px;background:var(--surface-soft);border-bottom:1px solid var(--border);font-weight:700;font-size:14px;font-family:\'Sora\',sans-serif;">' +
        '<i class="fas ' + icon + '" style="color:var(--yiriba-vert);margin-right:8px;"></i>' + title + '</div>' +
        '<div style="padding:8px 20px 14px;">' + inner + '</div></div>';
    }

    var identite = section('Identit\u00e9', 'fa-id-card',
      row('Nom et pr\u00e9nom', child.first_name + ' ' + child.last_name) +
      row('Matricule', child.matricule) +
      row('Classe', child.class_name || 'Non inscrit') +
      row('Ann\u00e9e scolaire', summary.academic_year || '\u2014') +
      row('\u00c9tablissement', child.school_name || '\u2014'));

    var scolarite = section('Scolarit\u00e9', 'fa-school',
      row('Classe actuelle', child.class_name || '\u2014') +
      row('Niveau', child.level_name || '\u2014') +
      row('Effectif de la classe', summary.class_size ?? '\u2014'));

    var resultats = section('R\u00e9sultats', 'fa-chart-line',
      row('Moyenne g\u00e9n\u00e9rale', avg !== null ? avg + ' / 20' : 'Aucune note') +
      row('Rang', summary.grades?.rank ?? '\u2014') +
      row('Nombre d\u2019\u00e9valuations', grades.length) +
      row('Meilleure mati\u00e8re', best ? best.name + ' (' + best.avg.toFixed(1) + ') ' : '\u2014') +
      row('Mati\u00e8re \u00e0 surveiller', weakest ? weakest.name + ' (' + weakest.avg.toFixed(1) + ')' : '\u2014'));

    var presence = section('Pr\u00e9sence', 'fa-clipboard-check',
      row('Jours pr\u00e9sents', present) +
      row('Absences', absent) +
      row('Retards', late) +
      row('Taux de pr\u00e9sence', attRate !== null ? attRate + ' %' : '\u2014'));

    var finances = section('Situation financi\u00e8re', 'fa-money-bill-wave',
      row('Montant total de la scolarit\u00e9', totalOwed ? totalOwed.toLocaleString('fr-FR') + ' FCFA' : '\u2014') +
      row('Montant pay\u00e9', totalPaid.toLocaleString('fr-FR') + ' FCFA') +
      row('Reste \u00e0 payer', balance ? balance.toLocaleString('fr-FR') + ' FCFA' : '0 FCFA') +
      row('Statut', finStatus));

    c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;">Scolarit\u00e9 de ' + _ppEsc(child.first_name) + '</h1><p style="color:var(--texte-secondaire);">Situation compl\u00e8te de l\u2019enfant.</p></div>' +
      _ppChildSelector() +
      '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px;margin-top:16px;">' + identite + scolarite + resultats + presence + finances + '</div>';
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

/* ==============================================================
   7c. DEVOIRS & ÉVALUATIONS
   ============================================================== */
async function loadParentEvaluations() {
  var c = document.getElementById('main-content');
  var child = _pp.selectedChild;
  if (!child) { c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-user-graduate"></i></div><h4>S\u00e9lectionnez un enfant</h4></div></div>'; return; }
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';
  try {
    await _ppLoadChildren();
    var results = await Promise.all([ api('/api/parent/children/' + child.id + '/evaluations'), api('/api/academic-periods') ]);
    var data = results[0]?.ok ? await results[0].json() : {};
    var pData = results[1]?.ok ? await results[1].json() : {};
    var evals = data.evaluations || [];
    var periods = pData.periods || [];

    var periodOpts = '<option value="">Toutes les p\u00e9riodes</option>';
    periods.forEach(function(p) { periodOpts += '<option value="' + p.id + '">' + _ppEsc(p.name) + '</option>'; });

    var typeLabel = function(t) {
      var m = { devoir1: 'Devoir 1', devoir2: 'Devoir 2', composition: 'Composition', test: 'Test', interrogation: 'Interrogation' };
      return m[t] || t || '\u00c9valuation';
    };
    var statusBadge = function(e) {
      if (e.status === 'upcoming') return '<span class="badge badge-warning"><span class="badge-dot"></span>\u00c0 venir</span>';
      if (e.status === 'completed') return '<span class="badge badge-active"><span class="badge-dot"></span>Not\u00e9</span>';
      return '<span class="badge badge-info"><span class="badge-dot"></span>En attente</span>';
    };

    var upcoming = evals.filter(function(e) { return e.status === 'upcoming'; });
    var completed = evals.filter(function(e) { return e.status === 'completed'; });
    var pending = evals.filter(function(e) { return e.status === 'pending'; });

    var card = function(e) {
      var gradeHtml = e.status === 'completed' ?
        '<span style="font-family:\'Sora\',sans-serif;font-size:18px;font-weight:700;color:' + _ppGradeColor(e.max_score > 0 ? (e.grade / e.max_score * 100) : 0) + '">' + e.grade + '/' + (e.max_score || 20) + '</span>' :
        '<span style="font-size:12px;color:var(--texte-secondaire);">' + (e.date || '') + '</span>';
      return '<div class="card section-card" style="padding:14px 18px;display:flex;align-items:center;gap:14px;">' +
        '<div style="width:42px;height:42px;border-radius:10px;background:' + (e.status === 'upcoming' ? 'var(--yiriba-jaune)' : 'var(--yiriba-vert)') + '1a;display:grid;place-items:center;color:' + (e.status === 'upcoming' ? 'var(--yiriba-jaune)' : 'var(--yiriba-vert)') + ';font-size:15px;flex-shrink:0;"><i class="fas ' + (e.status === 'upcoming' ? 'fa-calendar-plus' : 'fa-file-pen') + '"></i></div>' +
        '<div style="flex:1;min-width:0;"><div style="font-weight:600;font-size:14px;">' + (e.name || typeLabel(e.type)) + '</div>' +
        '<div style="font-size:12px;color:var(--texte-secondaire);margin-top:2px;">' + (e.subject || '\u2014') + ' \u00b7 ' + typeLabel(e.type) + (e.period ? ' \u00b7 ' + _ppPeriodLabel(e.period) : '') + '</div></div>' +
        gradeHtml + '<div style="margin-left:8px;">' + statusBadge(e) + '</div></div>';
    };

    var block = function(title, icon, list, emptyMsg) {
      var inner = list.length > 0 ? list.map(card).join('') :
        '<div class="yiriba-empty" style="padding:30px;"><div class="empty-tree"><i class="fas ' + icon + '"></i></div><h4>' + emptyMsg + '</h4></div>';
      return '<div style="margin-top:16px;"><div style="font-weight:700;font-size:14px;margin-bottom:10px;"><i class="fas ' + icon + '" style="color:var(--yiriba-vert);margin-right:8px;"></i>' + title + ' <span style="font-size:12px;color:var(--texte-secondaire);font-weight:400;">(' + list.length + ')</span></div><div style="display:flex;flex-direction:column;gap:8px;">' + inner + '</div></div>';
    };

    c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;">Devoirs & \u00c9valuations de ' + _ppEsc(child.first_name) + '</h1><p style="color:var(--texte-secondaire);">Suivi des devoirs, compositions et r\u00e9sultats.</p></div>' +
      _ppChildSelector() +
      '<div style="display:flex;align-items:center;gap:10px;margin:12px 0;padding:10px 16px;background:white;border:1px solid var(--border);border-radius:10px">' +
        '<i class="fas fa-calendar-days" style="color:var(--yiriba-vert)"></i>' +
        '<span style="font-size:13px;font-weight:600;">P\u00e9riode :</span>' +
        '<select onchange="loadParentEvaluationsByPeriod(this.value)" style="padding:6px 12px;border:1px solid var(--border);border-radius:6px;font-size:13px;background:white;cursor:pointer">' + periodOpts + '</select></div>' +
      block('\u00c0 venir', 'fa-calendar-plus', upcoming, 'Aucun devoir \u00e0 venir') +
      block('Not\u00e9s', 'fa-file-pen', completed, 'Aucune \u00e9valuation not\u00e9e') +
      (pending.length > 0 ? block('En attente de publication', 'fa-hourglass-half', pending, '') : '');
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

async function loadParentEvaluationsByPeriod(periodId) {
  var child = _pp.selectedChild;
  if (!child) return;
  var c = document.getElementById('main-content');
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';
  try {
    var res = await api('/api/parent/children/' + child.id + '/evaluations' + (periodId ? '?period_id=' + periodId : ''));
    var data = res?.ok ? await res.json() : {};
    var evals = data.evaluations || [];
    var typeLabel = function(t) {
      var m = { devoir1: 'Devoir 1', devoir2: 'Devoir 2', composition: 'Composition', test: 'Test', interrogation: 'Interrogation' };
      return m[t] || t || '\u00c9valuation';
    };
    var statusBadge = function(e) {
      if (e.status === 'upcoming') return '<span class="badge badge-warning"><span class="badge-dot"></span>\u00c0 venir</span>';
      if (e.status === 'completed') return '<span class="badge badge-active"><span class="badge-dot"></span>Not\u00e9</span>';
      return '<span class="badge badge-info"><span class="badge-dot"></span>En attente</span>';
    };
    var rows = evals.length > 0 ? evals.map(function(e) {
      return '<tr><td style="font-weight:600;">' + (e.name || typeLabel(e.type)) + '</td><td>' + (e.subject || '\u2014') + '</td><td>' + typeLabel(e.type) + '</td><td>' + (e.date || '\u2014') + '</td><td>' + (e.grade !== null && e.grade !== undefined ? e.grade + '/' + (e.max_score || 20) : '\u2014') + '</td><td>' + statusBadge(e) + '</td></tr>';
    }).join('') : '<tr><td colspan="6" style="text-align:center;color:var(--texte-secondaire);padding:24px;">Aucune \u00e9valuation pour cette p\u00e9riode.</td></tr>';
    var child = _pp.selectedChild;
    c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;">Devoirs & \u00c9valuations de ' + _ppEsc(child.first_name) + '</h1><p style="color:var(--texte-secondaire);">Suivi des devoirs et r\u00e9sultats.</p></div>' +
      _ppChildSelector() +
      '<div class="card section-card" style="margin-top:16px;padding:0;"><div class="yiriba-table-wrap" style="border:0;border-radius:0;">' +
      '<table class="yiriba-table"><thead><tr><th>\u00c9valuation</th><th>Mati\u00e8re</th><th>Type</th><th>Date</th><th>Note</th><th>Statut</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div></div>';
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

/* ==============================================================
   7d. DOCUMENTS (bulletins publiés + reçus)
   ============================================================== */
async function loadParentDocuments() {
  var c = document.getElementById('main-content');
  var child = _pp.selectedChild;
  if (!child) { c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-user-graduate"></i></div><h4>S\u00e9lectionnez un enfant</h4></div></div>'; return; }
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';
  try {
    await _ppLoadChildren();
    var results = await Promise.all([
      api('/api/parent/children/' + child.id + '/bulletins'),
      api('/api/parent/children/' + child.id + '/payments')
    ]);
    var bData = results[0]?.ok ? await results[0].json() : {};
    var pData = results[1]?.ok ? await results[1].json() : {};
    var bulletins = bData.bulletins || [];
    var payments = pData.payments || [];

    var items = [];
    bulletins.forEach(function(b) {
      items.push({ icon: 'fa-file-lines', color: 'var(--yiriba-vert)', name: 'Bulletin ' + _ppPeriodLabel(b.period), type: 'Bulletin', date: b.generated_at || b.created_at || '', href: '/api/report-cards/' + (b.id || '') + '/pdf?token=' + (state.token || ''), action: 'T\u00e9l\u00e9charger' });
    });
    payments.forEach(function(p) {
      items.push({ icon: 'fa-receipt', color: 'var(--yiriba-jaune)', name: 'Re\u00e7u de paiement \u2013 ' + (p.amount || 0).toLocaleString('fr-FR') + ' FCFA', type: 'Re\u00e7u', date: p.date || '', href: '/api/payments/' + p.id + '/receipt?token=' + (state.token || ''), action: 'Consulter' });
    });

    var html = '';
    if (items.length > 0) {
      html = items.map(function(d) {
        var link = d.href ? '<a href="' + d.href + '" target="_blank" class="btn-secondary" style="font-size:12px;padding:7px 14px;border-radius:7px;text-decoration:none;white-space:nowrap;"><i class="fas fa-download"></i> ' + d.action + '</a>' : '';
        return '<div class="card section-card" style="padding:14px 18px;display:flex;align-items:center;gap:14px;">' +
          '<div style="width:42px;height:42px;border-radius:10px;background:' + d.color + '1a;display:grid;place-items:center;color:' + d.color + ';font-size:16px;flex-shrink:0;"><i class="fas ' + d.icon + '"></i></div>' +
          '<div style="flex:1;min-width:0;"><div style="font-weight:600;font-size:14px;">' + _ppEsc(d.name) + '</div>' +
          '<div style="font-size:12px;color:var(--texte-secondaire);margin-top:2px;">' + d.type + (d.date ? ' \u00b7 ' + (d.date || '').slice(0, 10) : '') + '</div></div>' + link + '</div>';
      }).join('');
    } else {
      html = '<div class="yiriba-empty" style="padding:40px;"><div class="empty-tree"><i class="fas fa-folder-open"></i></div><h4>Aucun document</h4><p>Les bulletins publi\u00e9s et re\u00e7us de paiement appara\u00eetront ici.</p></div>';
    }

    c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;"><i class="fas fa-folder-open" style="color:var(--yiriba-vert);margin-right:8px;"></i>Documents</h1><p style="color:var(--texte-secondaire);">Bulletins et re\u00e7us de ' + _ppEsc(child.first_name) + '.</p></div>' +
      _ppChildSelector() + '<div style="display:flex;flex-direction:column;gap:8px;margin-top:16px;">' + html + '</div>';
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

/* ==============================================================
   8. NOTIFICATIONS
   ============================================================== */
async function loadParentNotifications() {
  var c = document.getElementById('main-content');
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';
  try {
    var res = await api('/api/notifications');
    var data = res?.ok ? await res.json() : {};
    var notifications = data.notifications || [];
    var html = '';
    if (notifications.length > 0) {
      notifications.forEach(function(n) {
        var border = n.is_read ? 'var(--border)' : 'var(--yiriba-vert)';
        var titleStyle = n.is_read ? 'color:var(--texte-secondaire)' : '';
        var dateStr = n.created_at ? new Date(n.created_at).toLocaleDateString('fr-FR', {day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'}) : '';
        var readBtn = !n.is_read ? '<button onclick="ppMarkNotifRead(' + n.id + ')" style="padding:4px 10px;border:1px solid var(--border);border-radius:6px;background:white;font-size:11px;cursor:pointer;white-space:nowrap;">Marquer lu</button>' : '';
        html += '<div class="card section-card" style="padding:16px 20px;margin-bottom:8px;border-left:4px solid ' + border + ';">' +
          '<div style="display:flex;justify-content:space-between;align-items:start;">' +
            '<div><div style="font-weight:600;font-size:14px;' + titleStyle + '">' + (n.subject || n.category || 'Notification') + '</div>' +
            '<div style="font-size:13px;color:var(--texte-secondaire);margin-top:4px;">' + (n.body || '') + '</div>' +
            '<div style="font-size:11px;color:var(--texte-secondaire);margin-top:6px;">' + dateStr + '</div></div>' + readBtn + '</div></div>';
      });
    } else {
      html = '<div class="yiriba-empty" style="padding:40px;"><div class="empty-tree"><i class="fas fa-bell-slash"></i></div><h4>Aucune notification</h4><p>Vous serez notifi\u00e9 des \u00e9v\u00e9nements importants.</p></div>';
    }
    var unreadCount = notifications.filter(function(n) { return !n.is_read; }).length;
    var markAllBtn = unreadCount > 0 ? '<button class="btn-secondary" onclick="ppMarkAllNotifsRead()" style="font-size:12px;padding:7px 14px;border-radius:7px;cursor:pointer;"><i class="fas fa-check-double"></i> Tout marquer comme lu</button>' : '';
    c.innerHTML = '<div class="welcome" style="display:flex;justify-content:space-between;align-items:center;">' +
      '<div><h1 style="font-family:\'Sora\',sans-serif;"><i class="fas fa-bell" style="color:var(--yiriba-vert);margin-right:8px;"></i>Notifications</h1><p style="color:var(--texte-secondaire);">Alertes et informations importantes.</p></div>' + markAllBtn + '</div>' +
      _ppChildSelector() + '<div style="margin-top:16px;">' + html + '</div>';
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

async function ppMarkNotifRead(id) {
  try { await api('/api/notifications/mark-read', { method: 'POST', body: JSON.stringify({ notification_ids: [id] }) }); loadParentNotifications(); } catch(e) {}
}

async function ppMarkAllNotifsRead() {
  try {
    var res = await api('/api/notifications/mark-read', { method: 'POST', body: JSON.stringify({ notification_ids: null }) });
    if (res?.ok) { showToast('Toutes les notifications marqu\u00e9es comme lues'); loadParentNotifications(); }
    else { var e = await res?.json?.(); showToast(e?.detail || 'Erreur', 'error'); }
  } catch(e) { showToast('Erreur r\u00e9seau', 'error'); }
}

/* ==============================================================
   9. RAPPELS
   ============================================================== */
async function loadParentRappels() {
  var c = document.getElementById('main-content');
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';
  try {
    var child = _pp.selectedChild;
    var rappels = [];
    if (child) {
      var results = await Promise.all([
        api('/api/parent/children/' + child.id + '/payments'),
        api('/api/parent/children/' + child.id + '/attendance'),
        api('/api/parent/children/' + child.id + '/bulletins')
      ]);
      var pay = results[0]?.ok ? await results[0].json() : {};
      var att = results[1]?.ok ? (await results[1].json()).attendance || [] : [];
      var bulls = results[2]?.ok ? (await results[2].json()).bulletins || [] : [];

      if (pay.balance > 0) rappels.push({ icon: 'fa-money-bill-wave', color: 'var(--yiriba-rouge)', priority: 'important', title: 'Frais scolaires en attente', body: 'Reste \u00e0 payer : ' + (pay.balance || 0).toLocaleString('fr-FR') + ' FCFA' });
      var absences = att.filter(function(a) { return a.status === 'absent' && !a.is_justified; });
      if (absences.length > 0) rappels.push({ icon: 'fa-user-xmark', color: 'var(--yiriba-rouge)', priority: 'important', title: absences.length + ' absence(s) non justifi\u00e9e(s)', body: 'Veuillez justifier les absences.' });
      var retards = att.filter(function(a) { return a.status === 'late'; });
      if (retards.length > 0) rappels.push({ icon: 'fa-clock', color: 'var(--yiriba-jaune)', priority: 'info', title: retards.length + ' retard(s) enregistr\u00e9(s)', body: 'Pensez \u00e0 arriver \u00e0 l\u2019heure.' });
      if (bulls.length === 0) rappels.push({ icon: 'fa-file-lines', color: 'var(--yiriba-bleu,#1565C0)', priority: 'info', title: 'Aucun bulletin disponible', body: 'Les bulletins seront publi\u00e9s par l\u2019\u00e9tablissement.' });
    }

    var html = '';
    var childName = child ? child.first_name : 'votre enfant';
    if (rappels.length > 0) {
      rappels.forEach(function(r) {
        var prioColor = r.priority === 'important' ? '#fee2e2' : '#e0f2fe';
        var prioTextColor = r.priority === 'important' ? 'var(--yiriba-rouge)' : '#0369a1';
        var prioLabel = r.priority === 'important' ? 'Important' : 'Info';
        html += '<div class="card section-card" style="padding:16px 20px;margin-bottom:8px;border-left:4px solid ' + r.color + ';">' +
          '<div style="display:flex;align-items:start;gap:12px;">' +
            '<div style="width:36px;height:36px;border-radius:8px;background:' + r.color + '15;display:grid;place-items:center;color:' + r.color + ';font-size:16px;flex-shrink:0;"><i class="fas ' + r.icon + '"></i></div>' +
            '<div style="flex:1;"><div style="font-weight:600;font-size:14px;">' + _ppEsc(r.title) + '</div>' +
            '<div style="font-size:13px;color:var(--texte-secondaire);margin-top:2px;">' + r.body + '</div></div>' +
            '<span style="font-size:10px;font-weight:600;padding:2px 8px;border-radius:10px;background:' + prioColor + ';color:' + prioTextColor + ';white-space:nowrap;">' + prioLabel + '</span></div></div>';
      });
    } else {
      html = '<div class="yiriba-empty" style="padding:40px;"><div class="empty-tree"><i class="fas fa-check-circle"></i></div><h4>Aucun rappel</h4><p>Tout est \u00e0 jour pour ' + childName + '.</p></div>';
    }

    c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;"><i class="fas fa-clipboard-list" style="color:var(--yiriba-vert);margin-right:8px;"></i>Rappels</h1><p style="color:var(--texte-secondaire);">Informations importantes concernant ' + childName + '.</p></div>' +
      _ppChildSelector() + '<div style="margin-top:16px;">' + html + '</div>';
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

/* ==============================================================
   10. ÉCHANGES / MESSAGERIE
   ============================================================== */
async function loadParentMessages() {
  var c = document.getElementById('main-content');
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';
  try {
    var res = await api('/api/messages/conversations');
    var data = res?.ok ? await res.json() : {};
    var conversations = data.conversations || [];
    var html = '';
    if (conversations.length > 0) {
      conversations.forEach(function(conv) {
        var unread = conv.unread_count > 0 ? '<div style="background:var(--yiriba-vert);color:white;border-radius:10px;padding:2px 8px;font-size:11px;font-weight:600;margin-top:4px;display:inline-block;">' + conv.unread_count + '</div>' : '';
        var lastMsg = (conv.last_message && typeof conv.last_message === 'object') ? conv.last_message.content : (conv.last_message || 'Aucun message');
        var lastAt = (conv.last_message && typeof conv.last_message === 'object' && conv.last_message.created_at) ? conv.last_message.created_at : (conv.last_message_at || '');
        var dateStr = lastAt ? new Date(lastAt).toLocaleDateString('fr-FR', {day:'numeric',month:'short'}) : '';
        html += '<div class="card section-card" style="padding:16px 20px;margin-bottom:8px;cursor:pointer;" onclick="ppOpenConversation(' + conv.id + ')">' +
          '<div style="display:flex;align-items:center;gap:12px;">' +
            '<div style="width:40px;height:40px;border-radius:50%;background:var(--yiriba-vert);display:grid;place-items:center;color:white;font-size:16px;"><i class="fas fa-user"></i></div>' +
            '<div style="flex:1;"><div style="font-weight:600;font-size:14px;">' + (conv.subject || conv.other_name || 'Conversation') + '</div>' +
            '<div style="font-size:12px;color:var(--texte-secondaire);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:400px;">' + lastMsg + '</div></div>' +
            '<div style="text-align:right;"><div style="font-size:11px;color:var(--texte-secondaire);">' + dateStr + '</div>' + unread + '</div></div></div>';
      });
    } else {
      html = '<div class="yiriba-empty" style="padding:40px;"><div class="empty-tree"><i class="fas fa-comments"></i></div><h4>Aucune conversation</h4><p>Communiquez avec l\u2019\u00e9tablissement.</p></div>';
    }
    c.innerHTML = '<div class="welcome" style="display:flex;justify-content:space-between;align-items:center;">' +
      '<div><h1 style="font-family:\'Sora\',sans-serif;"><i class="fas fa-comments" style="color:var(--yiriba-vert);margin-right:8px;"></i>\u00c9changes</h1><p style="color:var(--texte-secondaire);">Communiquez avec l\u2019\u00e9tablissement.</p></div>' +
      '<button class="btn-add" onclick="ppShowNewMessage()"><i class="fas fa-plus"></i> Nouveau message</button></div>' +
      '<div style="margin-top:16px;">' + html + '</div>';
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

async function ppOpenConversation(convId) {
  var c = document.getElementById('main-content');
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';
  try {
    var res = await api('/api/messages/conversations/' + convId);
    var data = res?.ok ? await res.json() : {};
    var messages = data.messages || [];
    var convName = data.subject || 'Conversation';
    var msgHtml = '';
    messages.forEach(function(m) {
      var isMe = m.sender_id === state.user?.id;
      var bgColor = isMe ? 'background:var(--yiriba-vert);color:white;' : 'background:var(--surface-soft);';
      var align = isMe ? 'text-align:right;' : '';
      var timeColor = isMe ? 'color:rgba(255,255,255,0.7)' : 'color:var(--texte-secondaire)';
      var time = m.created_at ? new Date(m.created_at).toLocaleTimeString('fr-FR', {hour:'2-digit',minute:'2-digit'}) : '';
      msgHtml += '<div style="padding:12px 20px;border-bottom:1px solid var(--border);' + align + '">' +
        '<div style="display:inline-block;max-width:70%;padding:10px 14px;border-radius:12px;' + bgColor + '">' +
        '<div style="font-size:13px;">' + (m.content || '') + '</div>' +
        '<div style="font-size:10px;' + timeColor + ';margin-top:4px;">' + time + '</div></div></div>';
    });
    c.innerHTML = '<div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">' +
      '<button onclick="loadParentMessages()" style="padding:8px;border:1px solid var(--border);border-radius:8px;background:white;cursor:pointer;"><i class="fas fa-arrow-left"></i></button>' +
      '<h2 style="margin:0;font-family:\'Sora\',sans-serif;font-size:18px;">' + convName + '</h2></div>' +
      '<div class="card section-card" style="padding:0;max-height:60vh;overflow-y:auto;" id="msg-list">' + msgHtml + '</div>' +
      '<div style="margin-top:12px;display:flex;gap:8px;">' +
        '<input id="msg-input" style="flex:1;padding:10px 14px;border:1.5px solid var(--border);border-radius:8px;font-size:14px;" placeholder="\u00c9crire un message..." onkeydown="if(event.key===\'Enter\')ppSendMessage(' + convId + ')">' +
        '<button class="btn-add" onclick="ppSendMessage(' + convId + ')"><i class="fas fa-paper-plane"></i></button></div>';
    var list = document.getElementById('msg-list');
    if (list) list.scrollTop = list.scrollHeight;
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

async function ppSendMessage(convId) {
  var input = document.getElementById('msg-input');
  var content = input?.value?.trim();
  if (!content) return;
  try {
    await api('/api/messages/conversations/' + convId + '/messages', { method: 'POST', body: JSON.stringify({ content: content }) });
    input.value = '';
    ppOpenConversation(convId);
  } catch(e) {}
}

async function ppShowNewMessage() {
  var destOpts = '<option value="">Chargement...</option>';
  showModal('Nouveau message',
    '<div class="modal-form">' +
      '<div class="form-group"><label>Destinataire</label>' +
        '<select id="msg-dest" style="width:100%;padding:8px;border:1px solid var(--border);border-radius:6px;">' + destOpts + '</select></div>' +
      '<div class="form-group"><label>Objet</label><input id="msg-subject" placeholder="Sujet du message"></div>' +
      '<div class="form-group"><label>Message</label><textarea id="msg-body" rows="4" placeholder="Votre message..." style="width:100%;padding:8px;border:1px solid var(--border);border-radius:6px;resize:vertical;"></textarea></div>' +
      '<div style="display:flex;gap:8px;justify-content:flex-end;"><button class="btn-secondary" onclick="closeModal()">Annuler</button><button class="btn-add" onclick="ppSubmitMessage()">Envoyer</button></div></div>');
  try {
    var res = await api('/api/messages/recipients');
    var data = res?.ok ? await res.json() : {};
    var recipients = data.recipients || [];
    var roleLabel = { admin: 'Administration', directeur: 'Direction', secretaire: 'Secr\u00e9tariat', comptable: 'Comptabilit\u00e9', teacher: 'Enseignant', parent: 'Parent' };
    var opts = recipients.length > 0
      ? recipients.map(function(r) { return '<option value="' + r.id + '">' + (r.name || r.email || '') + (roleLabel[r.role] ? ' \u00b7 ' + roleLabel[r.role] : ''); }).join('')
      : '<option value="">Administration de l\u2019\u00e9cole</option>';
    var el = document.getElementById('msg-dest');
    if (el) el.innerHTML = opts;
  } catch(e) {}
}

async function ppSubmitMessage() {
  var dest = document.getElementById('msg-dest')?.value;
  var subject = document.getElementById('msg-subject')?.value?.trim();
  var body = document.getElementById('msg-body')?.value?.trim();
  if (!dest) { showToast('S\u00e9lectionnez un destinataire', 'error'); return; }
  if (!body) { showToast('Message requis', 'error'); return; }
  try {
    var payload = { recipient_id: Number(dest), content: body };
    if (subject) payload.subject = subject;
    var res = await api('/api/messages/conversations', { method: 'POST', body: JSON.stringify(payload) });
    if (res?.ok) { closeModal(); showToast('Message envoy\u00e9'); loadParentMessages(); }
    else { var e = await res?.json?.(); showToast(e?.detail || 'Erreur lors de l\u2019envoi', 'error'); }
  } catch(e) { showToast('Erreur lors de l\u2019envoi', 'error'); }
}

/* ==============================================================
   11. PARAMÈTRES
   ============================================================== */
async function loadParentSettings() {
  var c = document.getElementById('main-content');
  var fn = state.user?.first_name || '';
  var ln = state.user?.last_name || '';
  var email = state.user?.email || '';
  c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;"><i class="fas fa-gear" style="color:var(--yiriba-vert);margin-right:8px;"></i>Param\u00e8tres</h1><p style="color:var(--texte-secondaire);">G\u00e9rez votre compte.</p></div>' +
    '<div class="card section-card" style="padding:24px;margin-top:16px;max-width:500px;">' +
      '<div style="display:flex;align-items:center;gap:16px;margin-bottom:24px;">' +
        '<div style="width:60px;height:60px;border-radius:50%;background:var(--yiriba-vert);display:grid;place-items:center;color:white;font-size:24px;font-weight:700;">' + fn.charAt(0) + ln.charAt(0) + '</div>' +
        '<div><div style="font-size:18px;font-weight:700;">' + fn + ' ' + ln + '</div><div style="font-size:13px;color:var(--texte-secondaire);">' + email + '</div>' +
        '<div style="margin-top:4px;"><span class="badge badge-active">Parent</span></div></div></div>' +
      '<div style="border-top:1px solid var(--border);padding-top:16px;">' +
        '<div style="font-size:13px;font-weight:600;color:var(--texte-secondaire);margin-bottom:12px;">CHANGER LE MOT DE PASSE</div>' +
        '<div class="form-group"><label>Mot de passe actuel</label><input type="password" id="sp-current-pwd" placeholder="\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"></div>' +
        '<div class="form-group"><label>Nouveau mot de passe</label><input type="password" id="sp-new-pwd" placeholder="Min. 8 caract\u00e8res"></div>' +
        '<button class="btn-add" onclick="ppChangePassword()" style="margin-top:8px;"><i class="fas fa-check"></i> Enregistrer</button></div></div>';
}

async function ppChangePassword() {
  var current = document.getElementById('sp-current-pwd')?.value;
  var newPwd = document.getElementById('sp-new-pwd')?.value;
  if (!current || !newPwd) { showToast('Remplissez les deux champs', 'error'); return; }
  if (newPwd.length < 8) { showToast('Le mot de passe doit faire au moins 8 caract\u00e8res', 'error'); return; }
  try {
    var res = await api('/api/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password: current, new_password: newPwd }) });
    if (res?.ok) { showToast('Mot de passe modifi\u00e9'); document.getElementById('sp-current-pwd').value = ''; document.getElementById('sp-new-pwd').value = ''; }
    else { var e = await res?.json?.(); showToast(e?.detail || 'Erreur', 'error'); }
  } catch(err) { showToast('Erreur r\u00e9seau', 'error'); }
}
