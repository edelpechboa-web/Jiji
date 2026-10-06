"use strict";
/* Jiji — interface web. Aucune dépendance externe. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n, d = 2) => (n === null || n === undefined ? "–" : Number(n).toFixed(d).replace(".", ","));
const num = (v) => (v === "" || v === null || v === undefined ? null : Number(String(v).replace(",", ".")));
const frDate = (d) => (d ? d.split("-").reverse().join("/") : "");
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
};

const state = { years: [], year: null, settings: null, user: null, school: "" };

/* ---------- Réseau ---------- */
async function api(method, path, body) {
  const res = await fetch("/api" + path, {
    method,
    headers: { "X-Requested-With": "jiji", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && path !== "/login" && path !== "/status") { showAuth(); throw new Error("Session expirée"); }
  if (!res.ok) throw new Error(data.error || `Erreur ${res.status}`);
  return data;
}
const get = (p) => api("GET", p);
const post = (p, b = {}) => api("POST", p, b);
const put = (p, b) => api("PUT", p, b);
const del = (p) => api("DELETE", p);

function toast(msg, error = false) {
  const el = document.createElement("div");
  el.className = "toast" + (error ? " error" : "");
  el.textContent = msg;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), error ? 6000 : 3000);
}
const guard = (fn) => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message, true); } };

/* ---------- Modales ---------- */
function modal(title, bodyHtml, { submitLabel = "Enregistrer", onSubmit, wide = false } = {}) {
  return new Promise((resolve) => {
    const back = document.createElement("div");
    back.className = "modal-back";
    back.innerHTML = `<form class="modal" style="${wide ? "width:min(720px,100%)" : ""}"><h2>${esc(title)}</h2>${bodyHtml}
      <div class="error-text" role="alert"></div>
      <div class="btns"><button type="button" data-cancel>Annuler</button>${onSubmit ? `<button class="primary">${esc(submitLabel)}</button>` : ""}</div></form>`;
    document.body.append(back);
    const form = $("form", back);
    const close = (v) => { back.remove(); resolve(v); };
    $("[data-cancel]", back).onclick = () => close(null);
    back.addEventListener("mousedown", (e) => { if (e.target === back) close(null); });
    back.addEventListener("keydown", (e) => { if (e.key === "Escape") close(null); });
    form.onsubmit = async (e) => {
      e.preventDefault();
      try { const r = await onSubmit(form); close(r === undefined ? true : r); }
      catch (err) { $(".error-text", back).textContent = err.message; }
    };
    const first = $("input:not([type=hidden]), select, textarea", form);
    (first || $("[data-cancel]", back)).focus();
  });
}

function fieldHtml(f, value) {
  const v = value ?? f.default ?? "";
  const req = f.required ? "required" : "";
  let input;
  if (f.type === "select") {
    const opts = (f.options || []).map((o) => `<option value="${esc(o.value)}" ${String(o.value) === String(v) ? "selected" : ""}>${esc(o.label)}</option>`).join("");
    input = `<select name="${f.name}" ${req}>${f.blank ? `<option value="">${esc(f.blank)}</option>` : ""}${opts}</select>`;
  } else if (f.type === "checkbox") {
    return `<div class="field"><label><input type="checkbox" name="${f.name}" style="width:auto" ${v ? "checked" : ""}> ${esc(f.label)}</label></div>`;
  } else if (f.type === "textarea") {
    input = `<textarea name="${f.name}" rows="6" placeholder="${esc(f.placeholder || "")}"></textarea>`;
  } else {
    const t = f.type === "number" ? "text" : f.type || "text";
    input = `<input name="${f.name}" type="${t}" value="${esc(v)}" ${req} ${f.type === "number" ? 'inputmode="decimal"' : ""} placeholder="${esc(f.placeholder || "")}" autocomplete="off">`;
  }
  return `<div class="field"><label>${esc(f.label)}${f.required ? " *" : ""}</label>${input}${f.help ? `<div class="help">${esc(f.help)}</div>` : ""}</div>`;
}
function readForm(form, fields) {
  const out = {};
  for (const f of fields) {
    const el = form.elements[f.name];
    if (!el) continue;
    out[f.name] = f.type === "checkbox" ? el.checked : el.value;
  }
  return out;
}
async function formModal(title, fields, values = {}, onSubmit, opts = {}) {
  const html = fields.map((f) => fieldHtml(f, values[f.name])).join("");
  return modal(title, html, { ...opts, onSubmit: (form) => onSubmit(readForm(form, fields)) });
}
const confirmBox = (msg, label = "Supprimer") => modal("Confirmation", `<p>${esc(msg)}</p>`, { submitLabel: label, onSubmit: () => true });

/* ---------- Authentification ---------- */
async function boot() {
  const st = await get("/status");
  state.school = st.school_name;
  if (st.setup_needed) return showAuth(true);
  if (!st.authenticated) return showAuth(false);
  state.user = st.user;
  await loadContext();
  renderShell();
  route();
}

