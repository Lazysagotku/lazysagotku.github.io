# -*- coding: utf-8 -*-
"""Собирает «Копилку ссылок» - интерактивную страницу из Learning_Links.md.

Устроена как роадмапы (build_roadmaps.py): статический HTML, JS без сервера,
GitHub Pages открывается без VPN. Разница в том, что здесь не прогресс по
фазам, а список ссылок:

  - ссылки из Learning_Links.md вшиты в страницу при сборке - это источник
    правды, они не редактируются и не удаляются через интерфейс;
  - ссылки, добавленные через форму на самой странице, живут в localStorage
    этого браузера. На другом устройстве их не будет.

Кнопка «Скачать .md» сводит оба списка в один файл в исходном формате -
это и есть путь вернуть новые ссылки в репозиторий: скачал, заменил
Learning_Links.md, закоммитил, пересобрал сайт.

Запуск: python build_links.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from build_roadmaps import CSS, FAVICON, FONTS, THEME_BOOT

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "l2code" / "Learning_Links.md"
OUT = ROOT / "links"

LINK_RE = re.compile(r"^-\s*\[(.+?)\]\((https?://\S+)\)\s*-\s*(.+?)\s*$")


# ---------------------------------------------------------------- разбор

def parse(text: str) -> tuple[str, list[dict]]:
    """Возвращает преамбулу (цитата под заголовком) и список категорий."""
    lines = text.replace("\r\n", "\n").split("\n")
    preamble: list[str] = []
    i = 0
    while i < len(lines) and not lines[i].startswith("## "):
        if lines[i].startswith(">"):
            preamble.append(lines[i].lstrip(">").strip())
        i += 1
    categories: list[dict] = []
    cur: dict | None = None
    for line in lines[i:]:
        if line.startswith("## "):
            cur = {"name": line[3:].strip(), "items": []}
            categories.append(cur)
            continue
        if cur is None:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("*(пусто") or stripped.startswith("---") or stripped.startswith("*Создан"):
            continue
        m = LINK_RE.match(stripped)
        if m:
            title, url, why = m.groups()
            cur["items"].append({"title": title.strip(), "url": url.strip(), "why": why.strip().rstrip(".")})
    return " ".join(preamble), categories


# ---------------------------------------------------------------- стиль и JS

EXTRA_CSS = r"""
.hint { font-size:14px; color:var(--muted); }
.add-form { display:grid; grid-template-columns:1fr 1fr; gap:10px 12px; }
.add-form .full { grid-column:1/-1; }
.add-form input,.add-form select,.add-form textarea { font:inherit; font-size:14px; padding:8px 10px; border:1px solid var(--line); border-radius:3px; background:var(--surface); color:inherit; width:100%; box-sizing:border-box; }
.add-form textarea { resize:vertical; min-height:52px; }
.add-form button { grid-column:1/-1; justify-self:start; font:inherit; font-size:14px; font-weight:600; color:var(--surface); background:var(--accent); border:none; border-radius:3px; padding:9px 18px; cursor:pointer; }
.add-form button:hover { filter:brightness(1.08); }
.cats { display:flex; flex-direction:column; gap:14px; }
.cat { padding:16px 20px; }
.cat h2 { font-size:17px; font-weight:600; margin-bottom:10px; }
.linklist { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:12px; }
.linkitem { padding-bottom:12px; border-bottom:1px solid var(--line); }
.linkitem:last-child { border-bottom:none; padding-bottom:0; }
.li-head { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.li-head a { font-weight:600; font-size:15px; }
.tag.-local { color:var(--accent); background:var(--accent-soft); }
.del { margin-left:auto; font:inherit; font-size:16px; line-height:1; color:var(--muted); background:none; border:1px solid var(--line); border-radius:50%; width:22px; height:22px; cursor:pointer; }
.del:hover { color:var(--break); border-color:var(--break); }
.why { margin-top:4px; font-size:14px; color:var(--muted); }
.empty { color:var(--muted); font-size:14px; }
"""

JS_TEMPLATE = r"""
(() => {
  const KEY = "links-personal-v1";
  const BUILTIN = __BUILTIN__;
  const CATS = BUILTIN.map(c => c.name);

  const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || []; } catch (e) { return []; } };
  const save = (a) => { try { localStorage.setItem(KEY, JSON.stringify(a)); } catch (e) {} };
  let personal = load();

  const esc = (s) => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

  function allNames() {
    const names = CATS.slice();
    personal.forEach(p => { if (!names.includes(p.category)) names.push(p.category); });
    return names;
  }

  function render() {
    const root = document.getElementById("cats");
    root.innerHTML = "";
    let any = false;
    allNames().forEach(name => {
      const builtinItems = (BUILTIN.find(c => c.name === name) || { items: [] }).items
        .map((it, i) => ({ ...it, id: "b:" + name + ":" + i, local: false }));
      const personalItems = personal.filter(p => p.category === name).map(p => ({ ...p, local: true }));
      const items = builtinItems.concat(personalItems);
      if (!items.length) return;
      any = true;
      const sec = document.createElement("section");
      sec.className = "layer cat";
      sec.innerHTML = "<h2>" + esc(name) + '</h2><ul class="linklist"></ul>';
      const ul = sec.querySelector("ul");
      items.forEach(it => {
        const li = document.createElement("li");
        li.className = "linkitem";
        li.innerHTML = '<div class="li-head"><a href="' + esc(it.url) + '" target="_blank" rel="noopener">' + esc(it.title) + "</a>"
          + (it.local ? '<button class="del" type="button" title="Удалить">×</button><span class="tag -local">своя</span>' : "")
          + '</div><p class="why">' + esc(it.why) + "</p>";
        if (it.local) {
          li.querySelector(".del").addEventListener("click", () => {
            if (!confirm("Удалить ссылку «" + it.title + "»?")) return;
            personal = personal.filter(p => p.id !== it.id);
            save(personal);
            render();
          });
        }
        ul.appendChild(li);
      });
      root.appendChild(sec);
    });
    if (!any) root.innerHTML = '<p class="empty">Ссылок пока нет - добавь первую формой выше.</p>';
    const sel = document.getElementById("f-cat");
    if (sel) {
      const cur = sel.value;
      sel.innerHTML = allNames().map(n => '<option value="' + esc(n) + '">' + esc(n) + "</option>").join("")
        + '<option value="__new__">+ новая категория</option>';
      if ([...sel.options].some(o => o.value === cur)) sel.value = cur;
    }
  }

  const $ = (id) => document.getElementById(id);

  $("f-cat").addEventListener("change", () => {
    $("f-cat-new").hidden = $("f-cat").value !== "__new__";
  });

  $("add-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const url = $("f-url").value.trim();
    const title = $("f-title").value.trim();
    const why = $("f-why").value.trim();
    let category = $("f-cat").value;
    if (category === "__new__") category = $("f-cat-new").value.trim();
    if (!url || !title || !why || !category) return;
    personal.push({ id: "l:" + Date.now() + Math.random().toString(36).slice(2), category, title, url, why });
    save(personal);
    e.target.reset();
    $("f-cat-new").hidden = true;
    render();
  });

  $("export-md").addEventListener("click", () => {
    const lines = ["# Копилка ссылок - каналы, курсы, статьи", "",
      "> Личный список Ивана. Сюда падает всё, что найдено по пути и пригодится позже -",
      "> необязательно прямо сейчас. Каждая ссылка с одной строкой «зачем», без нее",
      "> через полгода непонятно, почему она вообще тут лежит. Пополняется по мере",
      "> находок, не по расписанию.",
      ">",
      "> Курируемые списки документации под каждую фазу - в разделе «Ресурсы» самих",
      "> роадмапов (`PythonBackend_Roadmap.md`, `Roadmap_Infra_Sept2026.md` и так далее).",
      "> Здесь - всё остальное: каналы, плейлисты, статьи, разовые находки.",
      "", "---", ""];
    allNames().forEach(name => {
      lines.push("## " + name, "");
      const builtinItems = (BUILTIN.find(c => c.name === name) || { items: [] }).items;
      const personalItems = personal.filter(p => p.category === name);
      const items = builtinItems.concat(personalItems);
      if (!items.length) {
        lines.push("*(пусто пока)*", "");
      } else {
        items.forEach(it => lines.push("- [" + it.title + "](" + it.url + ") - " + it.why + "."));
        lines.push("");
      }
    });
    lines.push("---", "*Обновлено со страницы «Копилка ссылок», " + new Date().toLocaleDateString("ru-RU") + ".*", "");
    const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "Learning_Links.md"; a.click();
    URL.revokeObjectURL(a.href);
  });

  $("export-json").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify({ at: new Date().toISOString(), personal }, null, 2)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "links-backup.json"; a.click();
    URL.revokeObjectURL(a.href);
  });

  $("import-json").addEventListener("change", (e) => {
    const f = e.target.files[0]; if (!f) return;
    f.text().then(t => {
      try {
        const data = JSON.parse(t);
        const incoming = Array.isArray(data) ? data : (data.personal || []);
        const ids = new Set(personal.map(p => p.id));
        incoming.forEach(p => { if (p && p.id && !ids.has(p.id)) { personal.push(p); ids.add(p.id); } });
        save(personal);
        render();
      } catch (err) { alert("Файл не похож на резервную копию копилки."); }
    });
    e.target.value = "";
  });

  render();
})();
"""


def render(preamble: str, categories: list[dict]) -> str:
    cat_names = "".join(f'<option value="{c["name"]}">{c["name"]}</option>' for c in categories)
    builtin_json = json.dumps(categories, ensure_ascii=False)
    js = JS_TEMPLATE.replace("__BUILTIN__", builtin_json)
    body = f"""
