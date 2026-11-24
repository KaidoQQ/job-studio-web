function statusLabel(s) {
  return (
    {
      new: "Новое",
      draft: "Черновик",
      reviewed: "Проверено",
      applied: "Отправлено",
      archived: "В архиве",
    }[s] || s
  );
}

const TOKEN = document.querySelector('meta[name="studio-token"]').content;
let state = { jobs: [] },
  selected = null,
  loaded = false,
  dirty = false;
const $ = (id) => document.getElementById(id);
const escape = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
function toast(s) {
  $("toast").textContent = s;
  $("toast").classList.remove("hidden");
  setTimeout(() => $("toast").classList.add("hidden"), 4500);
}
async function api(path, data) {
  const r = await fetch("/api/" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Studio-Token": TOKEN },
    body: JSON.stringify(data),
  });
  const v = await r.json();
  if (!r.ok) throw Error(v.error);
  return v;
}
async function action(fn) {
  try {
    await fn();
  } catch (e) {
    toast(e.message);
  }
}
function showPage(page) {
  document
    .querySelectorAll(".section")
    .forEach((e) => e.classList.toggle("hidden", e.id !== page));
  document
    .querySelectorAll(".nav")
    .forEach((e) => e.classList.toggle("active", e.dataset.page === page));
}
document
  .querySelectorAll(".nav")
  .forEach((b) => (b.onclick = () => showPage(b.dataset.page)));
function publishedLabel(j) {
  if (!j.published_at) return "Дата публикации неизвестна";
  const age = Date.now() - Date.parse(j.published_at);
  return (
    (age >= 0 && age < 86400000 ? "Новое · " : "Опубликовано · ") +
    new Date(j.published_at).toLocaleDateString("ru-RU")
  );
}
function render() {
  const q = $("search").value.toLowerCase(),
    f = $("filter").value;
  const days = Number($("freshness").value);
  const jobs = state.jobs.filter(
    (j) =>
      (!days ||
        (j.published_at &&
          Date.parse(j.published_at) <= Date.now() &&
          Date.now() - Date.parse(j.published_at) < days * 86400000)) &&
      (!f || j.status === f) &&
      [j.title, j.company, j.source].join(" ").toLowerCase().includes(q),
  );
  $("total").textContent = state.jobs.length;
  $("drafts").textContent = state.jobs.filter(
    (j) => j.draft && j.status === "draft",
  ).length;
  $("reviewed").textContent = state.jobs.filter(
    (j) => j.status === "reviewed",
  ).length;
  $("list").innerHTML = jobs.length
    ? jobs
        .map(
          (j) =>
            `<button class="job ${j.id === selected ? "selected" : ""}" data-id="${j.id}"><span class="job-head"><span class="badge">${escape(statusLabel(j.status))}</span><svg class="icon" aria-hidden="true"><use href="#i-arrow"></use></svg></span><span class="job-title">${escape(j.title)}</span><span class="muted">${escape(j.company || j.source)}</span><small class="muted">${escape(publishedLabel(j))}</small></button>`,
        )
        .join("")
    : '<div class="panel empty"><div class="empty-visual"><svg class="icon" aria-hidden="true"><use href="#i-briefcase"></use></svg></div><b>Пока пусто</b>Добавь профиль в настройках и запусти первый сбор.</div>';
  $("list")
    .querySelectorAll("button")
    .forEach(
      (b) =>
        (b.onclick = () => {
          if (dirty && !confirm("Не сохранять изменения письма?")) return;
          selected = b.dataset.id;
          dirty = false;
          render();
          renderDetail();
        }),
    );
}
function renderDetail() {
  const j = state.jobs.find((j) => j.id === selected);
  if (!j) return;
  $("detail").innerHTML =
    `<span class="eyebrow">${escape(j.source)}</span><h2 style="margin-top:12px">${escape(j.title)}</h2><p class="muted">${escape(publishedLabel(j))} · Найдено ${new Date(j.created).toLocaleDateString("ru-RU")}</p><a href="${escape(j.url)}" target="_blank" rel="noopener noreferrer">Открыть вакансию ↗</a><p class="muted">${escape(j.company)} · ${escape(j.location).slice(0, 220)}</p>${j.error ? "<p>" + escape(j.error) + "</p>" : ""}<textarea id="letter" aria-label="Черновик письма" placeholder="После генерации здесь появится черновик">${escape(j.draft)}</textarea><div class="actions"><button class="primary" id="applyjob"><svg class="icon" aria-hidden="true"><use href="#i-send"></use></svg>Откликнуться</button><button id="saveletter"><svg class="icon" aria-hidden="true"><use href="#i-save"></use></svg>Сохранить</button><button id="copyletter"><svg class="icon" aria-hidden="true"><use href="#i-copy"></use></svg>Копировать</button><select id="jobstatus" aria-label="Статус вакансии">${["new", "draft", "reviewed", "applied", "archived"].map((s) => `<option value="${s}" ${s === j.status ? "selected" : ""}>${statusLabel(s)}</option>`).join("")}</select></div><div id="attempt-info" style="margin-top:15px"></div><details style="margin-top:20px"><summary>Описание вакансии</summary><pre>${escape(j.description)}</pre></details>`;
  renderAttempt(j);
  $("letter").oninput = () => (dirty = true);
  $("jobstatus").onchange = () => (dirty = true);
  $("applyjob").disabled =
    !!state.application?.running || j.status === "applied";
  $("applyjob").onclick = () =>
    action(async () => {
      await api("job", {
        id: j.id,
        draft: $("letter").value,
        status: $("jobstatus").value,
      });
      dirty = false;
      await api("apply", { id: j.id });
      toast("Бот открывает форму отклика");
      await refresh();
    });
  $("saveletter").onclick = () =>
    action(async () => {
      await api("job", {
        id: j.id,
        draft: $("letter").value,
        status: $("jobstatus").value,
      });
      dirty = false;
      toast("Сохранено");
      await refresh();
    });
  $("copyletter").onclick = () =>
    action(async () => {
      await navigator.clipboard.writeText($("letter").value);
      toast("Скопировано");
    });
}
async function refresh() {
  const r = await fetch("/api/state");
  if (!r.ok) throw Error("Не удалось загрузить данные");
  state = await r.json();
  $("message").textContent = state.application?.running
    ? state.application.message
    : state.run.message;
  $("progress").classList.toggle("busy", state.run.running);
  $("run").disabled = state.run.running;
  $("stop").disabled = !state.run.running;
  $("events").textContent =
    [
      ...state.run.events,
      ...(state.application_events || []).map(
        (e) =>
          new Date(e.created * 1000).toLocaleTimeString() +
          " [" +
          e.state +
          "] " +
          e.message,
      ),
    ].join("\n") || "Пока нет событий";
  if (!loaded) {
    for (const key of ["profile", "provider", "limit", "keywords", "exclude"])
      $(key).value = state.settings[key];
    $("fallback").checked = state.settings.fallback;
    $("sources").value = state.settings.sources
      .filter((s) => s.enabled)
      .map((s) => s.name + " | " + s.url)
      .join("\n");
    loaded = true;
    loadApplicant();
  }
  renderApplication();
  renderParsePlus();
  render();
  if (!dirty) renderDetail();
}
$("search").oninput = render;
$("filter").onchange = render;
$("freshness").onchange = render;
$("savesettings").onclick = () =>
  action(async () => {
    const cfg = {};
    for (const k of ["profile", "provider", "limit", "keywords", "exclude"])
      cfg[k] = $(k).value;
    cfg.fallback = $("fallback").checked;
    cfg.sources = $("sources")
      .value.split("\n")
      .filter((s) => s.trim())
      .map((s) => {
        const i = s.indexOf("|");
        if (i < 0)
          throw Error("Источник должен быть в формате: название | URL");
        return {
          name: s.slice(0, i).trim(),
          url: s.slice(i + 1).trim(),
          enabled: true,
        };
      });
    await api("settings", cfg);
    toast("Настройки сохранены");
  });