function showAuth(setup = false) {
  $("#app").innerHTML = `<div class="auth"><form class="card" autocomplete="on">
    <div class="brand"><i style="color:#fff">J</i><div>Jiji<small>Calcul de moyennes scolaires</small></div></div>
    <h2>${setup ? "Première configuration" : "Connexion"}</h2>
    ${setup ? `<p class="muted">Créez le compte administrateur et nommez votre établissement.</p>
      <div class="field"><label>Nom de l'établissement</label><input name="school_name" placeholder="Lycée …"></div>` : ""}
    <div class="field"><label>Identifiant</label><input name="username" required autocomplete="username"></div>
    <div class="field"><label>Mot de passe${setup ? " (6 caractères min.)" : ""}</label><input name="password" type="password" required autocomplete="${setup ? "new-password" : "current-password"}"></div>
    <div class="error-text" role="alert"></div>
    <button class="primary" style="width:100%">${setup ? "Créer et démarrer" : "Se connecter"}</button></form></div>`;
  const form = $("form");
  form.username.focus();
  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      await post(setup ? "/setup" : "/login", Object.fromEntries(new FormData(form)));
      location.hash = "#/dashboard";
      boot();
    } catch (err) { $(".error-text", form).textContent = err.message; }
  };
}

async function loadContext() {
  [state.years, state.settings] = await Promise.all([get("/years"), get("/settings")]);
  state.school = state.settings.school_name;
  const saved = Number(store.get("jiji.year"));
  state.year = state.years.find((y) => y.id === saved) || state.years.find((y) => y.active) || state.years[0] || null;
}

/* ---------- Coquille / routage ---------- */
const NAV = [
  ["dashboard", "Tableau de bord", "▦"], ["sep", "Organisation"],
  ["years", "Années & périodes", "◷"], ["tracks", "Filières", "⑂"], ["subjects", "Matières", "✎"],
  ["classes", "Classes", "▤"], ["students", "Élèves", "☺"], ["sep", "Évaluation"],
  ["grades", "Saisie des notes", "✓"], ["results", "Résultats & bulletins", "★"], ["sep", "Système"],
  ["settings", "Paramètres", "⚙"],
];

function renderShell() {
  const nav = NAV.map(([id, label, icon]) => id === "sep" ? `<div class="sep">${label}</div>` : `<a href="#/${id}" data-nav="${id}"><span>${icon}</span>${label}</a>`).join("");
  $("#app").innerHTML = `<div class="shell"><aside class="sidebar"><div class="brand"><i>J</i><div>Jiji<small>${esc(state.school)}</small></div></div><nav class="nav">${nav}</nav></aside>
    <main class="main"><div class="topbar noprint"><div class="who"><label style="margin:0">Année scolaire</label>
    <select id="year-select" style="width:auto">${state.years.map((y) => `<option value="${y.id}" ${state.year && y.id === state.year.id ? "selected" : ""}>${esc(y.name)}${y.active ? " (en cours)" : ""}</option>`).join("")}</select></div>
    <div class="who"><span class="muted">${esc(state.user)}</span><button id="logout" class="small">Déconnexion</button></div></div><div id="view"></div></main></div>`;
  $("#year-select").onchange = (e) => { state.year = state.years.find((y) => y.id === Number(e.target.value)); store.set("jiji.year", state.year.id); route(); };
  $("#logout").onclick = async () => { await post("/logout"); boot(); };
}

const VIEWS = () => ({ dashboard: viewDashboard, years: viewYears, tracks: viewTracks, subjects: viewSubjects, classes: viewClasses, students: viewStudents, grades: viewGrades, results: viewResults, settings: viewSettings });

async function route() {
  if (!$("#view")) return;
  const [page = "dashboard", arg] = location.hash.replace(/^#\//, "").split("/");
  $$("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === page));
  const fresh = document.createElement("div"); // nouvel élément : supprime les écouteurs de la page précédente
  fresh.id = "view";
  $("#view").replaceWith(fresh);
  const view = fresh;
  view.innerHTML = '<p class="muted">Chargement…</p>';
  try { await (VIEWS()[page] || viewDashboard)(view, arg); }
  catch (e) { view.innerHTML = `<div class="card"><p class="bad-text">${esc(e.message)}</p></div>`; }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);

const pageHead = (title, sub = "", actions = "") => `<div class="pagehead"><div><h1>${esc(title)}</h1><p>${sub}</p></div><div class="toolbar" style="margin:0">${actions}</div></div>`;
const needYear = (view) => { if (state.year) return false; view.innerHTML = pageHead("Aucune année scolaire", "Commencez par créer une année scolaire.", '<a class="btn primary" href="#/years">Créer une année</a>'); return true; };
const classOptions = (classes) => classes.map((c) => ({ value: c.id, label: c.name + (c.track_name ? ` — ${c.track_name}` : "") }));

/* ---------- Page CRUD générique ---------- */
async function crudPage(view, { title, sub, resource, query = "", columns, fields, newLabel, defaults = {}, createExtra = {}, extraRow, onChange }) {
  const rows = await get(`/${resource}${query}`);
  view.innerHTML = pageHead(title, sub, `<button class="primary" id="add">${newLabel}</button>`) +
    (rows.length ? `<div class="table-wrap"><table><thead><tr>${columns.map((c) => `<th class="${c.cls || ""}">${esc(c.label)}</th>`).join("")}<th></th></tr></thead><tbody>
      ${rows.map((r) => `<tr>${columns.map((c) => `<td class="${c.cls || ""}">${c.render(r)}</td>`).join("")}<td><div class="actions">${extraRow ? extraRow(r) : ""}<button class="small" data-edit="${r.id}">Modifier</button><button class="small danger" data-del="${r.id}">Supprimer</button></div></td></tr>`).join("")}
    </tbody></table></div>` : '<div class="card empty">Aucun élément pour l\'instant.</div>');
  const refresh = async () => { if (onChange) await onChange(); route(); };
  const save = (id) => async (data) => { id ? await put(`/${resource}/${id}`, data) : await post(`/${resource}`, { ...data, ...createExtra }); await refresh(); toast("Enregistré"); };
  $("#add").onclick = () => formModal(newLabel, fields, defaults, save(null));
  $$("[data-edit]", view).forEach((b) => b.onclick = () => { const r = rows.find((x) => x.id === Number(b.dataset.edit)); formModal("Modifier", fields, r, save(r.id)); });
  $$("[data-del]", view).forEach((b) => b.onclick = async () => {
    const r = rows.find((x) => x.id === Number(b.dataset.del));
    if (await confirmBox(`Supprimer « ${r.name || r.title || r.last_name || r.subject_name} » ? Les données associées seront également supprimées.`)) guard(async () => { await del(`/${resource}/${r.id}`); await refresh(); toast("Supprimé"); })();
  });
  return rows;
}

/* ---------- Tableau de bord ---------- */
async function viewDashboard(view) {
  if (needYear(view)) return;
  const d = await get(`/dashboard?year_id=${state.year.id}`);
  const c = d.counts;
  const stat = (v, l) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`;
  view.innerHTML = pageHead("Tableau de bord", `Année scolaire ${esc(state.year.name)}`) +
    `<div class="grid cols4" style="margin-bottom:16px">${stat(c.students, "Élèves")}${stat(c.classes, "Classes")}${stat(c.subjects, "Matières")}${stat(c.tracks, "Filières")}${stat(c.evaluations, "Évaluations")}</div>
    <div class="grid cols2"><div class="card"><h2>Moyennes par classe</h2>${d.classes.length ? `<table><thead><tr><th>Classe</th><th class="num">Élèves</th><th>Période</th><th class="num">Moyenne</th><th class="num">Réussite</th></tr></thead><tbody>
      ${d.classes.map((k) => `<tr><td><a href="#/results" data-class="${k.id}">${esc(k.name)}</a><div class="muted">${esc(k.track || "")}</div></td><td class="num">${k.students}</td><td>${esc(k.period || "–")}</td>
      <td class="num">${k.avg === null ? "–" : `<b>${fmt(k.avg)}</b>`}</td><td class="num">${k.pass_rate === null ? "–" : `<div class="bar good" title="${fmt(k.pass_rate, 0)} %"><i style="width:${k.pass_rate}%"></i></div>${fmt(k.pass_rate, 0)} %`}</td></tr>`).join("")}</tbody></table>` : '<p class="empty">Aucune classe. <a href="#/classes">Créer une classe</a></p>'}</div>
    <div class="card"><h2>Meilleurs élèves</h2>${d.top.length ? `<table><tbody>${d.top.map((t, i) => `<tr><td>${i + 1}</td><td>${esc(t.name)}<div class="muted">${esc(t.class)} · ${esc(t.period)}</div></td><td class="num"><b>${fmt(t.average)}</b></td></tr>`).join("")}</tbody></table>` : '<p class="empty">Saisissez des notes pour voir le classement.</p>'}</div></div>
    ${c.students === 0 ? `<div class="card"><h2>Pour démarrer</h2><ol><li><a href="#/years">Créez les périodes</a> (trimestres ou semestres)</li><li>Ajoutez des <a href="#/tracks">filières</a>, <a href="#/subjects">matières</a> et <a href="#/classes">classes</a></li><li>Affectez les matières et coefficients à chaque classe</li><li>Importez ou saisissez les <a href="#/students">élèves</a></li><li>Créez des évaluations et saisissez les <a href="#/grades">notes</a></li><li>Consultez les <a href="#/results">résultats et bulletins</a></li></ol></div>` : ""}`;
  $$("[data-class]", view).forEach((a) => a.onclick = () => store.set("jiji.results.class", a.dataset.class));
}