<div class="wrap">
  <header class="masthead">
    <div>
      <a class="back" href="/">← Иван Архипов</a>
      <p class="eyebrow">Копилка · растёт без расписания</p>
      <h1>Ссылки на будущее</h1>
      <p class="sub">{preamble}</p>
    </div>
  </header>

  <section class="summary">
    <p class="hint">Новые ссылки, добавленные формой ниже, живут в этом браузере - на другом устройстве их не будет.
    Время от времени жми «Скачать .md» и присылай файл, чтобы он попал в репозиторий насовсем.</p>
    <form id="add-form" class="add-form">
      <input type="url" id="f-url" placeholder="https://..." required>
      <input type="text" id="f-title" placeholder="Название" required>
      <select id="f-cat">{cat_names}<option value="__new__">+ новая категория</option></select>
      <input type="text" id="f-cat-new" class="full" placeholder="Название новой категории" hidden>
      <textarea id="f-why" class="full" placeholder="Зачем - одна строка" required></textarea>
      <button type="submit">Добавить</button>
    </form>
    <div class="tools">
      <button type="button" id="export-md">Скачать .md для репозитория</button>
      <button type="button" id="export-json">Скачать резервную копию</button>
      <label for="import-json">Загрузить резервную копию</label><input type="file" id="import-json" accept="application/json">
    </div>
  </section>

  <div class="cats" id="cats"></div>
</div>"""
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">{THEME_BOOT}'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">'
            f'<title>Копилка ссылок - Иван Архипов</title>'
            f'<meta name="description" content="Личный список каналов, курсов и статей с пояснением зачем - Иван Архипов">'
            f'<link rel="icon" href="{FAVICON}">{FONTS}<style>{CSS}{EXTRA_CSS}</style></head>'
            f'<body>{body}<script>{js}</script><script src="/theme.js?v=2"></script></body></html>')


def main() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    preamble, categories = parse(text)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.html").write_text(render(preamble, categories), encoding="utf-8", newline="\n")
    total = sum(len(c["items"]) for c in categories)
    print(f"links/index.html - {len(categories)} категорий, {total} ссылок из репозитория")


if __name__ == "__main__":
    main()
