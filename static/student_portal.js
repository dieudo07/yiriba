/* ==============================================================
   PORTAIL ÉLÈVE — Dashboard & fonctions complètes
   YIRIBA « Vos Racines Digitalisées »
   ============================================================== */

const studentState = { me: null, grades: [], attendance: [], bulletins: [], subjects: [], timetable: [], homework: [] };

/* -- Anti-XSS helper ------------------------------------------- */
function escapeHtml(v) {
  return String(v == null ? '' : v)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function _gradeColor(pct) {
  if (pct >= 80) return 'var(--yiriba-vert)';
  if (pct >= 50) return 'var(--yiriba-vert-feuille)';
  if (pct >= 35) return 'var(--yiriba-jaune)';
  return 'var(--yiriba-rouge)';
}
function _gradeBadge(pct) {
  if (pct >= 80) return 'badge-active';
  if (pct >= 50) return 'badge-info';
  if (pct >= 35) return 'badge-warning';
  return 'badge-danger';
}
function _attBadge(s) {
  if (s === 'present') return '<span class="badge badge-active"><span class="badge-dot"></span>Présent</span>';
  if (s === 'absent') return '<span class="badge badge-danger"><span class="badge-dot"></span>Absent</span>';
  if (s === 'late') return '<span class="badge badge-warning"><span class="badge-dot"></span>Retard</span>';
  if (s === 'excused') return '<span class="badge badge-info"><span class="badge-dot"></span>Justifié</span>';
  return '<span class="badge">' + (s || '—') + '</span>';
}
function _periodLabel(p) {
  var m = { T1: 'Trimestre 1', T2: 'Trimestre 2', T3: 'Trimestre 3', S1: 'Semestre 1', S2: 'Semestre 2' };
  return m[p] || p || '—';
}
var _AVATAR_COLORS = ['#0E5C3F','#2F8F5B','#F2B705','#C94A35','#6B4E9B','#1565C0','#E67C13'];
function _avatarColor(name) { var h = 0; for (var i = 0; i < (name||'').length; i++) h = (h * 31 + (name||'').charCodeAt(i)) & 0xFFFFFF; return _AVATAR_COLORS[h % _AVATAR_COLORS.length]; }

/* ==============================================================
   DASHBOARD ÉLÈVE
   ============================================================== */
async function loadStudentDashboard() {
  var c = document.getElementById('main-content');
  var fn = state.user?.first_name || 'Élève';
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';

  try {
    var results = await Promise.all([
      api('/api/student/me'),
      api('/api/student/me/grades'),
      api('/api/student/me/attendance'),
      api('/api/student/me/bulletins'),
      api('/api/student/me/timetable')
    ]);
    var me = results[0]?.ok ? await results[0].json() : {};
    var grades = results[1]?.ok ? (await results[1].json()).grades || [] : [];
    var att = results[2]?.ok ? (await results[2].json()).attendance || [] : [];
    var bulletins = results[3]?.ok ? (await results[3].json()).bulletins || [] : [];
    var timetable = results[4]?.ok ? (await results[4].json()).timetable || [] : [];

    studentState.me = me;
    studentState.grades = grades;
    studentState.attendance = att;
    studentState.bulletins = bulletins;
    studentState.timetable = timetable;

    var avg = grades.length > 0 ? (grades.reduce(function(s, g) { return s + (g.grade || 0); }, 0) / grades.length).toFixed(1) : '—';
    var avgPct = avg !== '—' ? Math.round(avg / 20 * 100) : 0;
    var presentCount = att.filter(function(a) { return a.status === 'present'; }).length;
    var lateCount = att.filter(function(a) { return a.status === 'late'; }).length;
    var absentCount = att.filter(function(a) { return a.status === 'absent'; }).length;
    var attRate = att.length > 0 ? Math.round(presentCount / att.length * 100) : '—';
    var latestBull = bulletins[0] || null;
    var firstName = me.first_name || fn;

    var gradesHtml = '';
    if (grades.length > 0) {
      grades.slice(0, 7).forEach(function(g) {
        var pct = g.max_grade > 0 ? (g.grade / g.max_grade * 100) : 0;
        gradesHtml += '<div style="display:flex;align-items:center;justify-content:space-between;padding:10px 8px;border-radius:8px;">' +
          '<div style="display:flex;align-items:center;gap:12px;">' +
'<div style="width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,rgba(14,92,63,0.08),rgba(47,143,91,0.06));display:grid;place-items:center;color:var(--yiriba-vert);font-size:13px;font-weight:700;flex-shrink:0;">' + escapeHtml(g.evaluation_name || '?').substring(0,2).toUpperCase() + '</div>' +
'<div><div style="font-size:13px;font-weight:600;">' + escapeHtml(g.evaluation_name || '—') + '</div>' +
            '<div style="font-size:11px;color:var(--texte-secondaire);">Coeff. ' + (g.coefficient || 1) + ' · ' + _periodLabel(g.period) + '</div></div></div>' +
          '<div style="text-align:right;"><span style="font-family:\'Sora\',sans-serif;font-size:16px;font-weight:700;color:' + _gradeColor(pct) + '">' + escapeHtml(g.grade) + '</span>' +
          '<span style="font-size:12px;color:var(--texte-secondaire);">/' + (g.max_grade || 20) + '</span></div></div>';
      });
    } else {
      gradesHtml = '<div class="yiriba-empty" style="padding:24px;"><div class="empty-tree"><i class="fas fa-pen-fancy"></i></div><h4>Aucune note</h4><p>Vos notes apparaîtront ici.</p></div>';
    }

    var bullHtml = '';
    if (latestBull) {
      bullHtml = '<div style="background:var(--surface-soft);border-radius:10px;padding:14px;">' +
        '<div style="display:flex;justify-content:space-between;margin-bottom:8px;">' +
          '<span style="font-size:12px;color:var(--texte-secondaire);">' + _periodLabel(latestBull.period) + '</span>' +
          '<span class="badge badge-active" style="font-size:11px;">Publié</span></div>' +
        '<div style="font-family:\'Sora\',sans-serif;font-size:28px;font-weight:700;color:var(--yiriba-vert);">' + (latestBull.overall_average || '—') + '</div>' +
        '<div style="font-size:12px;color:var(--texte-secondaire);">Moyenne' + (latestBull.rank ? ' · Rang ' + latestBull.rank : '') + '</div></div>';
    } else {
      bullHtml = '<div style="text-align:center;padding:12px;font-size:13px;color:var(--texte-secondaire);"><i class="fas fa-hourglass-half" style="font-size:20px;color:var(--yiriba-jaune);display:block;margin-bottom:6px;"></i>Bulletin en cours</div>';
    }

    var progressHtml = '';
    if (avg !== '—') {
      progressHtml = '<div class="card section-card" style="margin-top:16px;padding:20px;">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">' +
          '<div style="font-weight:700;font-size:14px;"><i class="fas fa-trophy" style="color:var(--yiriba-jaune);margin-right:8px;"></i>Progression</div>' +
          '<span style="font-size:24px;font-weight:700;color:' + _gradeColor(avgPct) + ';font-family:\'Sora\',sans-serif;">' + avgPct + '%</span></div>' +
        '<div style="height:10px;background:var(--yiriba-ivoire);border-radius:5px;overflow:hidden;">' +
          '<div style="height:100%;width:' + avgPct + '%;background:' + _gradeColor(avgPct) + ';border-radius:5px;"></div></div></div>';
    }

    c.innerHTML = '<div class="welcome" style="background:linear-gradient(135deg,rgba(14,92,63,0.06) 0%,rgba(47,143,91,0.03) 50%,transparent 100%);">' +
      '<h1 style="font-family:\'Sora\',sans-serif;font-size:clamp(24px,3vw,32px);">Bonjour, ' + firstName + ' ??</h1>' +
      '<p style="color:var(--texte-secondaire);font-size:15px;margin-top:6px;">Voici un aperçu de votre parcours scolaire.</p></div>' +
      '<div class="indicator-row" style="margin-top:16px;">' +
        '<div class="indicator-card hero" style="min-width:220px;"><div class="indicator-icon" style="background:rgba(255,255,255,0.18)"><i class="fas fa-user-graduate"></i></div>' +
          '<div class="indicator-info"><h4>Classe</h4><div class="indicator-val">' + (me.class_name || '—') + '</div><div class="indicator-sub">' + (me.first_name || '') + ' ' + (me.last_name || '') + ' · #' + (me.matricule || '—') + '</div></div></div>' +
        '<div class="indicator-card" style="min-width:200px;"><div class="indicator-icon" style="color:var(--yiriba-vert)"><i class="fas fa-chart-line"></i></div>' +
          '<div class="indicator-info"><h4>Moyenne</h4><div class="indicator-val" style="color:' + _gradeColor(avgPct) + '">' + avg + ' / 20</div><div class="indicator-sub">' + grades.length + ' note(s)</div></div></div>' +
        '<div class="indicator-card" style="min-width:200px;"><div class="indicator-icon" style="color:var(--yiriba-vert-feuille)"><i class="fas fa-clipboard-check"></i></div>' +
          '<div class="indicator-info"><h4>Présence</h4><div class="indicator-val">' + attRate + (attRate !== '—' ? '%' : '—') + '</div><div class="indicator-sub">' + presentCount + ' présent · ' + lateCount + ' retard · ' + absentCount + ' absent</div></div></div></div>' +
      progressHtml +
      '<div style="display:grid;grid-template-columns:1.4fr 1fr;gap:16px;margin-top:16px;">' +
        '<div class="card section-card" style="padding:0;">' +
          '<div style="padding:18px 20px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;">' +
            '<h3 style="margin:0;font-size:15px;font-family:\'Sora\',sans-serif;"><i class="fas fa-pen-fancy" style="color:var(--yiriba-vert);margin-right:8px;"></i>Dernières notes</h3>' +
            '<a style="font-size:13px;font-weight:600;color:var(--yiriba-vert-feuille);cursor:pointer;" onclick="loadPage(\'s-grades\')">Voir tout →</a></div>' +
          '<div style="padding:8px 12px;">' + gradesHtml + '</div></div>' +
        '<div style="display:flex;flex-direction:column;gap:16px;">' +
          '<div class="card section-card" style="padding:20px;cursor:pointer;" onclick="loadPage(\'s-bulletins\')">' +
            '<div style="display:flex;align-items:center;gap:14px;margin-bottom:14px;">' +
              '<div style="width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,var(--yiriba-vert),var(--yiriba-vert-feuille));display:grid;place-items:center;color:white;font-size:18px;"><i class="fas fa-file-lines"></i></div>' +
              '<div><div style="font-weight:700;font-size:14px;">Mon dernier bulletin</div><div style="font-size:12px;color:var(--texte-secondaire);">Consulter les résultats</div></div></div>' + bullHtml + '</div>' +
          '<div class="card section-card" style="padding:20px;">' +
            '<div style="font-weight:700;font-size:14px;margin-bottom:14px;"><i class="fas fa-bolt" style="color:var(--yiriba-jaune);margin-right:8px;"></i>Actions rapides</div>' +
            '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">' +
              '<button class="btn-add" style="justify-content:center;padding:12px;font-size:13px;border-radius:10px;" onclick="loadPage(\'s-grades\')"><i class="fas fa-pen-fancy"></i> Mes notes</button>' +
              '<button class="btn-secondary" style="justify-content:center;padding:12px;font-size:13px;border-radius:10px;" onclick="loadPage(\'s-timetable\')"><i class="fas fa-calendar-days"></i> Emploi du temps</button>' +
              '<button class="btn-secondary" style="justify-content:center;padding:12px;font-size:13px;border-radius:10px;" onclick="loadPage(\'s-attendance\')"><i class="fas fa-clipboard-check"></i> Présences</button>' +
              '<button class="btn-secondary" style="justify-content:center;padding:12px;font-size:13px;border-radius:10px;" onclick="loadPage(\'s-bulletins\')"><i class="fas fa-file-lines"></i> Bulletin</button>' +
            '</div></div></div></div>';
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur de chargement</h4></div></div>';
  }
}

/* ==============================================================
   MES NOTES
   ============================================================== */
async function loadStudentGrades(periodId) {
  var c = document.getElementById('main-content');
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';

  try {
    var url = '/api/student/me/grades';
    if (periodId) url += '?academic_period_id=' + periodId;
    var results = await Promise.all([ api(url), api('/api/academic-periods') ]);
    var grades = results[0]?.ok ? (await results[0].json()).grades || [] : [];
    var periods = results[1]?.ok ? (await results[1].json()).periods || [] : [];

    var periodOpts = '<option value="">Toutes les périodes</option>';
    periods.forEach(function(p) {
      var sel = (periodId && p.id == periodId) ? ' selected' : '';
      var extra = p.status === 'active' ? ' (en cours)' : '';
      periodOpts += '<option value="' + p.id + '"' + sel + '>' + p.name + extra + '</option>';
    });

    var overallAvg = grades.length > 0 ? (grades.reduce(function(s, g) { return s + (g.grade || 0); }, 0) / grades.length).toFixed(1) : '—';

    var tableHtml = '';
    if (grades.length > 0) {
      var rows = '';
      grades.forEach(function(g) {
        var pct = g.max_grade > 0 ? (g.grade / g.max_grade * 100) : 0;
        rows += '<tr><td style="font-weight:600;">' + escapeHtml(g.evaluation_name || '—') + '</td>' +
          '<td><span style="font-family:\'Sora\',sans-serif;font-size:16px;font-weight:700;color:' + _gradeColor(pct) + '">' + escapeHtml(g.grade) + '</span></td>' +
          '<td>/' + (g.max_grade || 20) + '</td><td>' + (g.coefficient || 1) + '</td><td>' + _periodLabel(g.period) + '</td>' +
          '<td style="font-style:italic;color:var(--texte-secondaire);">' + escapeHtml(g.comment || '—') + '</td></tr>';
      });
      tableHtml = '<div class="card section-card" style="margin-top:20px;padding:0;">' +
        '<div style="padding:16px 20px;border-bottom:1px solid var(--border);font-weight:700;font-size:15px;font-family:\'Sora\',sans-serif;"><i class="fas fa-list" style="color:var(--yiriba-vert);margin-right:8px;"></i>Toutes mes notes</div>' +
        '<div class="yiriba-table-wrap" style="border:0;border-radius:0;"><table class="yiriba-table"><thead><tr><th>Évaluation</th><th>Note</th><th>Barème</th><th>Coeff.</th><th>Période</th><th>Appréciation</th></tr></thead>' +
        '<tbody>' + rows + '</tbody></table></div></div>';
    }

    c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;">Mes notes</h1><p style="color:var(--texte-secondaire);">Suivi de vos résultats scolaires.</p></div>' +
      '<div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;padding:10px 16px;background:white;border:1px solid var(--border);border-radius:10px">' +
        '<i class="fas fa-calendar-days" style="color:var(--yiriba-vert)"></i>' +
        '<span style="font-size:13px;font-weight:600;color:var(--texte-primaire)">Période :</span>' +
        '<select id="s-grade-period" onchange="loadStudentGrades(this.value)" style="padding:6px 12px;border:1px solid var(--border);border-radius:6px;font-size:13px;background:white;cursor:pointer">' + periodOpts + '</select></div>' +
      '<div class="indicator-row" style="margin-top:16px;">' +
        '<div class="indicator-card hero" style="min-width:200px;"><div class="indicator-icon" style="background:rgba(255,255,255,0.18)"><i class="fas fa-chart-line"></i></div>' +
          '<div class="indicator-info"><h4>Moyenne générale</h4><div class="indicator-val">' + overallAvg + ' / 20</div><div class="indicator-sub">' + grades.length + ' note(s)</div></div></div>' +
        '<div class="indicator-card" style="min-width:160px;"><div class="indicator-icon"><i class="fas fa-star"></i></div>' +
          '<div class="indicator-info"><h4>Meilleure note</h4><div class="indicator-val">' + (grades.length > 0 ? Math.max.apply(null, grades.map(function(g) { return g.grade || 0; })) : '—') + ' / 20</div></div></div></div>' +
      tableHtml;
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

/* ==============================================================
   MES MATIÈRES
   ============================================================== */
async function loadStudentSubjects() {
  var c = document.getElementById('main-content');
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';

  try {
    var results = await Promise.all([ api('/api/student/me/grades'), api('/api/student/me') ]);
    var grades = results[0]?.ok ? (await results[0].json()).grades || [] : [];
    var me = results[1]?.ok ? await results[1].json() : {};

    var subjectMap = {};
    grades.forEach(function(g) {
      var name = g.evaluation_name || '—';
      if (!subjectMap[name]) subjectMap[name] = { name: name, grades: [], coef: g.coefficient || 1 };
      subjectMap[name].grades.push(g);
    });
    Object.values(subjectMap).forEach(function(s) {
      s.avg = s.grades.length > 0 ? (s.grades.reduce(function(a, g) { return a + (g.grade || 0); }, 0) / s.grades.length).toFixed(1) : '—';
    });
    var subjects = Object.values(subjectMap);

    var cardsHtml = '';
    if (subjects.length > 0) {
      subjects.forEach(function(s, i) {
        var avgPct = s.avg !== '—' ? Math.round(s.avg / 20 * 100) : 0;
        var color = _AVATAR_COLORS[i % _AVATAR_COLORS.length];
        cardsHtml += '<div class="card section-card" style="padding:0;overflow:hidden;">' +
          '<div style="background:linear-gradient(135deg,' + color + ',' + color + 'dd);padding:20px;color:white;">' +
            '<div style="display:flex;justify-content:space-between;align-items:flex-start;"><div><div style="font-family:\'Sora\',sans-serif;font-size:18px;font-weight:700;">' + escapeHtml(s.name) + '</div>' +
            '<div style="font-size:12px;opacity:0.8;margin-top:4px;">Coeff. ' + s.coef + '</div></div>' +
            '<div style="width:44px;height:44px;border-radius:12px;background:rgba(255,255,255,0.2);display:grid;place-items:center;font-size:20px;"><i class="fas fa-book-open"></i></div></div>' +
            '<div style="margin-top:16px;font-family:\'Sora\',sans-serif;font-size:36px;font-weight:700;">' + s.avg + ' <span style="font-size:18px;opacity:0.7;">/ 20</span></div></div>' +
          '<div style="padding:16px 20px;"><div style="display:flex;justify-content:space-between;font-size:12px;color:var(--texte-secondaire);">' +
            '<span>' + s.grades.length + ' note(s)</span><span style="font-weight:600;color:' + _gradeColor(avgPct) + '">' + avgPct + '%</span></div>' +
          '<div style="margin-top:8px;height:4px;background:var(--yiriba-ivoire);border-radius:2px;overflow:hidden;">' +
            '<div style="height:100%;width:' + avgPct + '%;background:' + _gradeColor(avgPct) + ';border-radius:2px;"></div></div></div></div>';
      });
    } else {
      cardsHtml = '<div class="card section-card" style="margin-top:16px;"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-book-open"></i></div><h4>Aucune matière</h4></div></div>';
    }

    c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;">Mes matières</h1><p style="color:var(--texte-secondaire);">' + subjects.length + ' matière(s) · Classe ' + escapeHtml(me.class_name || '—') + '</p></div>' +
      '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px;margin-top:20px;">' + cardsHtml + '</div>';
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

/* ==============================================================
   MES PRÉSENCES
   ============================================================== */
async function loadStudentAttendance() {
  var c = document.getElementById('main-content');
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';

  try {
    var res = await api('/api/student/me/attendance');
    var att = res?.ok ? (await res.json()).attendance || [] : [];
    var presentCount = att.filter(function(a) { return a.status === 'present'; }).length;
    var absentCount = att.filter(function(a) { return a.status === 'absent'; }).length;
    var lateCount = att.filter(function(a) { return a.status === 'late'; }).length;
    var attRate = att.length > 0 ? Math.round(presentCount / att.length * 100) : '—';

    var rowsHtml = '';
    att.forEach(function(a) {
      var justified = a.is_justified ? '<span class="badge badge-active">Oui</span>' : '<span style="color:var(--texte-secondaire)">Non</span>';
      rowsHtml += '<tr><td style="font-weight:600;">' + (a.date || '—') + '</td><td>' + _attBadge(a.status) + '</td><td>' + (a.minutes_late ? a.minutes_late + ' min' : '—') + '</td><td>' + justified + '</td></tr>';
    });

    var tableHtml = '';
    if (att.length > 0) {
      tableHtml = '<div class="card section-card" style="margin-top:16px;padding:0;"><div style="padding:16px 20px;border-bottom:1px solid var(--border);font-weight:700;font-size:15px;font-family:\'Sora\',sans-serif;"><i class="fas fa-calendar-days" style="color:var(--yiriba-vert);margin-right:8px;"></i>Historique</div>' +
        '<div class="yiriba-table-wrap" style="border:0;border-radius:0;"><table class="yiriba-table"><thead><tr><th>Date</th><th>Statut</th><th>Retard</th><th>Justifié</th></tr></thead><tbody>' + rowsHtml + '</tbody></table></div></div>';
    } else {
      tableHtml = '<div class="card section-card" style="margin-top:16px;"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-clipboard-check"></i></div><h4>Aucune présence</h4></div></div>';
    }

    c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;">Mes présences</h1><p style="color:var(--texte-secondaire);">Suivi de vos présences et absences.</p></div>' +
      '<div class="indicator-row" style="margin-top:16px;">' +
        '<div class="indicator-card hero"><div class="indicator-icon" style="background:rgba(255,255,255,0.18)"><i class="fas fa-clipboard-check"></i></div><div class="indicator-info"><h4>Taux</h4><div class="indicator-val">' + attRate + (attRate !== '—' ? '%' : '—') + '</div><div class="indicator-sub">' + att.length + ' jour(s)</div></div></div>' +
        '<div class="indicator-card"><div class="indicator-icon" style="color:var(--yiriba-vert)"><i class="fas fa-check-circle"></i></div><div class="indicator-info"><h4>Présents</h4><div class="indicator-val">' + presentCount + '</div></div></div>' +
        '<div class="indicator-card"><div class="indicator-icon" style="color:var(--yiriba-rouge)"><i class="fas fa-times-circle"></i></div><div class="indicator-info"><h4>Absents</h4><div class="indicator-val">' + absentCount + '</div></div></div>' +
        '<div class="indicator-card"><div class="indicator-icon" style="color:var(--yiriba-jaune)"><i class="fas fa-clock"></i></div><div class="indicator-info"><h4>Retards</h4><div class="indicator-val">' + lateCount + '</div></div></div></div>' +
      tableHtml;
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

/* ==============================================================
   MES BULLETINS
   ============================================================== */
async function loadStudentBulletins() {
  var c = document.getElementById('main-content');
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';

  try {
    var res = await api('/api/student/me/bulletins');
    var bulletins = res?.ok ? (await res.json()).bulletins || [] : [];

    var cardsHtml = '';
    if (bulletins.length > 0) {
      bulletins.forEach(function(b) {
        var avg = b.overall_average || b.average || '—';
        cardsHtml += '<div class="card section-card" style="padding:0;overflow:hidden;">' +
          '<div style="background:linear-gradient(135deg,var(--yiriba-vert),#063B2A);padding:24px;color:white;">' +
            '<div style="display:flex;justify-content:space-between;align-items:flex-start;"><div>' +
              '<div style="font-size:12px;opacity:0.7;text-transform:uppercase;letter-spacing:1px;">' + (b.academic_year || '2025-2026') + '</div>' +
              '<div style="font-family:\'Sora\',sans-serif;font-size:20px;font-weight:700;margin-top:4px;">' + _periodLabel(b.period) + '</div></div>' +
              '<span class="badge badge-active" style="background:rgba(255,255,255,0.2);color:white;"><span class="badge-dot" style="background:white;"></span>Publié</span></div>' +
            '<div style="margin-top:20px;font-family:\'Sora\',sans-serif;font-size:40px;font-weight:700;">' + avg + ' <span style="font-size:20px;opacity:0.6;">/ 20</span></div></div>' +
          '<div style="padding:18px 20px;"><div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:13px;">' +
            '<div><span style="color:var(--texte-secondaire);">Rang</span><div style="font-weight:700;font-size:16px;margin-top:2px;">' + (b.rank || '—') + (b.total_students ? ' / ' + b.total_students : '') + '</div></div>' +
            '<div><span style="color:var(--texte-secondaire);">Décision</span><div style="font-weight:700;font-size:16px;margin-top:2px;">' + (b.decision || '—') + '</div></div></div></div></div>';
      });
    } else {
      cardsHtml = '<div class="card section-card" style="margin-top:16px;"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-file-lines"></i></div><h4>Aucun bulletin</h4><p>Les bulletins seront publiés par l’administration.</p></div></div>';
    }

    c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;">Mes bulletins</h1><p style="color:var(--texte-secondaire);">Consultez vos bulletins scolaires.</p></div>' +
      '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px;margin-top:20px;">' + cardsHtml + '</div>';
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

/* ==============================================================
   EMPLOI DU TEMPS
   ============================================================== */
async function loadStudentTimetable() {
  var c = document.getElementById('main-content');
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';

  try {
    var res = await api('/api/student/me/timetable');
    var timetable = res?.ok ? (await res.json()).timetable || [] : [];

    c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;">Mon emploi du temps</h1><p style="color:var(--texte-secondaire);">' + timetable.length + ' matière(s)</p></div>' +
      '<div class="card section-card" style="margin-top:16px;"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-calendar-days"></i></div><h4>Emploi du temps</h4><p>Sera disponible prochainement.</p></div></div>';
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

/* ==============================================================
   MES DEVOIRS
   ============================================================== */
async function loadStudentHomework() {
  var c = document.getElementById('main-content');
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';

  try {
    var res = await api('/api/student/me/grades');
    var grades = res?.ok ? (await res.json()).grades || [] : [];

    var byType = {};
    grades.forEach(function(g) {
      var type = g.assessment_type || 'Devoir';
      if (!byType[type]) byType[type] = [];
      byType[type].push(g);
    });

    var cardsHtml = '';
    var keys = Object.keys(byType);
    if (keys.length > 0) {
      keys.forEach(function(type) {
        var items = byType[type];
        cardsHtml += '<div class="card section-card" style="padding:20px;">' +
          '<div style="font-weight:700;font-size:14px;margin-bottom:12px;"><i class="fas fa-book" style="color:var(--yiriba-vert);margin-right:8px;"></i>' + type + ' (' + items.length + ')</div>';
        items.forEach(function(g) {
          var pct = g.max_grade > 0 ? (g.grade / g.max_grade * 100) : 0;
          cardsHtml += '<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-top:1px solid var(--border);font-size:13px;">' +
            '<span>' + escapeHtml(g.evaluation_name || '—') + '</span>' +
            '<span style="font-weight:700;color:' + _gradeColor(pct) + ';">' + escapeHtml(g.grade) + '/' + (g.max_grade || 20) + '</span></div>';
        });
        cardsHtml += '</div>';
      });
    } else {
      cardsHtml = '<div class="card section-card" style="margin-top:16px;"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-book-bookmark"></i></div><h4>Aucun devoir</h4></div></div>';
    }

    c.innerHTML = '<div class="welcome"><h1 style="font-family:\'Sora\',sans-serif;">Mes devoirs</h1><p style="color:var(--texte-secondaire);">Évaluations et travaux.</p></div>' +
      '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;margin-top:20px;">' + cardsHtml + '</div>';
  } catch(err) {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}
