/* ===================================================================
   YIRIBA — Offline Sync (Notes + Présences uniquement)
   ===================================================================
   
   Architecture :
   - File d'attente dans localStorage (max 100 entrées)
   - Sync automatique dès que la connexion revient
   - Indicateurs visuels (barre, badges, notifications)
   - Résolution de conflits : double saisie = même élève + même date/eval
   
   Modules concernés :
   - Notes (grades) : POST /api/grades
   - Présences (attendance) : POST /api/attendance/bulk
   =================================================================== */

const OfflineSync = (() => {
  const STORAGE_KEY = 'yiriba_offline_queue';
  const MAX_ITEMS = 100;

  /* -- Gestion de la file -------------------------------------- */
  
  function getQueue() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    } catch { return []; }
  }

  function saveQueue(queue) {
    // Limiter à MAX_ITEMS
    if (queue.length > MAX_ITEMS) {
      queue = queue.slice(-MAX_ITEMS);
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(queue));
    updateUI();
  }

  function enqueue(module, action, data) {
    const queue = getQueue();
    const item = {
      id: crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2),
      module,        // "grade" | "attendance"
      action,        // "create"
      data,          // payload à envoyer
      timestamp: new Date().toISOString(),
      synced: false,
      error: null,
      retries: 0,
    };
    queue.push(item);
    saveQueue(queue);
    return item.id;
  }

  function markSynced(id) {
    const queue = getQueue();
    const item = queue.find(i => i.id === id);
    if (item) {
      item.synced = true;
      item.error = null;
    }
    saveQueue(queue);
  }

  function markError(id, errorMsg) {
    const queue = getQueue();
    const item = queue.find(i => i.id === id);
    if (item) {
      item.error = errorMsg;
      item.retries = (item.retries || 0) + 1;
    }
    saveQueue(queue);
  }

  function getPending() {
    return getQueue().filter(i => !i.synced);
  }

  function getConflicts() {
    return getQueue().filter(i => i.error && i.error.includes('conflict'));
  }

  function clearSynced() {
    const queue = getQueue().filter(i => !i.synced);
    saveQueue(queue);
  }

  /* -- Sync automatique ---------------------------------------- */

  let syncing = false;

  async function syncNow() {
    if (syncing || !navigator.onLine) return;
    syncing = true;
    updateSyncStatus('syncing');

    const pending = getPending();
    let synced = 0, failed = 0;

    for (const item of pending) {
      if (!navigator.onLine) break; // Couper si on perd la connexion

      try {
        let endpoint, method, body;

        if (item.module === 'grade') {
          endpoint = '/api/grades';
          method = 'POST';
          body = JSON.stringify(item.data);
        } else if (item.module === 'attendance') {
          endpoint = '/api/attendance/bulk';
          method = 'POST';
          body = JSON.stringify(item.data);
        } else {
          continue;
        }

        const h = { 'Content-Type': 'application/json' };
        // Utiliser le token courant de app.js (refresh automatique géré par api())
        let tok = null;
        try { if (typeof state !== 'undefined' && state?.token) tok = state.token; } catch {}
        if (!tok) tok = localStorage.getItem('yiriba_token');
        if (tok) h['Authorization'] = `Bearer ${tok}`;

        const res = await fetch(`${window.location.origin}${endpoint}`, {
          method, headers: h, body,
        });

        if (res.ok) {
          markSynced(item.id);
          synced++;
        } else if (res.status === 409) {
          // Conflit : double saisie détectée
          markError(item.id, 'conflict: ' + (await res.text()));
          failed++;
        } else {
          markError(item.id, `HTTP ${res.status}`);
          failed++;
        }
      } catch (e) {
        markError(item.id, 'network: ' + e.message);
        failed++;
      }
    }

    syncing = false;
    updateSyncStatus(synced > 0 ? 'done' : 'idle');

    // Notifications
    if (synced > 0) {
      showSyncToast(`${synced} élément${synced > 1 ? 's' : ''} synchronisé${synced > 1 ? 's' : ''}`, 'success');
    }
    if (failed > 0) {
      const conflicts = getConflicts();
      if (conflicts.length > 0) {
        showSyncToast(`${conflicts.length} conflit${conflicts.length > 1 ? 's' : ''} nécessite une vérification`, 'warning');
      }
    }

    // Nettoyer les items syncés
    clearSynced();
    return { synced, failed };
  }

  /* -- UI Indicateurs ------------------------------------------ */

  function updateUI() {
    const pending = getPending();
    const count = pending.length;
    
    // Mettre à jour le compteur dans la sidebar
    const counter = document.getElementById('offline-counter');
    if (counter) {
      counter.textContent = count;
      counter.style.display = count > 0 ? 'grid' : 'none';
    }

    // Mettre à jour la barre offline
    const bar = document.getElementById('offline-bar');
    if (bar) {
      if (!navigator.onLine) {
        bar.classList.add('visible');
        bar.innerHTML = `<i class="fas fa-wifi-slash"></i> Mode hors-ligne — ${count} modification${count > 1 ? 's' : ''} en attente de synchronisation`;
      } else if (count > 0) {
        bar.classList.add('visible');
        bar.style.background = 'var(--yiriba-vert)';
        bar.style.color = 'white';
        bar.innerHTML = `<i class="fas fa-sync-alt"></i> Synchronisation en cours... ${count} modification${count > 1 ? 's' : ''} en attente`;
      } else {
        bar.classList.remove('visible');
        bar.style.background = '';
        bar.style.color = '';
      }
    }
  }

  function updateSyncStatus(status) {
    const bar = document.getElementById('offline-bar');
    if (!bar) return;

    const count = getPending().length;

    switch (status) {
      case 'syncing':
        bar.classList.add('visible');
        bar.style.background = 'var(--yiriba-vert)';
        bar.style.color = 'white';
        bar.innerHTML = `<i class="fas fa-sync-alt fa-spin"></i> Synchronisation en cours...`;
        break;
      case 'done':
        bar.style.background = 'var(--yiriba-vert)';
        bar.style.color = 'white';
        bar.innerHTML = `<i class="fas fa-check-circle"></i> Synchronisation terminée`;
        setTimeout(() => {
          bar.classList.remove('visible');
          bar.style.background = '';
          bar.style.color = '';
        }, 3000);
        break;
      case 'idle':
      default:
        updateUI();
        break;
    }
  }

  function showSyncToast(message, type) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type === 'warning' ? 'error' : ''}`;
    toast.innerHTML = `<i class="fas fa-${type === 'success' ? 'check-circle' : 'exclamation-triangle'}" style="margin-right:8px"></i>${message}`;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
  }

  /* -- Intercepteurs pour Notes et Présences ------------------- */

  /**
   * Wrapper : tente l'envoi online, sinon stocke localement.
   * Retourne { ok: true } ou { ok: false, offline: true }
   */
  async function submitGradeOrOffline(data) {
    if (navigator.onLine) {
      try {
        const token = localStorage.getItem('yiriba_token');
        const res = await fetch(`${window.location.origin}/api/grades`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
          body: JSON.stringify(data),
        });
        if (res.ok) return { ok: true };
        // Si le serveur est up mais erreur, on ne stocke PAS hors-ligne
        return { ok: false, error: await res.text() };
      } catch {
        // Erreur réseau → stocker hors-ligne
      }
    }
    // Hors-ligne ou échec réseau → stocker
    enqueue('grade', 'create', data);
    return { ok: true, offline: true, pending: getPending().length };
  }

  async function submitAttendanceOrOffline(data) {
    if (navigator.onLine) {
      try {
        const res = await api('/api/attendance/bulk', {
          method: 'POST',
          body: JSON.stringify(data),
        });
        if (res.ok) return { ok: true };
        // 401 déjà géré par api() (tentative de refresh) ; sinon message lisible
        let msg = 'Erreur lors de l\'enregistrement';
        try { const j = await res.json(); msg = (typeof j.detail === 'string') ? j.detail : msg; } catch {}
        return { ok: false, error: msg };
      } catch (e) {
        // Erreur réseau réelle (fetch rejeté) : on tente la file hors-ligne
        if (!navigator.onLine) { enqueue('attendance', 'create', data); return { ok: true, offline: true, pending: getPending().length }; }
        return { ok: false, error: 'Erreur réseau — vérifiez votre connexion' };
      }
    }
    enqueue('attendance', 'create', data);
    return { ok: true, offline: true, pending: getPending().length };
  }

  /* -- Initialisation ------------------------------------------ */

  function init() {
    // Sync au démarrage si des items en attente
    if (navigator.onLine && getPending().length > 0) {
      setTimeout(syncNow, 2000);
    }

    // Sync à la reconnexion
    window.addEventListener('online', () => {
      updateUI();
      setTimeout(syncNow, 1000);
    });

    window.addEventListener('offline', () => {
      updateUI();
    });

    updateUI();
  }

  // Auto-init
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  /* -- API publique -------------------------------------------- */
  return {
    getQueue,
    getPending,
    getConflicts,
    submitGradeOrOffline,
    submitAttendanceOrOffline,
    syncNow,
    init,
  };
})();