/* ---------- Années & périodes ---------- */
async function viewYears(view) {
  const years = await get("/years");
  const periods = state.year ? await get(`/periods?year_id=${state.year.id}`) : [];
  const refreshCtx = async () => { await loadContext(); renderShell(); route(); };
  const yfields = [{ name: "name", label: "Année scolaire", required: true, placeholder: "2025-2026" }, { name: "active", label: "Année en cours", type: "checkbox" }];
  const pfields = [{ name: "name", label: "Nom", required: true, placeholder: "Trimestre 1" }, { name: "weight", label: "Poids dans la moyenne annuelle", type: "number", default: 1, help: "1 = poids normal ; 2 = compte double" }, { name: "position", label: "Ordre", type: "number", default: periods.length + 1 }];
  view.innerHTML = pageHead("Années & périodes", "Définissez les années scolaires et leur découpage.", '<button class="primary" id="add-year">Nouvelle année</button>') +
    `<div class="card"><h2>Années scolaires</h2><table><thead><tr><th>Année</th><th>État</th><th></th></tr></thead><tbody>${years.map((y) => `<tr><td>${esc(y.name)}</td><td>${y.active ? '<span class="badge good">En cours</span>' : ""}</td>
      <td><div class="actions">${y.active ? "" : `<button class="small" data-activate="${y.id}">Définir en cours</button>`}<button class="small" data-edit-y="${y.id}">Modifier</button><button class="small danger" data-del-y="${y.id}">Supprimer</button></div></td></tr>`).join("") || '<tr><td colspan="3" class="empty">Aucune année.</td></tr>'}</tbody></table></div>
    ${state.year ? `<div class="card"><h2>Périodes — ${esc(state.year.name)}<span class="toolbar" style="margin:0"><button class="small" data-preset="trimestre">+ 3 trimestres</button><button class="small" data-preset="semestre">+ 2 semestres</button><button class="small primary" id="add-period">Ajouter une période</button></span></h2>
      <table><thead><tr><th>Ordre</th><th>Nom</th><th class="num">Poids</th><th></th></tr></thead><tbody>${periods.map((p) => `<tr><td>${p.position}</td><td>${esc(p.name)}</td><td class="num">${fmt(p.weight, 1)}</td>
      <td><div class="actions"><button class="small" data-edit-p="${p.id}">Modifier</button><button class="small danger" data-del-p="${p.id}">Supprimer</button></div></td></tr>`).join("") || '<tr><td colspan="4" class="empty">Aucune période : utilisez les raccourcis ci-dessus.</td></tr>'}</tbody></table></div>` : ""}`;
  const saveYear = (id) => async (d) => { id ? await put(`/years/${id}`, d) : await post("/years", d); await refreshCtx(); };
  $("#add-year").onclick = () => formModal("Nouvelle année scolaire", yfields, {}, saveYear(null));
  $$("[data-edit-y]", view).forEach((b) => b.onclick = () => { const y = years.find((x) => x.id === +b.dataset.editY); formModal("Modifier l'année", yfields, y, saveYear(y.id)); });
  $$("[data-activate]", view).forEach((b) => b.onclick = guard(async () => { await put(`/years/${b.dataset.activate}`, { active: true }); await refreshCtx(); }));
  $$("[data-del-y]", view).forEach((b) => b.onclick = async () => { if (await confirmBox("Supprimer cette année et TOUTES ses classes, élèves et notes ?")) guard(async () => { await del(`/years/${b.dataset.delY}`); await refreshCtx(); })(); });
  $$("[data-preset]", view).forEach((b) => b.onclick = guard(async () => { await post(`/years/${state.year.id}/periods/preset`, { kind: b.dataset.preset }); route(); }));
  const savePeriod = (id) => async (d) => { id ? await put(`/periods/${id}`, d) : await post("/periods", { ...d, year_id: state.year.id }); route(); };
  $("#add-period")?.addEventListener("click", () => formModal("Nouvelle période", pfields, {}, savePeriod(null)));
  $$("[data-edit-p]", view).forEach((b) => b.onclick = () => { const p = periods.find((x) => x.id === +b.dataset.editP); formModal("Modifier la période", pfields, p, savePeriod(p.id)); });
  $$("[data-del-p]", view).forEach((b) => b.onclick = async () => { if (await confirmBox("Supprimer cette période et les évaluations associées ?")) guard(async () => { await del(`/periods/${b.dataset.delP}`); route(); })(); });
}

/* ---------- Filières & matières ---------- */
const viewTracks = (view) => crudPage(view, {
  title: "Filières", sub: "Séries ou filières d'enseignement (Sciences, Lettres, Économie…).", resource: "tracks", newLabel: "Nouvelle filière",
  columns: [{ label: "Filière", render: (r) => `<b>${esc(r.name)}</b>` }, { label: "Code", render: (r) => esc(r.code) }, { label: "Classes", cls: "num", render: (r) => r.class_count }],
  fields: [{ name: "name", label: "Nom de la filière", required: true }, { name: "code", label: "Code", placeholder: "S, L, ES…" }],
});
const viewSubjects = (view) => crudPage(view, {
  title: "Matières", sub: "Catalogue des matières ; les coefficients se règlent par classe.", resource: "subjects", newLabel: "Nouvelle matière",
  columns: [{ label: "Matière", render: (r) => `<b>${esc(r.name)}</b>` }, { label: "Code", render: (r) => esc(r.code) }, { label: "Utilisée dans", cls: "num", render: (r) => `${r.class_count} classe(s)` }],
  fields: [{ name: "name", label: "Nom de la matière", required: true }, { name: "code", label: "Abréviation", placeholder: "MATH" }],
});

