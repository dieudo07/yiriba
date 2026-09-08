let _attRoster = null;

async function loadTeacherAttendance() {
  const c = document.getElementById('main-content');
  c.innerHTML = '<div class="yiriba-loading"><div class="tree-icon"><i class="fas fa-tree"></i></div><p>Chargement...</p></div>';

  try {
    const res = await api('/api/teacher/my-classes');
    const classes = res?.ok ? (await res.json()).classes || [] : [];
    _teacherState.classes = classes;
    const today = new Date().toISOString().split('T')[0];

    c.innerHTML = `
      <div class="welcome"><h1 style="font-family:'Sora',sans-serif;">Présences</h1><p style="color:var(--texte-secondaire);">Faites l'appel de vos classes en quelques secondes.</p></div>

      <div class="card section-card" style="margin-top:16px;padding:20px;">
        <div style="display:grid;grid-template-columns:1fr 1fr auto;gap:14px;align-items:end;">
          <div>
            <label style="display:block;font-size:13px;font-weight:600;color:var(--texte-secondaire);margin-bottom:6px;">Classe</label>
            <select id="t-att-class" style="width:100%;padding:10px 12px;border:1.5px solid var(--border);border-radius:8px;font-size:14px;background:white;" onchange="loadTeacherAttendanceStudents()">
              <option value="">— Sélectionner —</option>
              ${classes.map(cl => `<option value="${cl.id}">${escapeHtml(cl.name) || 'Classe'}</option>`).join('')}
            </select>
          </div>
          <div>
            <label style="display:block;font-size:13px;font-weight:600;color:var(--texte-secondaire);margin-bottom:6px;">Date</label>
            <input type="date" id="t-att-date" value="${today}" style="width:100%;padding:10px 12px;border:1.5px solid var(--border);border-radius:8px;font-size:14px;" onchange="if(document.getElementById('t-att-class').value) loadTeacherAttendanceStudents()">
          </div>
          <button class="btn-add" style="height:42px;" onclick="saveTeacherAttendance()"><i class="fas fa-save"></i> Enregistrer</button>
        </div>
      </div>

      <div id="t-att-grid-container" style="margin-top:16px;">
        <div class="yiriba-empty" style="padding:40px;">
          <div class="empty-tree"><i class="fas fa-clipboard-check"></i></div>
          <h4>Sélectionnez une classe</h4>
          <p>La grille d'appel apparaîtra ici.</p>
        </div>
      </div>
    `;
  } catch {
    c.innerHTML = '<div class="card section-card"><div class="yiriba-empty"><div class="empty-tree"><i class="fas fa-exclamation-triangle"></i></div><h4>Erreur</h4></div></div>';
  }
}

async function loadTeacherAttendanceStudents() {
  const classId = document.getElementById('t-att-class')?.value;
  if (!classId) return;
  const container = document.getElementById('t-att-grid-container');
  const attDate = document.getElementById('t-att-date')?.value;

  try {
    const res = await api(`/api/attendance/roster?class_id=${classId}&date_str=${attDate}`);
    if (!res?.ok) { container.innerHTML = '<div class="yiriba-empty" style="padding:20px;"><h4>Erreur de chargement</h4></div>'; return; }
    const roster = await res.json();
    _attRoster = roster;

    const searchHtml = `
      <div style="margin:12px 0;">
        <input id="t-att-search" type="text" placeholder="Rechercher un élève (nom, matricule)..." oninput="filterRosterRows(this.value)"
          style="width:100%;max-width:340px;padding:9px 12px;border:1.5px solid var(--border);border-radius:8px;font-size:13px;">
      </div>`;

    if (roster.students.length === 0) {
      container.innerHTML = searchHtml + '<div class="yiriba-empty" style="padding:30px;"><div class="empty-tree"><i class="fas fa-user-graduate"></i></div><h4>Aucun élève</h4></div>';
      return;
    }

    const recorded = roster.already_recorded
      ? `<div style="background:#fff8e1;border:1px solid var(--yiriba-jaune);border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:13px;"><i class="fas fa-info-circle" style="color:#b28900;"></i> Appel déjà enregistré pour cette date — vous modifiez les statuts existants.</div>` : '';

    container.innerHTML = `
      ${recorded}
      <div class="roll-call-toolbar">
        <div class="roll-call-count">${roster.count} élèves${roster.class_name ? ' — ' + escapeHtml(roster.class_name) : ''}</div>
        <div style="display:flex;gap:8px;">
          <button class="btn-mark-all-present" onclick="markAllPresent()"><i class="fas fa-check-double"></i> Tous présents</button>
          <button class="btn-secondary" onclick="saveTeacherAttendance(true)"><i class="fas fa-forward"></i> Classe suivante</button>
        </div>
      </div>
      ${searchHtml}
      <div class="card section-card" style="padding:0;">
        <div class="roll-call-grid" id="roll-call-grid">
          ${roster.students.map((st, i) => {
            const stt = st.status;
            const att = st.attendance_id;
            return `<div class="roll-call-row" data-student-id="${st.id}" data-status="${stt}" data-att-id="${att || ''}" data-name="${escapeHtml(st.last_name + ' ' + st.first_name)} ${escapeHtml(st.matricule || '')}">
              <div class="roll-call-student">
                <div class="roll-call-avatar" style="background:${_TEACHER_COLORS[i % _TEACHER_COLORS.length]};">${escapeHtml(st.first_name||'?')[0]}${escapeHtml(st.last_name||'?')[0]}</div>
                <div class="roll-call-info">
                  <div class="roll-call-name">${escapeHtml(st.first_name || '')} ${escapeHtml(st.last_name || '')}</div>
                  <div class="roll-call-matricule">${escapeHtml(st.matricule || '')}${st.justification_status === 'pending' ? ' · <span style="color:#b28900;">justification en attente</span>' : ''}${st.validated ? ' · <i class="fas fa-lock" title="Validé"></i>' : ''}</div>
                </div>
              </div>
              <div class="roll-call-actions">
                <button class="roll-btn roll-present ${stt==='present'?'active':''}" onclick="setAttendance(this,'present')" title="Présent"><i class="fas fa-check"></i></button>
                <button class="roll-btn roll-absent ${stt==='absent'?'active':''}" onclick="setAttendance(this,'absent')" title="Absent"><i class="fas fa-times"></i></button>
                <button class="roll-btn roll-late ${stt==='late'?'active':''}" onclick="setAttendance(this,'late')" title="Retard"><i class="fas fa-clock"></i></button>
                <button class="roll-btn roll-excused ${stt==='excused'?'active':''}" onclick="setAttendance(this,'excused')" title="Excusé"><i class="fas fa-shield-halved"></i></button>
                ${att ? `<button class="roll-btn" style="background:var(--yiriba-ivoire);color:var(--yiriba-vert);" onclick="openJustifyModal(${att}, '${escapeHtml(st.first_name)} ${escapeHtml(st.last_name)}', '${st.justification || ''}', '${st.justification_status}')" title="Justifier"><i class="fas fa-file-signature"></i></button>` : ''}
              </div>
            </div>`;
          }).join('')}
        </div>
      </div>`;
  } catch {
    container.innerHTML = '<div class="yiriba-empty" style="padding:20px;"><h4>Erreur de chargement</h4></div>';
  }
}