$("savekey").onclick = () =>
  action(async () => {
    await api("key", { key: $("key").value });
    $("key").value = "";
    toast("Ключ сохранён в системном хранилище");
  });
for (const [id, drafts] of [
  ["run", true],
  ["collect", false],
])
  $(id).onclick = () =>
    action(async () => {
      await api("run", { drafts });
      showPage("inbox");
      await refresh();
    });
$("stop").onclick = () => action(() => api("stop", {}));
$("import").onclick = () => {
  const url = prompt("Ссылка на вакансию");
  if (url)
    action(async () => {
      toast("Загружаю вакансию…");
      await api("import", { url });
      await refresh();
    });
};
refresh().catch((e) => toast(e.message));
setInterval(
  () =>
    refresh().catch(() => {
      $("message").textContent = "Нет соединения с приложением";
    }),
  3000,
);

const applicantLabels = {
  first_name: "Имя",
  last_name: "Фамилия",
  email: "Email",
  phone: "Телефон с кодом страны",
  city: "Город",
  country: "Страна",
  github: "GitHub",
  linkedin: "LinkedIn (если есть)",
  notice: "Срок выхода",
  cv_path: "Полный путь к CV (PDF)",
  salary_expectation: "Ожидания по зарплате (с валютой и типом договора)",
  hybrid_availability: "Доступность для гибридной работы",
};
function loadApplicant() {
  $("applicant-fields").innerHTML = Object.entries(applicantLabels)
    .map(
      ([k, label]) =>
        `<div><label for="person-${k}">${label}</label><input id="person-${k}" value="${escape(state.applicant?.[k] || "")}"></div>`,
    )
    .join("");
  $("applicant-answers").value = JSON.stringify(
    state.applicant?.answers || {},
    null,
    2,
  );
}
$("saveapplicant").onclick = () =>
  action(async () => {
    const p = {};
    for (const k of Object.keys(applicantLabels)) p[k] = $("person-" + k).value;
    p.answers = JSON.parse($("applicant-answers").value || "{}");
    await api("applicant", p);
    toast("Данные сохранены");
  });