/* ---------- Classes ---------- */
async function viewClasses(view, arg) {
  if (needYear(view)) return;
  if (arg) return viewClassDetail(view, Number(arg));
  const tracks = await get("/tracks");
  const fields = [{ name: "name", label: "Nom de la classe", required: true, placeholder: "2nde S1" },
    { name: "track_id", label: "Filière", type: "select", blank: "— Aucune —", options: tracks.map((t) => ({ value: t.id, label: t.name })) }];
  await crudPage(view, {
    title: "Classes", sub: `Année scolaire ${esc(state.year.name)}`, resource: "classes", query: `?year_id=${state.year.id}`, newLabel: "Nouvelle classe",
    createExtra: { year_id: state.year.id }, fields,
    columns: [{ label: "Classe", render: (r) => `<a href="#/classes/${r.id}"><b>${esc(r.name)}</b></a>` }, { label: "Filière", render: (r) => esc(r.track_name || "–") },
      { label: "Élèves", cls: "num", render: (r) => r.student_count }, { label: "Matières", cls: "num", render: (r) => r.subject_count }],
    extraRow: (r) => `<a class="btn small" href="#/classes/${r.id}">Matières & coefficients</a>`,
  });
}

async function viewClassDetail(view, id) {
  const [cls, subs, allSubjects, classes] = await Promise.all([get(`/classes/${id}`), get(`/class-subjects?class_id=${id}`), get("/subjects"), get(`/classes?year_id=${state.year.id}`)]);
  const used = new Set(subs.map((s) => s.subject_id));
  const free = allSubjects.filter((s) => !used.has(s.id));
  const total = subs.reduce((a, s) => a + s.coef, 0);
  view.innerHTML = `<div class="crumbs"><a href="#/classes">Classes</a> › ${esc(cls.name)}</div>` + pageHead(`Classe ${cls.name}`, `${esc(cls.track_name || "Sans filière")} · ${cls.student_count} élève(s)`,
    `<a class="btn" href="#/students" id="to-students">Voir les élèves</a><button id="copy">Copier d'une autre classe</button><button class="primary" id="add">Affecter une matière</button>`) +
    `<div class="card"><h2>Matières & coefficients <span class="muted">Total des coefficients : ${fmt(total, 1)}</span></h2>
    ${subs.length ? `<table><thead><tr><th>Matière</th><th>Enseignant</th><th class="num">Coefficient</th><th></th></tr></thead><tbody>${subs.map((s) => `<tr><td><b>${esc(s.subject_name)}</b></td><td>${esc(s.teacher || "–")}</td><td class="num">${fmt(s.coef, 1)}</td>
    <td><div class="actions"><button class="small" data-edit="${s.id}">Modifier</button><button class="small danger" data-del="${s.id}">Retirer</button></div></td></tr>`).join("")}</tbody></table>` : '<p class="empty">Aucune matière affectée à cette classe.</p>'}</div>`;
  $("#to-students").onclick = () => store.set("jiji.students.class", id);
  const fields = (withSubject) => [
    ...(withSubject ? [{ name: "subject_id", label: "Matière", type: "select", required: true, options: free.map((s) => ({ value: s.id, label: s.name })) }] : []),
    { name: "coef", label: "Coefficient", type: "number", default: 1, required: true }, { name: "teacher", label: "Enseignant (facultatif)" }];
  $("#add").onclick = () => free.length ? formModal("Affecter une matière", fields(true), {}, async (d) => { await post("/class-subjects", { ...d, class_id: id }); route(); }) : toast("Toutes les matières sont déjà affectées. Créez-en une dans « Matières ».", true);
  $$("[data-edit]", view).forEach((b) => b.onclick = () => { const s = subs.find((x) => x.id === +b.dataset.edit); formModal(`Modifier — ${s.subject_name}`, fields(false), s, async (d) => { await put(`/class-subjects/${s.id}`, d); route(); }); });
  $$("[data-del]", view).forEach((b) => b.onclick = async () => { if (await confirmBox("Retirer cette matière ? Les évaluations et notes correspondantes seront supprimées.", "Retirer")) guard(async () => { await del(`/class-subjects/${b.dataset.del}`); route(); })(); });
  $("#copy").onclick = () => formModal("Copier les matières", [{ name: "from_class_id", label: "Classe source", type: "select", required: true, options: classOptions(classes.filter((c) => c.id !== id)) }], {},
    async (d) => { await post(`/classes/${id}/subjects/copy`, d); route(); }, { submitLabel: "Copier" });
}

