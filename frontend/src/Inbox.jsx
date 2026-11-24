import React from "react";
import { Button, Icon, published, statuses } from "./ui";
import { post } from "./studio";
export default function Inbox({
  state,
  selected,
  choose,
  edit,
  setEdit,
  filters,
  setFilters,
  act,
  busy,
}) {
  const jobs = state.jobs;
  const visible = jobs.filter((j) => {
    const age = Date.now() - Date.parse(j.published_at);
    return (
      (!filters.days || (age >= 0 && age < Number(filters.days) * 86400000)) &&
      (!filters.status || j.status === filters.status) &&
      [j.title, j.company, j.source]
        .join(" ")
        .toLowerCase()
        .includes(filters.query.toLowerCase())
    );
  });
  const selectFilter = (name) => ({
    value: filters[name],
    onChange: (e) => setFilters({ ...filters, [name]: e.target.value }),
  });
  const job = jobs.find((j) => j.id === selected);
  function importJob() {
    const url = window.prompt("Ссылка на вакансию");
    if (url?.trim()) act(() => post("import", { url: url.trim() }));
  }
  return (
    <section id="inbox" className="section">
      <div className="stats">
        {[
          ["briefcase", "Все вакансии", jobs.length],
          [
            "file",
            "Черновики",
            jobs.filter((j) => j.status === "draft" && j.draft).length,
          ],
          [
            "check",
            "Проверено",
            jobs.filter((j) => j.status === "reviewed").length,
          ],
        ].map(([icon, label, value]) => (
          <div className="stat" key={label}>
            <Icon name={icon} />
            <span className="muted">{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      <div className="toolbar">
        <input
          aria-label="Поиск"
          placeholder="Компания, должность, источник…"
          {...selectFilter("query")}
        />
        <select aria-label="Статус" {...selectFilter("status")}>
          <option value="">Все статусы</option>
          {Object.entries(statuses).map(([s, label]) => (
            <option key={s} value={s}>
              {label}
            </option>
          ))}
        </select>
        <select aria-label="Свежесть" {...selectFilter("days")}>
          <option value="">Сначала свежие</option>
          <option value="1">За 24 часа</option>
          <option value="7">За 7 дней</option>
        </select>
        <Button icon="plus" onClick={importJob} disabled={busy}>
          Добавить ссылку
        </Button>
      </div>
      <div className="workspace">
        <div className="list">
          {visible.map((j) => (
            <button
              key={j.id}
              className={"job " + (j.id === selected ? "selected" : "")}
              onClick={() => choose(j.id)}
            >
              <span className="job-head">
                <span className="badge">{statuses[j.status] || j.status}</span>
                <Icon name="arrow" />
              </span>
              <span className="job-title">{j.title}</span>
              <span className="muted">{j.company || j.source}</span>
              <small className="muted">{published(j)}</small>
            </button>
          ))}
          {!visible.length && (
            <div className="panel empty">
              {jobs.length
                ? "Нет вакансий по этим фильтрам"
                : "Запусти сбор или добавь ссылку на вакансию."}
            </div>
          )}
        </div>
        <div className="panel detail">
          {job ? (
            <Detail job={job} {...{ state, edit, setEdit, act, busy }} />
          ) : (
            <div className="empty">
              <div className="empty-visual">
                <Icon name="briefcase" />
              </div>
              Выбери вакансию, чтобы открыть письмо.
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
function Detail({ job, state, edit, setEdit, act, busy }) {
  const draft = edit?.draft ?? job.draft ?? "",
    status = edit?.status ?? job.status;
  const attempt = state.applications.find((a) => a.job_id === job.id);
  const change = (values) => setEdit({ draft, status, ...values });
  const save = async () => {
    await post("job", { id: job.id, draft, status });
    setEdit(null);
  };
  return (
    <>
      <span className="eyebrow">{job.source}</span>
      <h2>{job.title}</h2>
      <p className="muted">
        {published(job)} · Найдено{" "}
        {new Date(job.created).toLocaleDateString("ru-RU")}
      </p>
      <a href={job.url} target="_blank" rel="noreferrer">
        Открыть вакансию ↗
      </a>
      <p className="muted">
        {job.company} · {job.location}
      </p>
      {job.error && <p>{job.error}</p>}
      <textarea
        aria-label="Черновик письма"
        value={draft}
        disabled={busy}
        onChange={(e) => change({ draft: e.target.value })}
      />
      <div className="actions">
        <Button
          icon="send"
          className="primary"
          disabled={
            busy ||
            state.application.running ||
            job.status === "applied" ||
            status === "applied"
          }
          onClick={() =>
            act(async () => {
              await save();
              await post("apply", { id: job.id });
            }, "Открываю форму отклика")
          }
        >
          Откликнуться
        </Button>
        <Button
          icon="save"
          disabled={busy}
          onClick={() => act(save, "Сохранено")}
        >
          Сохранить
        </Button>
        <Button
          icon="copy"
          onClick={() =>
            act(() => navigator.clipboard.writeText(draft), "Скопировано")
          }
        >
          Копировать
        </Button>
        <select
          aria-label="Статус вакансии"
          disabled={busy}
          value={status}
          onChange={(e) => change({ status: e.target.value })}
        >
          {Object.entries(statuses).map(([s, label]) => (
            <option key={s} value={s}>
              {label}
            </option>
          ))}
        </select>
      </div>
      {attempt && (
        <>
          <p className="muted">
            {attempt.state} · {attempt.message}
          </p>
          {!state.application.running &&
            !["submitted", "failed", "cancelled"].includes(attempt.state) &&
            ["submitted", "not_sent"].map((result, i) => (
              <Button
                key={result}
                disabled={busy}
                onClick={() =>
                  act(() => post("apply/resolve", { id: job.id, result }))
                }
              >
                {i ? "Проверил — не отправлено" : "Проверил — отправлено"}
              </Button>
            ))}
        </>
      )}
      <details>
        <summary>Описание вакансии</summary>
        <pre>{job.description}</pre>
      </details>
    </>
  );
}
