import React, { useState } from "react";
import { Button, Field } from "./ui";
import { post } from "./studio";
const manual = (q) => ["file", "manual", "combobox"].includes(q.kind);
const check = (q) => ["radio", "checkbox"].includes(q.kind);
function Questions({ questions, id, act, busy }) {
  const [answers, setAnswers] = useState(() =>
      Object.fromEntries(
        questions
          .filter((q) => !manual(q))
          .map((q) => [q.id, check(q) ? false : q.suggestion || ""]),
      ),
    ),
    [remember, setRemember] = useState(true);
  const change = (q, v) => setAnswers({ ...answers, [q.id]: v });
  return (
    <>
      <h3>Ответы для этой анкеты</h3>
      {questions.map((q) => (
        <div key={q.id}>
          <Field label={q.label}>
            {manual(q) ? (
              <span>Заполни это поле в браузере.</span>
            ) : check(q) ? (
              <input
                type="checkbox"
                checked={answers[q.id]}
                onChange={(e) => change(q, e.target.checked)}
              />
            ) : q.options?.length ? (
              <select
                value={answers[q.id]}
                onChange={(e) => change(q, e.target.value)}
              >
                <option value="">Выбери ответ</option>
                {q.options.map((o) => (
                  <option key={o}>{o}</option>
                ))}
              </select>
            ) : (
              <textarea
                rows="2"
                value={answers[q.id]}
                onChange={(e) => change(q, e.target.value)}
              />
            )}
          </Field>
          {q.evidence && (
            <small className="muted">Основание: {q.evidence}</small>
          )}
        </div>
      ))}
      <label className="check">
        <input
          type="checkbox"
          checked={remember}
          onChange={(e) => setRemember(e.target.checked)}
        />
        Запомнить ответы для следующих анкет (кроме согласий)
      </label>
      <Button
        disabled={busy}
        onClick={() =>
          act(() => post("apply/answers", { id, answers, remember }))
        }
      >
        Принять ответы и продолжить
      </Button>
    </>
  );
}
export default function Application({ app, act, busy }) {
  if (!app.job_id) return null;
  const call = (path) => act(() => post("apply/" + path, { id: app.job_id }));
  return (
    <div className="panel" id="application-panel">
      <h2>Отклик</h2>
      <p>{app.message}</p>
      {app.waiting && app.questions?.length > 0 && (
        <Questions
          key={app.job_id + JSON.stringify(app.questions)}
          questions={app.questions}
          id={app.job_id}
          {...{ act, busy }}
        />
      )}
      {app.url && (
        <a href={app.url} target="_blank" rel="noreferrer">
          Открыть страницу ↗
        </a>
      )}
      <div className="actions">
        <Button
          className="primary"
          disabled={busy || !app.waiting}
          onClick={() => call("resume")}
        >
          Продолжить после ручного действия
        </Button>
        <Button
          icon="check"
          disabled={busy || (app.running && !app.waiting)}
          onClick={() => call("finish")}
        >
          Закончить отклик — отправил сам
        </Button>
        <Button disabled={busy || !app.running} onClick={() => call("cancel")}>
          Остановить отклик
        </Button>
      </div>
    </div>
  );
}