/* ---------- Élèves ---------- */
async function viewStudents(view) {
  if (needYear(view)) return;
  const classes = await get(`/classes?year_id=${state.year.id}`);
  let classId = store.get("jiji.students.class") || "";
  if (classId && !classes.some((c) => String(c.id) === String(classId))) classId = "";
  const search = view.dataset.q || "";
  const q = `?year_id=${state.year.id}${classId ? `&class_id=${classId}` : ""}`;
  const students = await get(`/students${q}`);
  view.innerHTML = pageHead("Élèves", `${students.length} élève(s) · année ${esc(state.year.name)}`,
    `<button id="import" ${classId ? "" : "disabled title=\"Choisissez d'abord une classe\""}>Importer (CSV)</button><button class="primary" id="add" ${classes.length ? "" : "disabled"}>Nouvel élève</button>`) +
    `<div class="toolbar"><div class="field"><label>Classe</label><select id="f-class"><option value="">Toutes les classes</option>${classes.map((c) => `<option value="${c.id}" ${String(c.id) === String(classId) ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select></div>
    <div class="field grow"><label>Recherche</label><input id="f-q" placeholder="Nom, prénom ou matricule" value="${esc(search)}"></div></div>
    <div class="table-wrap"><table><thead><tr><th>Matricule</th><th>Nom</th><th>Prénom</th><th>Sexe</th><th>Naissance</th><th>Classe</th><th></th></tr></thead><tbody id="rows"></tbody></table></div>`;
  const fields = [
    { name: "last_name", label: "Nom", required: true }, { name: "first_name", label: "Prénom(s)", required: true },
    { name: "class_id", label: "Classe", type: "select", required: true, options: classOptions(classes), default: classId },
    { name: "matricule", label: "Matricule", help: "Laissez vide pour générer automatiquement." },
    { name: "sex", label: "Sexe", type: "select", blank: "—", options: [{ value: "M", label: "Masculin" }, { value: "F", label: "Féminin" }] },
    { name: "birth_date", label: "Date de naissance", type: "date" }];
  const draw = () => {
    const needle = ($("#f-q").value || "").toLowerCase();
    view.dataset.q = $("#f-q").value;
    const list = students.filter((s) => !needle || `${s.last_name} ${s.first_name} ${s.matricule}`.toLowerCase().includes(needle));
    $("#rows").innerHTML = list.map((s) => `<tr><td>${esc(s.matricule)}</td><td><b>${esc(s.last_name.toUpperCase())}</b></td><td>${esc(s.first_name)}</td><td>${esc(s.sex)}</td><td>${frDate(s.birth_date)}</td><td>${esc(s.class_name)}</td>
      <td><div class="actions"><button class="small" data-edit="${s.id}">Modifier</button><button class="small danger" data-del="${s.id}">Supprimer</button></div></td></tr>`).join("") || '<tr><td colspan="7" class="empty">Aucun élève.</td></tr>';
  };
  draw();
  $("#f-q").oninput = draw;
  $("#f-class").onchange = (e) => { store.set("jiji.students.class", e.target.value); route(); };
  const save = (id) => async (d) => { id ? await put(`/students/${id}`, d) : await post("/students", d); route(); };
  $("#add").onclick = () => formModal("Nouvel élève", fields, {}, save(null));
  view.onclick = (e) => {
    const b = e.target.closest("button[data-edit], button[data-del]"); if (!b) return;
    if (b.dataset.edit) { const s = students.find((x) => x.id === +b.dataset.edit); formModal("Modifier l'élève", fields, s, save(s.id)); }
    else { const s = students.find((x) => x.id === +b.dataset.del); confirmBox(`Supprimer ${s.first_name} ${s.last_name} et toutes ses notes ?`).then((ok) => ok && guard(async () => { await del(`/students/${s.id}`); route(); })()); }
  };
  $("#import").onclick = () => modal("Importer des élèves (CSV)", `<p class="muted">Colonnes : <code>matricule ; nom ; prénom ; sexe ; date de naissance</code> (séparateur ; , ou tabulation, avec ou sans ligne d'en-tête). Le matricule est facultatif. Les élèves déjà présents (même matricule) sont mis à jour.</p>
    <div class="field"><label>Fichier CSV</label><input type="file" id="csv-file" accept=".csv,.txt,text/csv"></div><div class="field"><label>… ou collez le contenu</label><textarea name="csv" rows="7" placeholder="DIALLO;Awa;F;03/04/2009"></textarea></div>`, {
    submitLabel: "Importer", onSubmit: async (form) => {
      const file = $("#csv-file").files[0]; const text = file ? await file.text() : form.csv.value;
      const r = await post(`/classes/${classId}/students/import`, { csv: text });
      toast(`${r.created} ajouté(s), ${r.updated} mis à jour${r.errors.length ? `, ${r.errors.length} erreur(s)` : ""}`, r.errors.length > 0);
      if (r.errors.length) await modal("Lignes ignorées", `<ul>${r.errors.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`);
      route();
    } });
}

/* ---------- Saisie des notes ---------- */
async function viewGrades(view, arg) {
  if (needYear(view)) return;
  if (arg) return viewGradeSheet(view, Number(arg));
  const [classes, periods] = await Promise.all([get(`/classes?year_id=${state.year.id}`), get(`/periods?year_id=${state.year.id}`)]);
  const f = JSON.parse(store.get("jiji.grades.filter") || "{}");
  if (!classes.some((c) => c.id === f.class_id)) f.class_id = classes[0]?.id;
  if (!periods.some((p) => p.id === f.period_id)) f.period_id = periods[0]?.id;
  if (!f.class_id || !periods.length) {
    view.innerHTML = pageHead("Saisie des notes") + `<div class="card empty">Il faut au moins une classe et une période. <a href="#/classes">Classes</a> · <a href="#/years">Périodes</a></div>`; return;
  }
  const subs = await get(`/class-subjects?class_id=${f.class_id}`);
  if (f.cs_id && !subs.some((s) => s.id === f.cs_id)) f.cs_id = null;
  store.set("jiji.grades.filter", JSON.stringify(f));
  const evals = await get(`/evaluations?class_id=${f.class_id}&period_id=${f.period_id}${f.cs_id ? `&class_subject_id=${f.cs_id}` : ""}`);
  const sel = (id, label, opts, cur, blank) => `<div class="field"><label>${label}</label><select id="${id}">${blank ? `<option value="">${blank}</option>` : ""}${opts.map((o) => `<option value="${o.value}" ${String(o.value) === String(cur) ? "selected" : ""}>${esc(o.label)}</option>`).join("")}</select></div>`;
  view.innerHTML = pageHead("Saisie des notes", "Créez des évaluations puis saisissez les notes de chaque élève.", '<button class="primary" id="add">Nouvelle évaluation</button>') +
    `<div class="toolbar">${sel("g-class", "Classe", classOptions(classes), f.class_id)}${sel("g-period", "Période", periods.map((p) => ({ value: p.id, label: p.name })), f.period_id)}${sel("g-sub", "Matière", subs.map((s) => ({ value: s.id, label: s.subject_name })), f.cs_id, "Toutes les matières")}</div>
    ${evals.length ? `<div class="table-wrap"><table><thead><tr><th>Matière</th><th>Évaluation</th><th>Type</th><th>Date</th><th class="num">Barème</th><th class="num">Poids</th><th>Saisie</th><th></th></tr></thead><tbody>
    ${evals.map((e) => `<tr><td>${esc(e.subject_name)}</td><td><a href="#/grades/${e.id}"><b>${esc(e.title)}</b></a></td><td>${esc(e.kind)}</td><td>${frDate(e.date)}</td><td class="num">/${fmt(e.max_score, 0)}</td><td class="num">${fmt(e.weight, 1)}</td>
    <td><span class="badge ${e.student_count && e.graded_count === e.student_count ? "good" : "warn"}">${e.graded_count}/${e.student_count}</span></td>
    <td><div class="actions"><a class="btn small primary" href="#/grades/${e.id}">Saisir les notes</a><button class="small" data-edit="${e.id}">Modifier</button><button class="small danger" data-del="${e.id}">Supprimer</button></div></td></tr>`).join("")}</tbody></table></div>` : '<div class="card empty">Aucune évaluation pour cette sélection.</div>'}`;
  ["class", "period", "sub"].forEach((k) => $(`#g-${k}`).onchange = (e) => {
    const v = e.target.value ? Number(e.target.value) : null; if (k === "class") { f.class_id = v; f.cs_id = null; } else if (k === "period") f.period_id = v; else f.cs_id = v;
    store.set("jiji.grades.filter", JSON.stringify(f)); route();
  });
  const fields = (extra = []) => [...extra, { name: "title", label: "Intitulé", required: true, placeholder: "Devoir n°1" },
    { name: "kind", label: "Type", type: "select", options: ["Devoir", "Interrogation", "Composition", "Examen", "TP", "Oral"].map((x) => ({ value: x, label: x })) },
    { name: "date", label: "Date", type: "date" }, { name: "max_score", label: "Barème (note maximale)", type: "number", default: 20, required: true },
    { name: "weight", label: "Poids dans la moyenne de la matière", type: "number", default: 1, required: true, help: "Ex. : 2 pour une composition comptant double." }];
  $("#add").onclick = () => subs.length
    ? formModal("Nouvelle évaluation", fields([{ name: "class_subject_id", label: "Matière", type: "select", required: true, options: subs.map((s) => ({ value: s.id, label: s.subject_name })), default: f.cs_id || subs[0].id }]), { date: new Date().toISOString().slice(0, 10) },
      async (d) => { const e = await post("/evaluations", { ...d, period_id: f.period_id }); location.hash = `#/grades/${e.id}`; })
    : toast("Affectez d'abord des matières à cette classe.", true);
  $$("[data-edit]", view).forEach((b) => b.onclick = () => { const e = evals.find((x) => x.id === +b.dataset.edit); formModal("Modifier l'évaluation", fields(), e, async (d) => { await put(`/evaluations/${e.id}`, d); route(); }); });
  $$("[data-del]", view).forEach((b) => b.onclick = async () => { if (await confirmBox("Supprimer cette évaluation et ses notes ?")) guard(async () => { await del(`/evaluations/${b.dataset.del}`); route(); })(); });
}

async function viewGradeSheet(view, id) {
  const { evaluation: ev, students } = await get(`/evaluations/${id}/grades`);
  const inputs = students.map((s) => `<tr data-id="${s.student_id}"><td class="muted">${esc(s.matricule)}</td><td><b>${esc(s.last_name.toUpperCase())}</b> ${esc(s.first_name)}</td>
    <td class="num"><input class="score-input" inputmode="decimal" autocomplete="off" value="${s.score === null ? "" : String(s.score).replace(".", ",")}" ${s.absent ? "disabled" : ""} aria-label="Note de ${esc(s.first_name)} ${esc(s.last_name)}"> <span class="muted">/${fmt(ev.max_score, 0)}</span></td>
    <td class="center"><input type="checkbox" class="abs" style="width:auto" ${s.absent ? "checked" : ""} aria-label="Absent"></td></tr>`).join("");
  view.innerHTML = `<div class="crumbs"><a href="#/grades">Saisie des notes</a> › ${esc(ev.class_name)} › ${esc(ev.subject_name)}</div>` +
    pageHead(`${ev.title}`, `${esc(ev.class_name)} · ${esc(ev.subject_name)} · ${esc(ev.period_name)} · barème /${fmt(ev.max_score, 0)} · poids ${fmt(ev.weight, 1)}`, '<button id="save" class="primary">Enregistrer (Ctrl+S)</button>') +
    `<div class="grid cols4" style="margin-bottom:14px"><div class="stat"><b id="s-avg">–</b><span>Moyenne (sur 20)</span></div><div class="stat"><b id="s-min">–</b><span>Plus basse</span></div><div class="stat"><b id="s-max">–</b><span>Plus haute</span></div><div class="stat"><b id="s-n">–</b><span>Notes saisies</span></div></div>
    ${students.length ? `<div class="table-wrap"><table><thead><tr><th>Matricule</th><th>Élève</th><th class="num">Note</th><th class="center">Absent</th></tr></thead><tbody>${inputs}</tbody></table></div><p class="muted">Astuce : Entrée passe à l'élève suivant. Une case vide = pas de note ; « Absent » n'est pas compté comme zéro.</p>` : '<div class="card empty">Aucun élève dans cette classe.</div>'}`;
  let dirty = false;
  const rows = $$("tbody tr", view);
  const readRow = (tr) => { const abs = $(".abs", tr).checked; const raw = $(".score-input", tr).value.trim(); const v = abs || raw === "" ? null : num(raw); const bad = v !== null && (!Number.isFinite(v) || v < 0 || v > ev.max_score); return { abs, v, bad }; };
  const stats = () => {
    const vals = []; rows.forEach((tr) => { const r = readRow(tr); $(".score-input", tr).classList.toggle("invalid", r.bad); if (r.v !== null && !r.bad) vals.push(r.v / ev.max_score * 20); });
    $("#s-avg").textContent = vals.length ? fmt(vals.reduce((a, b) => a + b, 0) / vals.length) : "–"; $("#s-min").textContent = vals.length ? fmt(Math.min(...vals)) : "–";
    $("#s-max").textContent = vals.length ? fmt(Math.max(...vals)) : "–"; $("#s-n").textContent = `${vals.length}/${students.length}`;
  };
  stats();
  view.addEventListener("input", (e) => { dirty = true; if (e.target.classList.contains("abs")) { const inp = $(".score-input", e.target.closest("tr")); inp.disabled = e.target.checked; if (e.target.checked) inp.value = ""; } stats(); });
  view.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.classList.contains("score-input")) { e.preventDefault(); const list = $$(".score-input:not(:disabled)", view); (list[list.indexOf(e.target) + 1] || e.target).focus(); (list[list.indexOf(e.target) + 1] || e.target).select(); } });
  const save = guard(async () => {
    const grades = []; for (const tr of rows) { const r = readRow(tr); if (r.bad) { $(".score-input", tr).focus(); throw new Error(`Une note doit être comprise entre 0 et ${fmt(ev.max_score, 0)}.`); } grades.push({ student_id: +tr.dataset.id, score: r.v, absent: r.abs }); }
    await put(`/evaluations/${id}/grades`, { grades }); dirty = false; toast("Notes enregistrées");
  });
  $("#save").onclick = save;
  const onKey = (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); } };
  document.addEventListener("keydown", onKey);
  const leave = () => { document.removeEventListener("keydown", onKey); window.removeEventListener("hashchange", leave); window.onbeforeunload = null; };
  window.addEventListener("hashchange", leave); window.onbeforeunload = () => (dirty ? "Notes non enregistrées" : undefined);
  const first = $(".score-input:not(:disabled)", view); first?.focus();
}

