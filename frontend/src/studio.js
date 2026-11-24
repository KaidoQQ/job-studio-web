import { useCallback, useEffect, useRef, useState } from "react";

export async function post(path, data = {}) {
  const token = document.querySelector('meta[name="studio-token"]').content;
  const response = await fetch("/api/" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Studio-Token": token },
    body: JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok)
    throw Error(result.error || "Не удалось выполнить действие");
  return result;
}

export function useStudio() {
  const [state, setState] = useState(null),
    [offline, setOffline] = useState(false),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  const version = useRef(0),
    lock = useRef(false),
    timer = useRef();
  const refresh = useCallback(async () => {
    const seq = ++version.current;
    try {
      const res = await fetch("/api/state", { cache: "no-store" });
      if (!res.ok) throw Error();
      const data = await res.json();
      if (seq === version.current) {
        setState(data);
        setOffline(false);
      }
    } catch {
      if (seq === version.current) setOffline(true);
    }
  }, []);
  useEffect(() => {
    let active = true,
      poll;
    async function tick() {
      await refresh();
      if (active) poll = setTimeout(tick, 3000);
    }
    tick();
    return () => {
      active = false;
      ++version.current;
      clearTimeout(poll);
      clearTimeout(timer.current);
    };
  }, [refresh]);
  function notify(message) {
    clearTimeout(timer.current);
    setNotice(message);
    timer.current = setTimeout(() => setNotice(""), 4500);
  }
  async function act(fn, message) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      await fn();
      if (message) notify(message);
      await refresh();
    } catch (e) {
      notify(e.message);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return { state, offline, busy, act, notice };
}