/* Marquer le statut d'un élève lors de l'appel (présent/absent/retard/excusé). */
function setAttendance(btn, status) {
  const row = btn.closest('.roll-call-row');
  if (!row) return;
  row.dataset.status = status;
  row.querySelectorAll('.roll-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
}

function filterRosterRows(q) {
  q = (q || '').toLowerCase();
  document.querySelectorAll('#roll-call-grid .roll-call-row').forEach(row => {
    row.style.display = !q || (row.dataset.name || '').toLowerCase().includes(q) ? '' : 'none';
  });
}

function openJustifyModal(attId, studentName, existing, status) {
  const statusLabel = { none: 'Non justifiée', pending: 'En attente', accepted: 'Acceptée', refused: 'Refusée' }[status] || status;
  showModal('Justifier l\'absence — ' + studentName, `
    <div class="modal-form">
      <p style="font-size:13px;color:var(--texte-secondaire);margin-bottom:12px;">Statut actuel : <strong>${statusLabel}</strong></p>
      <div class="form-group"><label>Motif / justification</label>
        <textarea id="justify-text" rows="3" style="width:100%;padding:10px;border:1.5px solid var(--border);border-radius:8px;font-size:14px;">${escapeHtml(existing || '')}</textarea>
      </div>
      <div class="modal-footer">
        <button class="btn-secondary" onclick="closeModal()">Annuler</button>
        <button class="btn-add" onclick="submitJustification(${attId})"><i class="fas fa-paper-plane"></i> Envoyer la demande</button>
      </div>
    </div>`);
}

async function submitJustification(attId) {
  const text = document.getElementById('justify-text')?.value?.trim();
  if (!text || text.length < 3) { showToast('Motif trop court', 'error'); return; }
  try {
    const res = await api(`/api/attendance/${attId}/justify`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ justification: text }),
    });
    if (res?.ok) { showToast('Demande envoyée — en attente de validation'); closeModal(); loadTeacherAttendanceStudents(); }
    else { const j = await res.json().catch(() => ({})); showToast(j.detail || 'Erreur', 'error'); }
  } catch { showToast('Erreur réseau', 'error'); }
}

/* Saisie continue : enregistre puis recharge la grille (change de classe sans quitter) */
async function saveTeacherAttendance(nextClass = false) {
  const classId = document.getElementById('t-att-class')?.value;
  const attDate = document.getElementById('t-att-date')?.value;
  if (!classId || !attDate) { showToast('Sélectionnez une classe et une date', 'error'); return; }

  const rows = document.querySelectorAll('#roll-call-grid .roll-call-row');
  const entries = [];
  rows.forEach(row => {
    if (row.style.display === 'none') return;
    entries.push({
      student_id: parseInt(row.dataset.studentId),
      status: row.dataset.status || 'present',
      is_justified: (row.dataset.status === 'excused'),
    });
  });

  if (entries.length === 0) { showToast('Aucune donnée', 'error'); return; }

  try {
    const res = await api('/api/teacher/attendance/bulk', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        class_id: parseInt(classId),
        date: attDate,
        period: (() => { const pid = document.getElementById("t-grade-period")?.value; const p = _teacherState.periods?.find(x => x.id == pid); return p ? (p.name.includes("1") ? "T1" : p.name.includes("2") ? "T2" : "T3") : "T1"; })(),
        slot_index: 0,
        entries,
      }),
    });
    if (res?.ok) {
      showToast(`${entries.length} présence(s) enregistrée(s)`);
      if (nextClass) {
        const sel = document.getElementById('t-att-class');
        const idx = sel.selectedIndex;
        if (idx < sel.options.length - 1) { sel.selectedIndex = idx + 1; loadTeacherAttendanceStudents(); }
        else showToast('Dernière classe de la liste', 'info');
      } else loadTeacherAttendanceStudents();
    }
    else showToast('Erreur lors de l\'enregistrement', 'error');
  } catch { showToast('Erreur réseau', 'error'); }
}