/* ---------- Résultats & bulletins ---------- */
async function viewResults(view) {
  if (needYear(view)) return;
  const [classes, periods] = await Promise.all([get(`/classes?year_id=${state.year.id}`), get(`/periods?year_id=${state.year.id}`)]);
  if (!classes.length) { view.innerHTML = pageHead("Résultats") + '<div class="card empty">Aucune classe. <a href="#/classes">Créer une classe</a></div>'; return; }
  let classId = Number(store.get("jiji.results.class"));
  if (!classes.some((c) => c.id === classId)) classId = classes[0].id;
  let period = store.get("jiji.results.period") || "annual";
  if (period !== "annual" && !periods.some((p) => String(p.id) === period)) period = periods[0] ? String(periods[0].id) : "annual";
  const rep = await get(`/classes/${classId}/report?period=${period}`);
  const annual = rep.period.annual, pass = rep.settings.pass_mark, st = rep.stats;
  const cell = (v) => v === null || v === undefined ? '<span class="muted">–</span>' : `<span class="${v < pass ? "bad-text" : ""}">${fmt(v)}</span>`;
  view.innerHTML = pageHead("Résultats & bulletins", `${esc(rep.class.name)} · ${esc(rep.period.name)}`,
    `<button id="print">Imprimer le tableau</button><a class="btn" href="/api/classes/${classId}/report.csv?period=${period}" download>Exporter (Excel/CSV)</a><button class="primary" id="all-bull" ${st.count ? "" : "disabled"}>Tous les bulletins</button>`) +
    `<div class="toolbar noprint"><div class="field"><label>Classe</label><select id="r-class">${classOptions(classes).map((o) => `<option value="${o.value}" ${o.value === classId ? "selected" : ""}>${esc(o.label)}</option>`).join("")}</select></div>
    <div class="field"><label>Période</label><select id="r-period">${periods.map((p) => `<option value="${p.id}" ${String(p.id) === period ? "selected" : ""}>${esc(p.name)}</option>`).join("")}<option value="annual" ${annual ? "selected" : ""}>Moyenne annuelle</option></select></div></div>
    <div class="grid cols4" style="margin-bottom:14px"><div class="stat"><b>${fmt(st.avg)}</b><span>Moyenne de la classe</span></div><div class="stat"><b>${fmt(st.max)}</b><span>Plus forte moyenne</span></div><div class="stat"><b>${fmt(st.min)}</b><span>Plus faible moyenne</span></div><div class="stat"><b>${st.pass_rate === null ? "–" : fmt(st.pass_rate, 1) + " %"}</b><span>Taux de réussite (${st.passed}/${st.count})</span></div></div>
    ${rep.students.length ? `<div class="table-wrap"><table><thead><tr><th class="num">Rang</th><th>Élève</th>${rep.subjects.map((s) => `<th class="num" title="${esc(s.name)}">${esc(s.code || s.name)}<br><span class="muted">coef ${fmt(s.coef, 1)}</span></th>`).join("")}${annual ? rep.periods.map((p) => `<th class="num">${esc(p.name)}</th>`).join("") : ""}<th class="num">Moyenne</th><th>Mention</th><th class="noprint"></th></tr></thead><tbody>
    ${[...rep.students].sort((a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9) || a.name.localeCompare(b.name)).map((s) => `<tr><td class="num">${s.rank ? s.rank + (s.rank === 1 ? "er" : "e") : "–"}</td><td><b>${esc(s.name)}</b><div class="muted">${esc(s.matricule)}</div></td>
    ${rep.subjects.map((sub) => `<td class="num">${cell(s.subjects[sub.id])}</td>`).join("")}${annual ? rep.periods.map((p) => `<td class="num">${cell(s.period_averages[p.id])}</td>`).join("") : ""}
    <td class="num"><b>${cell(s.average)}</b></td><td>${s.mention ? `<span class="badge ${s.passed ? "good" : "bad"}">${esc(s.mention)}</span>` : ""}</td><td class="noprint"><button class="small" data-bull="${s.id}" ${s.average === null ? "disabled" : ""}>Bulletin</button></td></tr>`).join("")}</tbody>
    <tfoot><tr><td></td><td><b>Moyenne de classe</b></td>${rep.subjects.map((s) => `<td class="num"><b>${fmt(s.stats.avg)}</b></td>`).join("")}${annual ? rep.periods.map(() => "<td></td>").join("") : ""}<td class="num"><b>${fmt(st.avg)}</b></td><td colspan="2"></td></tr></tfoot></table></div>` : '<div class="card empty">Cette classe ne contient aucun élève.</div>'}`;
  $("#r-class").onchange = (e) => { store.set("jiji.results.class", e.target.value); route(); };
  $("#r-period").onchange = (e) => { store.set("jiji.results.period", e.target.value); route(); };
  $("#print").onclick = () => window.print();
  $$("[data-bull]", view).forEach((b) => b.onclick = () => showBulletins(rep, [rep.students.find((s) => s.id === +b.dataset.bull)]));
  $("#all-bull").onclick = () => showBulletins(rep, [...rep.students].filter((s) => s.average !== null).sort((a, b) => a.rank - b.rank));
}

