import React, { useState } from "react";
import { Button, Field } from "./ui";
import { post } from "./studio";
const labels = {
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
  salary_expectation: "Ожидания по зарплате",
  hybrid_availability: "Доступность для гибридной работы",
};
export default function Settings({ state, act, busy, collect }) {
  const [person, setPerson] = useState(state.applicant),
    [answers, setAnswers] = useState(() =>
      JSON.stringify(person.answers || {}, null, 2),
    ),
    [cfg, setCfg] = useState(state.settings),
    [key, setKey] = useState("");
  const [sources, setSources] = useState(() =>
    cfg.sources
      .filter((s) => s.enabled)
      .map((s) => s.name + " | " + s.url)
      .join("\n"),
  );
  const field = (k) => ({
    value: cfg[k],
    onChange: (e) => setCfg({ ...cfg, [k]: e.target.value }),
  });
  function saveSettings() {
    return act(() => {
      const list = sources
        .split("\n")
        .filter((s) => s.trim())
        .map((line) => {
          const i = line.indexOf("|");
          if (i < 1) throw Error("Введите источник в формате «название | URL»");
          return {
            name: line.slice(0, i).trim(),
            url: line.slice(i + 1).trim(),
            enabled: true,
          };
        });
      return post("settings", { ...cfg, sources: list });
    }, "Настройки сохранены");
  }
  return (
    <section className="section settings">
      <div className="panel">
        <h2>Данные для отклика</h2>
        <div className="row">
          {Object.entries(labels).map(([k, label]) => (
            <Field key={k} label={label}>
              <input
                value={person[k] || ""}
                onChange={(e) => setPerson({ ...person, [k]: e.target.value })}
              />
            </Field>
          ))}
        </div>
        <Field label="Подтверждённые ответы (JSON: текст поля → ответ)">
          <textarea
            rows="4"
            value={answers}
            onChange={(e) => setAnswers(e.target.value)}
          />
        </Field>
        <Button
          disabled={busy}
          onClick={() =>
            act(
              () =>
                post("applicant", {
                  ...person,
                  answers: JSON.parse(answers || "{}"),
                }),
              "Данные сохранены",
            )
          }
        >
          Сохранить данные для отклика
        </Button>
      </div>
      <div className="panel">
        <h2>Твой профиль</h2>
        <Field label="Подтверждённый опыт для генерации писем">
          <textarea rows="9" {...field("profile")} />
        </Field>
      </div>
      <div className="panel">
        <h2>Генерация писем</h2>
        <div className="row">
          <Field label="Основной провайдер">
            <select {...field("provider")}>
              <option value="infercom">Infercom · gpt-oss-120b</option>
              <option value="gemini">Gemini</option>
            </select>
          </Field>
          <Field label="Лимит вакансий на источник / писем за запуск">
            <input type="number" min="1" max="200" {...field("limit")} />
          </Field>
        </div>
        <label className="check">
          <input
            type="checkbox"
            checked={cfg.fallback}
            onChange={(e) => setCfg({ ...cfg, fallback: e.target.checked })}
          />
          Переключаться на второго провайдера при ошибке
        </label>
        <Field label="Ключ Infercom">
          <input
            type="password"
            autoComplete="new-password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
        </Field>
        <Button
          disabled={busy || !key}
          onClick={() =>
            act(async () => {
              await post("key", { key });
              setKey("");
            }, "Ключ сохранён в системном хранилище")
          }
        >
          Сохранить ключ
        </Button>
      </div>
      <div className="panel">
        <h2>Источники и фильтры</h2>
        <Field label="Ключевые слова через запятую">
          <input {...field("keywords")} />
        </Field>
        <Field label="Исключить из заголовков">
          <input {...field("exclude")} />
        </Field>
        <Field label="Источники: название | HTTPS-ссылка (один на строку)">
          <textarea
            rows="8"
            value={sources}
            onChange={(e) => setSources(e.target.value)}
          />
        </Field>
      </div>
      <Button className="primary" disabled={busy} onClick={saveSettings}>
        Сохранить настройки
      </Button>
      <Button
        disabled={busy || state.run.running}
        onClick={() => collect(false)}
      >
        Только собрать, без AI
      </Button>
    </section>
  );
}