function renderApplication() {
  const a = state.application || {};
  $("application-panel").classList.toggle("hidden", !a.job_id);
  $("application-message").textContent = a.message || "";
  $("application-url").href = a.url || "#";
  $("application-resume").disabled = !a.waiting;
  $("application-cancel").disabled = !a.running;
  $("application-finish").disabled = !a.job_id || (a.running && !a.waiting);
  renderQuestions(a);
}
$("application-resume").onclick = () => action(() => api("apply/resume", {}));
$("application-cancel").onclick = () => action(() => api("apply/cancel", {}));

function renderAttempt(j) {
  const attempt = (state.applications || []).find((a) => a.job_id === j.id);
  if (!attempt) return;
  const box = $("attempt-info");
  box.innerHTML = `<p class="muted">${escape(attempt.state)} · ${escape(attempt.message)}</p>`;
  if (
    !state.application?.running &&
    !["submitted", "failed", "cancelled"].includes(attempt.state)
  ) {
    box.innerHTML +=
      '<button id="resolve-sent">Проверил — отправлено</button> <button id="resolve-not-sent">Проверил — не отправлено</button>';
    for (const [id, result] of [
      ["resolve-sent", "submitted"],
      ["resolve-not-sent", "not_sent"],
    ])
      $(id).onclick = () =>
        action(async () => {
          await api("apply/resolve", { id: j.id, result });
          await refresh();
        });
  }
}

let questionSignature = "";
function renderQuestions(a) {
  const questions = a.waiting ? a.questions || [] : [];
  const signature = JSON.stringify(questions);
  if (signature === questionSignature) return;
  questionSignature = signature;
  const box = $("application-questions");
  if (!questions.length) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML =
    '<h2>Ответы для этой анкеты</h2><p class="muted">AI предлагает ответ только с опорой на профиль. Проверь предложения или введи свой ответ. Согласия подтверждаешь ты.</p>' +
    questions
      .map((q) => {
        const disabled = ["file", "manual", "combobox"].includes(q.kind);
        let control = disabled
          ? '<p class="muted">Этот элемент нужно заполнить в открытом браузере.</p>'
          : q.kind === "checkbox" || q.kind === "radio"
            ? `<label class="check"><input type="checkbox" data-question="${q.id}">Подтверждаю этот пункт для данной анкеты</label>`
            : q.options.length
              ? `<select data-question="${q.id}"><option value="">Выбери ответ</option>${q.options.map((o) => `<option value="${escape(o)}" ${o === q.suggestion ? "selected" : ""}>${escape(o)}</option>`).join("")}</select>`
              : `<textarea rows="2" data-question="${q.id}" placeholder="Данных в профиле недостаточно — введи ответ">${escape(q.suggestion)}</textarea>`;
        return `<div style="margin:16px 0"><label>${escape(q.label)}</label>${control}${q.evidence ? `<small class="muted">Основание: ${escape(q.evidence)}</small>` : ""}</div>`;
      })
      .join("") +
    '<label class="check"><input id="remember-answers" type="checkbox" checked>Запомнить мои ответы для следующих анкет (кроме согласий)</label><button class="primary" id="send-answers">Принять ответы и продолжить</button>';
  $("send-answers").onclick = () =>
    action(async () => {
      const answers = {};
      box
        .querySelectorAll("[data-question]")
        .forEach(
          (e) =>
            (answers[e.dataset.question] =
              e.type === "checkbox" ? e.checked : e.value),
        );
      await api("apply/answers", {
        id: a.job_id,
        answers,
        remember: $("remember-answers").checked,
      });
      await refresh();
    });
}

$("application-finish").onclick = () =>
  action(async () => {
    await api("apply/finish", { id: state.application.job_id });
    toast("Завершаю отклик: отправлено вручную");
    await refresh();
  });
function renderParsePlus() {
  const p = state.parse_plus || {};
  $("parseplus-message").textContent =
    p.message || "Вставь ссылку, чтобы начать";
  $("parseplus-events").textContent = (p.events || []).join("\n");
  $("parseplus-read").disabled = !!p.running;
  $("parseplus-apply").disabled = !!p.running || !!state.application?.running;
  $("parseplus-open").classList.toggle("hidden", !p.job_id);
}
for (const [id, apply] of [
  ["parseplus-read", false],
  ["parseplus-apply", true],
])
  $(id).onclick = () =>
    action(async () => {
      const url = $("parseplus-url").value.trim();
      if (!url) throw Error("Вставь ссылку на вакансию");
      await api("parse-plus", {
        url,
        title: $("parseplus-title").value,
        apply,
      });
      await refresh();
    });
$("parseplus-open").onclick = () => {
  if (dirty && !confirm("Не сохранять изменения текущего письма?")) return;
  selected = state.parse_plus.job_id;
  dirty = false;
  $("search").value = "";
  $("filter").value = "";
  showPage("inbox");
  render();
  renderDetail();
};
