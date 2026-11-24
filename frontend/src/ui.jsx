import React from "react";
export function Icon({ name }) {
  return (
    <svg className="icon" aria-hidden="true">
      <use href={"#i-" + name} />
    </svg>
  );
}
export function Button({ icon, children, ...props }) {
  return (
    <button type="button" {...props}>
      {icon && <Icon name={icon} />} {children}
    </button>
  );
}
export function Field({ label, children }) {
  return (
    <label>
      {label}
      {children}
    </label>
  );
}
export const statuses = {
  new: "Новое",
  draft: "Черновик",
  reviewed: "Проверено",
  applied: "Отправлено",
  archived: "Архив",
};
export function published(job) {
  if (!job.published_at) return "Дата публикации неизвестна";
  const d = new Date(job.published_at),
    age = Date.now() - d;
  return (
    (age >= 0 && age < 86400000 ? "Новое · " : "Опубликовано · ") +
    d.toLocaleDateString("ru-RU")
  );
}