function appreciation(v, mentions) {
  if (v === null || v === undefined) return "";
  const m = [...mentions].sort((a, b) => b.min - a.min).find((x) => v >= x.min);
  return m ? m.label : "";
}

function bulletinHtml(rep, s) {
  const n = rep.students.filter((x) => x.average !== null).length, annual = rep.period.annual, pass = rep.settings.pass_mark;
  const rows = rep.subjects.map((sub) => { const v = s.subjects[sub.id]; return `<tr><td>${esc(sub.name)}<div style="color:#555;font-size:10px">${esc(sub.teacher)}</div></td><td class="num">${fmt(sub.coef, 1)}</td><td class="num"><b>${fmt(v)}</b></td><td class="num">${fmt(v === null ? null : v * sub.coef)}</td><td class="num">${fmt(sub.stats.avg)}</td><td class="num">${fmt(sub.stats.min)}</td><td class="num">${fmt(sub.stats.max)}</td><td>${esc(appreciation(v, rep.settings.mentions))}</td></tr>`; }).join("");
  const totalCoef = rep.subjects.filter((x) => s.subjects[x.id] !== null).reduce((a, x) => a + x.coef, 0);
  const totalPts = rep.subjects.reduce((a, x) => a + (s.subjects[x.id] === null ? 0 : s.subjects[x.id] * x.coef), 0);
  return `<section class="sheet"><div class="head"><div><b>${esc(rep.settings.school_name)}</b><div>Année scolaire ${esc(rep.class.year)}</div></div><div style="text-align:right"><b>Classe : ${esc(rep.class.name)}</b><div>${esc(rep.class.track || "")}</div></div></div>
    <h1>BULLETIN DE NOTES</h1><div class="sub">${annual ? "Récapitulatif annuel" : esc(rep.period.name)}</div>
    <div class="ident"><div><b>Nom :</b> ${esc(s.last_name.toUpperCase())}</div><div><b>Prénom(s) :</b> ${esc(s.first_name)}</div><div><b>Matricule :</b> ${esc(s.matricule)}</div><div><b>Né(e) le :</b> ${frDate(s.birth_date) || "—"}</div><div><b>Sexe :</b> ${esc(s.sex) || "—"}</div><div><b>Effectif de la classe :</b> ${rep.students.length}</div></div>
    <table><thead><tr><th>Matière</th><th class="num">Coef.</th><th class="num">Moyenne /${rep.settings.scale}</th><th class="num">Points</th><th class="num">Moy. classe</th><th class="num">Min</th><th class="num">Max</th><th>Appréciation</th></tr></thead><tbody>${rows}</tbody>
    <tfoot><tr><td>TOTAL</td><td class="num">${fmt(totalCoef, 1)}</td><td></td><td class="num">${fmt(totalPts)}</td><td colspan="4"></td></tr></tfoot></table>
    ${annual ? `<table style="margin-top:10px"><thead><tr><th>Période</th><th class="num">Moyenne</th></tr></thead><tbody>${rep.periods.map((p) => `<tr><td>${esc(p.name)} <span style="color:#555">(poids ${fmt(p.weight, 1)})</span></td><td class="num">${fmt(s.period_averages[p.id])}</td></tr>`).join("")}</tbody></table>` : ""}
    <div class="summary"><div><b style="${s.average < pass ? "color:#b00" : ""}">${fmt(s.average)}</b>Moyenne ${annual ? "annuelle" : "générale"}</div><div><b>${s.rank}${s.rank === 1 ? "er" : "e"} / ${n}</b>Rang</div><div><b>${esc(s.mention) || "–"}</b>Mention</div><div><b>${fmt(rep.stats.avg)}</b>Moyenne de la classe<br><small>min ${fmt(rep.stats.min)} · max ${fmt(rep.stats.max)}</small></div></div>
    <div><b>Décision :</b> ${s.passed ? "Admis(e) — résultats satisfaisants" : "Résultats insuffisants — des efforts sont attendus"} <small>(moyenne de passage : ${fmt(pass, 1)})</small></div>
    <div class="sign"><div>Le Chef d'établissement</div><div>Les Parents / Tuteur</div></div></section>`;
}

