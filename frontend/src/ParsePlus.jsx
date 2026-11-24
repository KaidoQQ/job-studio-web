import React, { useState } from "react";
import { Button, Field } from "./ui";
import { post } from "./studio";
export default function ParsePlus({ state, open, act, busy }) {
  const [url, setUrl] = useState(""),
    [title, setTitle] = useState("");
  const p = state.parse_plus;
  const start = (apply) =>
    act(() => post("parse-plus", { url: url.trim(), title, apply }));
  return (
    <section className="section settings">
      <div className="panel">
        <h1>
          Parse <em>plus.</em>
        </h1>
        <Field label="Ссылка на вакансию">
          <input
            type="url"
            placeholder="https://www.upwork.com/jobs/…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </Field>
        <Field label="Название (необязательно)">
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <div className="actions">
          <Button
            icon="sparkles"
            className="primary"
            disabled={busy || p.running || !url.trim()}
            onClick={() => start(false)}
          >
            Разобрать и подготовить письмо
          </Button>
          <Button
            icon="send"
            disabled={
              busy || p.running || state.application.running || !url.trim()
            }
            onClick={() => start(true)}
          >
            Разобрать и начать отклик
          </Button>
        </div>
        <p className="muted">
          Финальную отправку с расходом Connects подтверждаешь на Upwork
          самостоятельно.
        </p>
      </div>
      <div className="panel">
        <h2>Ход выполнения</h2>
        <p>{p.message}</p>
        <pre>{p.events?.join("\n")}</pre>
        {p.job_id && (
          <Button onClick={() => open(p.job_id)}>
            Открыть карточку вакансии ↗
          </Button>
        )}
      </div>
    </section>
  );
}
