import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import Inbox from "./Inbox";
import Settings from "./Settings";
import ParsePlus from "./ParsePlus";
import Application from "./Application";
import { Icon, Button } from "./ui";
import { post, useStudio } from "./studio";

const pages = [
  ["inbox", "briefcase", "Вакансии"],
  ["parseplus", "plus", "Parse plus"],
  ["settings", "settings", "Настройки"],
  ["activity", "activity", "Активность"],
];
const defaults = { query: "", status: "", days: "" };
function App() {
  const { state, offline, notice, act, busy } = useStudio();
  const [page, setPage] = useState("inbox"),
    [selected, setSelected] = useState(null),
    [edit, setEdit] = useState(null),
    [filters, setFilters] = useState(defaults);
  function choose(id) {
    if (selected === id) return true;
    if (edit && !window.confirm("Не сохранять изменения письма?")) return false;
    setEdit(null);
    setSelected(id);
    return true;
  }
  function open(id) {
    if (choose(id)) {
      setFilters(defaults);
      setPage("inbox");
    }
  }
  const collect = (drafts) =>
    act(async () => {
      await post("run", { drafts });
      setPage("inbox");
    });
  const events = state
    ? [
        ...(state.run.events || []),
        ...state.application_events.map(
          (e) =>
            new Date(e.created * 1000).toLocaleTimeString() +
            " [" +
            e.state +
            "] " +
            e.message,
        ),
      ]
    : [];
  return (
    <>
      <aside>
        <div className="brand">
          <span className="mark">
            <Icon name="sparkles" />
          </span>
          Job Studio
        </div>
        <nav>
          {pages.map(([id, icon, label]) => (
            <Button
              key={id}
              data-page={id}
              className={"nav " + (page === id ? "active" : "")}
              aria-current={page === id ? "page" : undefined}
              icon={icon}
              onClick={() => setPage(id)}
            >
              {label}
            </Button>
          ))}
        </nav>
      </aside>
      <main>
        <header>
          <div>
            <h1>
              Работа, которая
              <br />
              <em>тебе подходит.</em>
            </h1>
          </div>
          <div className="actions">
            <Button
              icon="stop"
              disabled={busy || !state?.run.running}
              onClick={() => act(() => post("stop"))}
            >
              Остановить
            </Button>
            <Button
              className="primary"
              icon="sparkles"
              disabled={busy || !state || state.run.running}
              onClick={() => collect(true)}
            >
              Найти возможности
            </Button>
          </div>
        </header>
        <div className={"progress " + (state?.run.running ? "busy" : "")}>
          <span className="dot" />
          <span role="status">
            {offline
              ? "Нет соединения с приложением"
              : state?.application.running
                ? state.application.message
                : state?.run.message || "Загрузка…"}
          </span>
        </div>
        {state && (
          <>
            <Application app={state.application} {...{ act, busy }} />
            <div hidden={page !== "inbox"}>
              <Inbox
                {...{
                  state,
                  selected,
                  choose,
                  edit,
                  setEdit,
                  filters,
                  setFilters,
                  act,
                  busy,
                }}
              />
            </div>
            <div hidden={page !== "parseplus"}>
              <ParsePlus {...{ state, open, act, busy }} />
            </div>
            <div hidden={page !== "settings"}>
              <Settings {...{ state, act, busy, collect }} />
            </div>
            {page === "activity" && (
              <section className="section panel">
                <h2>Журнал запуска</h2>
                <pre id="events">{events.join("\n") || "Пока нет событий"}</pre>
              </section>
            )}
          </>
        )}
      </main>
      {notice && (
        <div className="toast" role="status">
          {notice}
        </div>
      )}
    </>
  );
}
createRoot(document.getElementById("root")).render(<App />);