function showBulletins(rep, list) {
  const ov = document.createElement("div");
  ov.className = "overlay";
  ov.innerHTML = `<div class="bar-top"><button class="primary" id="b-print">Imprimer / PDF</button><button id="b-close">Fermer</button><span class="muted">${list.length} bulletin(s) — « Enregistrer au format PDF » dans la fenêtre d'impression</span></div>${list.map((s) => bulletinHtml(rep, s)).join("")}`;
  document.body.append(ov); document.body.classList.add("has-overlay");
  const close = () => { ov.remove(); document.body.classList.remove("has-overlay"); document.removeEventListener("keydown", esc2); };
  const esc2 = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", esc2);
  $("#b-close", ov).onclick = close; $("#b-print", ov).onclick = () => window.print();
}

/* ---------- Paramètres ---------- */
async function viewSettings(view) {
  const s = await get("/settings");
  view.innerHTML = pageHead("Paramètres", "Établissement, barème, mentions et sécurité.") +
    `<div class="grid cols2"><form class="card" id="f-set"><h2>Établissement & calcul</h2>
    <div class="field"><label>Nom de l'établissement</label><input name="school_name" value="${esc(s.school_name)}" required></div>
    <div class="row2" style="display:grid;grid-template-columns:1fr 1fr;gap:12px"><div class="field"><label>Barème (note maximale)</label><input name="scale" value="${s.scale}" inputmode="decimal"></div><div class="field"><label>Moyenne de passage</label><input name="pass_mark" value="${s.pass_mark}" inputmode="decimal"></div></div>
    <h3>Mentions</h3><div id="mentions"></div><p><button type="button" class="small" id="add-m">+ Ajouter une mention</button></p><div class="error-text" id="set-err"></div><button class="primary">Enregistrer</button></form>
    <div><form class="card" id="f-pw"><h2>Mot de passe</h2><div class="field"><label>Mot de passe actuel</label><input type="password" name="old" required autocomplete="current-password"></div><div class="field"><label>Nouveau mot de passe</label><input type="password" name="new" required minlength="6" autocomplete="new-password"></div><button>Changer le mot de passe</button></form>
    <div class="card"><h2>Sauvegarde</h2><p class="muted">Téléchargez une copie complète de la base de données (élèves, notes, configuration). Conservez-la en lieu sûr.</p><a class="btn primary" href="/api/backup" download>Télécharger une sauvegarde</a></div></div></div>`;
  const ms = s.mentions.map((m) => ({ ...m }));
  const drawM = () => {
    $("#mentions").innerHTML = ms.map((m, i) => `<div class="toolbar" style="margin-bottom:6px"><div class="field narrow"><input data-i="${i}" data-k="min" value="${m.min}" inputmode="decimal" aria-label="À partir de"></div><div class="field grow"><input data-i="${i}" data-k="label" value="${esc(m.label)}" aria-label="Libellé"></div><button type="button" class="small danger" data-rm="${i}">✕</button></div>`).join("");
    $$("[data-rm]").forEach((b) => b.onclick = () => { ms.splice(+b.dataset.rm, 1); drawM(); });
    $$("#mentions input").forEach((inp) => inp.oninput = () => { ms[+inp.dataset.i][inp.dataset.k] = inp.value; });
  };
  drawM();
  $("#add-m").onclick = () => { ms.push({ min: 0, label: "" }); drawM(); };
  $("#f-set").onsubmit = async (e) => {
    e.preventDefault(); const f = e.target;
    try { state.settings = await put("/settings", { school_name: f.school_name.value, scale: num(f.scale.value), pass_mark: num(f.pass_mark.value), mentions: ms.map((m) => ({ min: num(m.min), label: m.label })) }); state.school = state.settings.school_name; $("#set-err").textContent = ""; toast("Paramètres enregistrés"); $(".brand small").textContent = state.school; }
    catch (err) { $("#set-err").textContent = err.message; }
  };
  $("#f-pw").onsubmit = guard(async (e) => { e.preventDefault(); const f = e.target; await post("/password", { old: f.old.value, new: f.new.value }); f.reset(); toast("Mot de passe modifié"); });
}

boot().catch((e) => { $("#app").innerHTML = `<div class="auth"><div class="card"><p class="bad-text">${esc(e.message)}</p></div></div>`; });
