# -*- coding: utf-8 -*-
"""Собирает интерактивные роадмапы из markdown-файлов фаз в l2code.

Два уровня на каждое направление:
  {folder}/index.html      - прогрессия: стек фаз с чекбоксами, кольца, общая полоса
  {folder}/{n}/index.html  - фаза целиком: боковая навигация по разделам, весь контент

Прогресс живёт в localStorage под одним ключом на направление - главная и
страницы фаз читают и пишут одно и то же. Сервера нет намеренно: GitHub Pages
открывается без VPN.

Метаданные берутся из HTML-комментариев в файле-оглавлении:
  <!-- meta: deadline=2026-09-16; deadline_label=до собеседования -->
  <!-- schedule: 0=чт 10.09; 1=пт 11.09 -->          дата на карточке фазы
  <!-- progress: 1=90; 2=75 -->                      самооценка поглощения, стартовая отметка

Запуск:  python build_roadmaps.py            - все направления
         python build_roadmaps.py infra      - одно
"""

from __future__ import annotations

import html
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent
L2CODE = ROOT.parent / "l2code"
GITHUB = "https://github.com/Lazysagotku/l2code/blob/main/"

MD = markdown.Markdown(extensions=["extra", "sane_lists"], output_format="html5")


def md(text: str) -> str:
    MD.reset()
    return MD.convert(text.strip())


def md_inline(text: str) -> str:
    out = md(text)
    if out.startswith("<p>") and out.endswith("</p>") and out.count("<p>") == 1:
        out = out[3:-4]
    return out


# ---------------------------------------------------------------- направления

@dataclass
class Track:
    key: str
    title: str
    lead: str
    folder: str
    roadmap: str
    phase_glob: str      # пусто - фазы внутри roadmap
    unit: str            # Слой / Фаза
    unit_pl: str         # Слои / Фазы
    unit_gen: str        # слоёв / фаз
    icon: str
    closed: str = ""     # закрыт / закрыта
    acc: str = ""        # слой / фазу  (открыть что?)
    loc: str = ""        # этом слое / этой фазе


TRACKS = {
    "infra": Track("infra", "Стенд с нуля",
                   "Чистый VPS, десять слоёв обвязки. Каждый слой проверяется руками и ломается намеренно.",
                   "roadmap-infra", "Roadmap_Infra_Sept2026.md", "Infra_Layer*.md", "Слой", "Слои", "слоёв", "🖥", "закрыт", "слой", "этом слое"),
    "python": Track("python", "Python Backend",
                    "Бэкенд-паттерны и идиомы поверх живого языка. Полигон - трекер и разведчик, написанные Claude.",
                    "roadmap-python", "PythonBackend_Roadmap.md", "Python_Phase*.md", "Фаза", "Фазы", "фаз", "🐍", "закрыта", "фазу", "этой фазе"),
    "ai": Track("ai", "AI Product Engineer",
                "Встраивание готовых LLM в продукт. Фазы 1 и 2 нужны сейчас - под вакансии, где владение AI в требованиях.",
                "roadmap-ai", "AIEngineer_Roadmap.md", "AI_Phase*.md", "Фаза", "Фазы", "фаз", "🤖", "закрыта", "фазу", "этой фазе"),
    "csharp": Track("csharp", "C# Backend",
                    "Фоновый трек с 1 сентября. Закрывает вопрос «читаете ли код разработчиков» и доводит Life Notes.",
                    "roadmap", "CSharp_Roadmap_Software.md", "", "Фаза", "Фазы", "фаз", "🟣", "закрыта", "фазу", "этой фазе"),
}

SIBLINGS = {
    "infra": [("python", "/roadmap-python/"), ("ai", "/roadmap-ai/"), ("csharp", "/roadmap/")],
    "python": [("infra", "/roadmap-infra/"), ("ai", "/roadmap-ai/"), ("csharp", "/roadmap/")],
    "ai": [("infra", "/roadmap-infra/"), ("python", "/roadmap-python/"), ("csharp", "/roadmap/")],
    "csharp": [("infra", "/roadmap-infra/"), ("python", "/roadmap-python/"), ("ai", "/roadmap-ai/")],
}


# ---------------------------------------------------------------- разбор

SECTION_KINDS = {"🎭": "analogy", "📖": "theory", "🔧": "practice", "💥": "break",
                 "✅": "task", "🌍": "life", "❓": "questions"}
SECTION_TITLES = {"analogy": "Аналогия", "theory": "Теория", "practice": "Практика",
                  "break": "Сломай намеренно", "task": "Задание", "life": "Из жизни",
                  "questions": "Вопросы с ответами"}
ICONS = {"analogy": "🎭", "theory": "📖", "practice": "🔧", "break": "💥",
         "task": "✅", "life": "🌍", "questions": "❓", "other": "▪"}

HEAD_RE = re.compile(r"^# (\S+) (?:Слой|Фаза) (\d+)\. (.+?)(?: \((.+)\))?\s*$")
STEP_RE = re.compile(r"^(\*{0,2})(\d+)\.\*{0,2}\s+(.+?)\s*$")
META_RE = re.compile(r"<!--\s*(\w+):\s*(.*?)\s*-->")


@dataclass
class Step:
    id: str
    title: str
    body: str


@dataclass
class Section:
    kind: str
    title: str
    html: str = ""
    steps: list[Step] = field(default_factory=list)
    parts: list[tuple[str, object]] = field(default_factory=list)


@dataclass
class Phase:
    n: int
    emoji: str
    title: str
    note: str
    source: str
    sections: list[Section]
    baseline: int = 0        # самооценка, проценты
    when: str = ""           # дата из расписания среза

    @property
    def steps(self) -> list[Step]:
        return [s for sec in self.sections for s in sec.steps]

    @property
    def status(self) -> str:
        low = self.note.lower()
        if "завершен" in low:
            return "done"
        if "пропущен" in low:
            return "skipped"
        return ""

    @property
    def hours(self) -> float:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*час", self.note)
        return float(m.group(1).replace(",", ".")) if m else 0.0

    @property
    def analogy(self) -> str:
        for s in self.sections:
            if s.kind == "analogy":
                return s.html
        return ""

    @property
    def criterion(self) -> str:
        for s in self.sections:
            if s.kind == "task":
                return s.html
        return ""


def _split_top(lines: list[str], marker: str):
    chunks, head, body, in_code = [], "", [], False
    for line in lines:
        if line.startswith("```"):
            in_code = not in_code
        if not in_code and line.startswith(marker):
            chunks.append((head, body))
            head, body = line[len(marker):].strip(), []
        else:
            body.append(line)
    chunks.append((head, body))
    return chunks


def _kind_of(head: str) -> str:
    for emoji, kind in SECTION_KINDS.items():
        if head.startswith(emoji):
            return kind
    return "other"


def _parse_steps(kind: str, phase_n: int, body: list[str]) -> Section:
    sec = Section(kind=kind, title=SECTION_TITLES[kind])
    buf: list[str] = []
    current: Step | None = None
    idx, in_code = 0, False

    def flush_text():
        text = "\n".join(buf).strip()
        if text:
            sec.parts.append(("text", md(text)))
        buf.clear()

    def flush_step():
        nonlocal current
        if current is not None:
            current.body = md("\n".join(buf)) if any(l.strip() for l in buf) else ""
            sec.steps.append(current)
            sec.parts.append(("step", current))
            current = None
        buf.clear()

    for line in body:
        if line.startswith("```"):
            in_code = not in_code
        m = None if in_code else STEP_RE.match(line)
        if m:
            flush_step() if current else flush_text()
            idx += 1
            opened, rest = m.group(1), m.group(3).strip()
            title = ("**" + rest) if opened else rest
            if title.startswith("**") and title.endswith("**") and title.count("**") == 2:
                title = title[2:-2]
            title = title.replace(":**", "**").rstrip(":").strip()
            current = Step(id=f"{phase_n}-{kind}-{idx}", title=md_inline(title), body="")
        elif (not in_code) and line.startswith("### "):
            flush_step() if current else flush_text()
            buf.append(line)
        else:
            buf.append(line)
    flush_step() if current else flush_text()
    return sec


def parse_phase(text: str, source: str) -> Phase | None:
    lines = text.split("\n")
    m = HEAD_RE.match(lines[0])
    if not m:
        return None
    emoji, n, title, note = m.group(1), int(m.group(2)), m.group(3), m.group(4) or ""
    rest = lines[1:]
    while rest and (not rest[0].strip() or rest[0].startswith(">")):
        rest.pop(0)
    sections: list[Section] = []
    for head, body in _split_top(rest, "## "):
        while body and body[-1].strip() in ("", "---"):
            body.pop()
        if not head and not body:
            continue
        kind = _kind_of(head) if head else "other"
        if kind in ("practice", "break"):
            sections.append(_parse_steps(kind, n, body))
        else:
            clean = re.sub(r"^\S+\s+", "", head) if head else ""
            sec = Section(kind=kind, title=SECTION_TITLES.get(kind, clean) if kind != "other" else clean)
            sec.html = md("\n".join(body))
            sections.append(sec)
    return Phase(n=n, emoji=emoji, title=title, note=note, source=source, sections=sections)


def _meta(text: str) -> dict:
    out: dict = {}
    for key, val in META_RE.findall(text):
        pairs = {}
        for chunk in val.split(";"):
            if "=" in chunk:
                k, v = chunk.split("=", 1)
                pairs[k.strip()] = v.strip()
        out[key] = pairs
    return out


def load(track: Track) -> tuple[str, list[Phase], dict]:
    roadmap_text = (L2CODE / track.roadmap).read_text(encoding="utf-8")
    meta = _meta(roadmap_text)
    phases: list[Phase] = []
    if track.phase_glob:
        for path in sorted(L2CODE.glob(track.phase_glob)):
            ph = parse_phase(path.read_text(encoding="utf-8"), path.name)
            if ph:
                phases.append(ph)
        phases.sort(key=lambda p: p.n)
        intro_src = roadmap_text.split("\n# 📂", 1)[0]
    else:
        lines = roadmap_text.split("\n")
        starts = [i for i, l in enumerate(lines) if HEAD_RE.match(l)]
        tails = [i for i, l in enumerate(lines) if l.startswith("# 📅") or l.startswith("# 🛠")]
        end = tails[0] if tails else len(lines)
        for k, s in enumerate(starts):
            e = starts[k + 1] if k + 1 < len(starts) else end
            ph = parse_phase("\n".join(lines[s:e]), track.roadmap)
            if ph:
                phases.append(ph)
        intro_src = "\n".join(lines[:starts[0]]) if starts else roadmap_text
    progress = meta.get("progress", {})
    schedule = meta.get("schedule", {})
    for ph in phases:
        ph.baseline = int(progress.get(str(ph.n), 0) or 0)
        ph.when = schedule.get(str(ph.n), "")
    intro_lines = [l for l in intro_src.split("\n")[1:] if not l.startswith("<!--")]
    return md("\n".join(intro_lines)), phases, meta.get("meta", {})


# ---------------------------------------------------------------- стиль

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E"
           "%3Crect width='64' height='64' rx='12' fill='%23a8741a'/%3E%3Ctext x='32' y='43' "
           "font-family='Georgia,serif' font-weight='700' font-size='30' fill='white' "
           "text-anchor='middle'%3EИА%3C/text%3E%3C/svg%3E")

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bitter:wght@600;700&family=Source+Sans+3:wght@400;600&family=JetBrains+Mono:wght@400;700&display=swap">')

CSS = r"""
:root {
  --ground:#e8eaee; --surface:#fff; --sunken:#f1f3f6; --ink:#1a1d24; --muted:#626b78; --faint:#8b939f;
  --line:#d2d7de; --accent:#a8741a; --accent-soft:#f5ead6; --done:#2f6f56; --done-soft:#dfeee7; --break:#97452f;
  --code-bg:#1a1d24; --code-ink:#e6e9ee;
  --shadow:0 1px 2px rgba(26,29,36,.06),0 4px 12px rgba(26,29,36,.05);
  color-scheme: light;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --ground:#131519; --surface:#1b1e24; --sunken:#22262d; --ink:#e6e9ee; --muted:#9aa3b0; --faint:#6d7684;
  --line:#2e333c; --accent:#d9a440; --accent-soft:#35291453; --done:#5aab86; --done-soft:#1d3a2e5c; --break:#d0785e;
  --code-bg:#0f1114; --code-ink:#dfe3e8; --shadow:0 1px 2px rgba(0,0,0,.3),0 4px 14px rgba(0,0,0,.25); color-scheme: dark;
} }
:root[data-theme="dark"] {
  --ground:#131519; --surface:#1b1e24; --sunken:#22262d; --ink:#e6e9ee; --muted:#9aa3b0; --faint:#6d7684;
  --line:#2e333c; --accent:#d9a440; --accent-soft:#35291453; --done:#5aab86; --done-soft:#1d3a2e5c; --break:#d0785e;
  --code-bg:#0f1114; --code-ink:#dfe3e8; --shadow:0 1px 2px rgba(0,0,0,.3),0 4px 14px rgba(0,0,0,.25); color-scheme: dark;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--ground); color:var(--ink); font-family:"Source Sans 3",system-ui,sans-serif; font-size:16px; line-height:1.55; -webkit-font-smoothing:antialiased; }
a { color:var(--accent); text-underline-offset:3px; }
h1,h2,h3,h4 { font-family:Bitter,Georgia,serif; margin:0; text-wrap:balance; }
p { margin:0; }
code { font-family:"JetBrains Mono",ui-monospace,monospace; font-size:.88em; background:var(--sunken); padding:.08em .35em; border-radius:3px; }
pre { background:var(--code-bg); color:var(--code-ink); padding:.85rem 1rem; border-radius:4px; overflow-x:auto; font-size:.85rem; line-height:1.5; margin:.7rem 0; }
pre code { background:none; padding:0; color:inherit; font-size:inherit; }
table { border-collapse:collapse; font-size:.92rem; margin:.7rem 0; display:block; overflow-x:auto; max-width:100%; }
th,td { text-align:left; padding:.42rem .6rem; border-bottom:1px solid var(--line); vertical-align:top; }
th { font-family:"JetBrains Mono",monospace; font-size:.72rem; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); font-weight:400; }
blockquote { margin:.5rem 0; padding:.6rem .95rem; border-left:3px solid var(--accent); background:var(--accent-soft); border-radius:0 4px 4px 0; }
blockquote p+p { margin-top:.45rem; }
ul,ol { padding-left:1.3rem; margin:.45rem 0; }
li+li { margin-top:.2rem; }
hr { border:0; border-top:1px solid var(--line); margin:1.2rem 0; }
.eyebrow { font-family:"JetBrains Mono",monospace; font-size:11px; letter-spacing:.16em; text-transform:uppercase; color:var(--muted); margin:0 0 6px; }
.wrap { max-width:940px; margin:0 auto; padding:28px 20px 72px; display:flex; flex-direction:column; gap:26px; }

.theme-switch { position:fixed; top:1rem; right:1rem; z-index:200; width:2.5rem; height:2.5rem; border-radius:50%; border:1px solid var(--line); background:var(--surface); color:var(--ink); font-size:1.05rem; cursor:pointer; display:grid; place-items:center; box-shadow:var(--shadow); }
.theme-switch:hover { border-color:var(--accent); }

/* ---------- главная ---------- */
.masthead { display:flex; flex-wrap:wrap; gap:24px; align-items:flex-end; justify-content:space-between; padding-bottom:20px; border-bottom:2px solid var(--ink); }
.masthead h1 { font-weight:700; font-size:clamp(30px,5vw,42px); letter-spacing:-.015em; }
.masthead .sub { margin-top:6px; color:var(--muted); max-width:46ch; }
.masthead .back { font-size:.9rem; text-decoration:none; color:var(--muted); }
.countdown { font-family:"JetBrains Mono",monospace; text-align:right; line-height:1.25; }
.countdown .num { font-size:34px; font-weight:700; color:var(--accent); font-variant-numeric:tabular-nums; }
.countdown .cap { font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:var(--muted); }
.summary { background:var(--surface); border:1px solid var(--line); border-radius:3px; box-shadow:var(--shadow); padding:20px 22px; display:flex; flex-direction:column; gap:16px; }
.meters { display:flex; flex-wrap:wrap; gap:28px 40px; }
.meter { display:flex; flex-direction:column; gap:2px; }
.meter .val { font-family:"JetBrains Mono",monospace; font-size:26px; font-weight:700; font-variant-numeric:tabular-nums; line-height:1.1; }
.meter .lbl { font-family:"JetBrains Mono",monospace; font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); }
.meter.-done .val { color:var(--done); }
.bar { height:10px; background:var(--sunken); border:1px solid var(--line); border-radius:2px; overflow:hidden; }
.bar>span { display:block; height:100%; width:0; background:repeating-linear-gradient(135deg,var(--accent) 0 6px,color-mix(in srgb,var(--accent) 78%,#000) 6px 12px); transition:width .55s cubic-bezier(.22,1,.36,1); }
.bar.-full>span { background:var(--done); }
.tools { display:flex; flex-wrap:wrap; gap:8px; }
.tools button,.tools label { font:inherit; font-size:13px; color:var(--muted); background:none; border:1px solid var(--line); border-radius:2px; padding:5px 11px; cursor:pointer; }
.tools button:hover,.tools label:hover { color:var(--ink); border-color:var(--faint); }
.tools .danger { margin-left:auto; }
.tools input[type=file] { display:none; }
.section-label { font-family:"JetBrains Mono",monospace; font-size:11px; letter-spacing:.16em; text-transform:uppercase; color:var(--muted); display:flex; align-items:center; gap:12px; margin:0; }
.section-label::after { content:""; flex:1; height:1px; background:var(--line); }
.stack { display:flex; flex-direction:column; gap:10px; }
.layer { background:var(--surface); border:1px solid var(--line); border-left:4px solid var(--line); border-radius:3px; transition:border-left-color .35s,background .35s; }
.layer.-active { border-left-color:var(--accent); }
.layer.-complete { border-left-color:var(--done); background:var(--sunken); }
.layer.-skipped { opacity:.65; }
.layer>summary { list-style:none; cursor:pointer; padding:14px 18px; display:grid; grid-template-columns:44px 1fr auto; gap:14px; align-items:center; }
.layer>summary::-webkit-details-marker { display:none; }
.idx { font-family:"JetBrains Mono",monospace; font-size:22px; font-weight:700; color:var(--faint); font-variant-numeric:tabular-nums; text-align:center; }
.layer.-complete .idx { color:var(--done); }
.layer.-active .idx { color:var(--accent); }
.headline h2 { font-size:18px; font-weight:600; letter-spacing:-.01em; }
.headline .meta { font-family:"JetBrains Mono",monospace; font-size:11.5px; color:var(--muted); margin-top:3px; display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
.tag { font-size:10px; letter-spacing:.1em; text-transform:uppercase; padding:2px 7px; border-radius:2px; border:1px solid currentColor; }
.tag.-when { color:var(--accent); background:var(--accent-soft); }
.gauge { display:flex; align-items:center; gap:10px; }
.gauge .frac { font-family:"JetBrains Mono",monospace; font-size:12.5px; color:var(--muted); font-variant-numeric:tabular-nums; white-space:nowrap; }
.ring { width:30px; height:30px; flex:none; transform:rotate(-90deg); }
.ring circle { fill:none; stroke-width:4; }
.ring .track { stroke:var(--line); }
.ring .fill { stroke:var(--accent); stroke-linecap:round; transition:stroke-dashoffset .55s cubic-bezier(.22,1,.36,1),stroke .3s; }
.layer.-complete .ring .fill { stroke:var(--done); }
.body { padding:0 18px 18px 62px; display:flex; flex-direction:column; gap:14px; }
.note { font-size:14.5px; color:var(--muted); border-left:2px solid var(--line); padding-left:12px; }
.note p+p { margin-top:.4rem; }
.open-phase { align-self:flex-start; font-family:"JetBrains Mono",monospace; font-size:12px; letter-spacing:.06em; text-transform:uppercase; text-decoration:none; color:var(--ink); border:1px solid var(--ink); padding:7px 12px; border-radius:2px; }
.open-phase:hover { background:var(--ink); color:var(--surface); }
.criterion { background:var(--sunken); border:1px dashed var(--line); border-radius:2px; padding:11px 14px; font-size:14.5px; }
.criterion b { font-family:"JetBrains Mono",monospace; font-size:10.5px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); display:block; margin-bottom:3px; font-weight:400; }
.criterion p+p { margin-top:.4rem; }
.base { font-family:"JetBrains Mono",monospace; font-size:11px; color:var(--muted); }

/* ---------- шаги ---------- */
.steps { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:1px; }
.steps .h { font-family:"JetBrains Mono",monospace; font-size:10.5px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); padding:8px 8px 2px; }
.step { display:flex; gap:11px; align-items:flex-start; padding:6px 8px; border-radius:2px; }
.step:hover { background:var(--sunken); }
.step input { position:absolute; opacity:0; width:0; height:0; }
.box { flex:none; width:17px; height:17px; margin-top:3px; border:1.5px solid var(--faint); border-radius:2px; background:var(--surface); position:relative; transition:border-color .2s,background .2s; cursor:pointer; }
.box::after { content:""; position:absolute; left:4.5px; top:1px; width:5px; height:9px; border:solid var(--surface); border-width:0 2px 2px 0; transform:rotate(45deg) scale(0); transform-origin:center; transition:transform .22s cubic-bezier(.34,1.56,.64,1); }
.step.-on .box { background:var(--done); border-color:var(--done); }
.step.-on .box::after { transform:rotate(45deg) scale(1); }
.step .txt { font-size:15px; flex:1; cursor:pointer; }
.step.-on .txt { color:var(--faint); text-decoration:line-through; text-decoration-thickness:1px; }
.step.-break .txt::before { content:"сломать"; font-family:"JetBrains Mono",monospace; font-size:9.5px; letter-spacing:.1em; text-transform:uppercase; color:var(--break); border:1px solid currentColor; border-radius:2px; padding:1px 5px; margin-right:8px; vertical-align:2px; }
.step .more { flex:none; font-family:"JetBrains Mono",monospace; font-size:11px; color:var(--muted); cursor:pointer; padding-top:4px; }
.step-body { display:none; padding:2px 8px 10px 36px; font-size:14px; }
.step-body.-open { display:block; }
.step-body pre { font-size:.82rem; }
.interlude { font-size:14.5px; padding:6px 8px; }
.interlude h3 { font-size:15px; margin:10px 0 4px; }
.interlude p+p { margin-top:.4rem; }

/* ---------- страница фазы ---------- */
.layout { display:grid; grid-template-columns:250px minmax(0,1fr); gap:0; min-height:100vh; }
.side { background:var(--surface); border-right:1px solid var(--line); padding:26px 18px 40px; position:sticky; top:0; height:100vh; overflow-y:auto; font-size:14px; }
.side .back { display:block; font-size:13px; color:var(--muted); text-decoration:none; margin-bottom:10px; }
.side .back:hover { color:var(--ink); }
.side h2 { font-size:16px; font-weight:700; margin-bottom:4px; }
.side .prog { font-family:"JetBrains Mono",monospace; font-size:11.5px; color:var(--muted); margin-bottom:6px; font-variant-numeric:tabular-nums; }
.side .bar { height:6px; margin-bottom:22px; }
.side nav { margin-bottom:22px; }
.side nav b { display:block; font-family:"JetBrains Mono",monospace; font-size:10.5px; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); font-weight:400; margin-bottom:6px; }
.side nav a { display:flex; gap:8px; align-items:baseline; padding:5px 8px; margin:0 -8px; border-radius:2px; color:var(--ink); text-decoration:none; }
.side nav a:hover { background:var(--sunken); }
.side nav a.-cur { background:var(--accent-soft); color:var(--accent); font-weight:600; }
.side nav a.-done { color:var(--faint); }
.side nav a .n { font-family:"JetBrains Mono",monospace; font-size:11px; color:var(--faint); width:22px; flex:none; }
.side nav a .i { width:18px; flex:none; text-align:center; }
.content { padding:28px clamp(20px,5vw,56px) 80px; max-width:820px; }
.topbar { display:flex; flex-wrap:wrap; gap:8px 20px; align-items:baseline; font-family:"JetBrains Mono",monospace; font-size:12px; color:var(--muted); padding-bottom:12px; border-bottom:1px solid var(--line); margin-bottom:26px; }
.topbar b { color:var(--ink); font-weight:600; }
.content h1 { font-size:clamp(26px,4vw,34px); font-weight:700; letter-spacing:-.015em; margin-bottom:6px; }
.content .lead { color:var(--muted); font-family:"JetBrains Mono",monospace; font-size:12px; margin-bottom:28px; }
.sec { margin-top:34px; scroll-margin-top:20px; }
.sec>h2 { font-family:"JetBrains Mono",monospace; font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:var(--muted); display:flex; align-items:center; gap:8px; margin-bottom:12px; font-weight:400; }
.sec>h2 .i { font-size:15px; }
.sec .text h3 { font-size:17px; margin:20px 0 6px; }
.sec .text h4 { font-size:15.5px; margin:14px 0 4px; }
.sec .text p+p { margin-top:.55rem; }
.sec .text>p:first-child { margin-top:0; }
.sec.-analogy .text { background:var(--surface); border:1px solid var(--line); border-radius:3px; padding:14px 18px; }
.sec.-task .text { background:var(--sunken); border:1px dashed var(--line); border-radius:3px; padding:12px 16px; }
.sec.-questions .text>p>strong { display:block; margin-top:1rem; font-family:Bitter,Georgia,serif; font-size:16px; }
.sec .steps { background:var(--surface); border:1px solid var(--line); border-radius:3px; padding:6px; }
.pager { display:flex; justify-content:space-between; gap:16px; margin-top:48px; padding-top:20px; border-top:1px solid var(--line); font-size:14px; }
.pager a { text-decoration:none; color:var(--ink); }
.pager a:hover { color:var(--accent); }
.pager .r { text-align:right; }
.src { font-family:"JetBrains Mono",monospace; font-size:11px; color:var(--muted); margin-top:28px; }
@media (max-width:820px) {
  .layout { grid-template-columns:1fr; }
  .side { position:static; height:auto; border-right:0; border-bottom:1px solid var(--line); }
  .side nav.-siblings { display:none; }
  .body { padding-left:18px; }
  .layer>summary { grid-template-columns:32px 1fr; gap:10px; }
  .gauge { grid-column:1/-1; justify-content:flex-start; padding-left:42px; }
  .countdown { text-align:left; }
}
@media (prefers-reduced-motion:reduce) { * { transition-duration:.01ms !important; } }
"""

# JS общий: прогресс в localStorage. Плейсхолдеры __KEY__, __DEADLINE__, __PHASES__.
JS = r"""
(() => {
  const KEY = "__KEY__";
  const DEADLINE = __DEADLINE__;
  const PHASES = __PHASES__;
  const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; } };
  const save = (s) => { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} };
  let state = load();
  const C = 2 * Math.PI * 12;

  function phasePct(n, done) {
    const p = PHASES[n];
    if (p.status === "done") return 1;
    if (p.status === "skipped") return 0;
    const byChecks = p.total ? done / p.total : 0;
    return Math.max(byChecks, p.baseline / 100);
  }

  function paint() {
    const doneBy = {};
    document.querySelectorAll(".step[data-step]").forEach(st => {
      const on = !!state[st.dataset.step];
      st.classList.toggle("-on", on);
      const box = st.querySelector("input"); if (box) box.checked = on;
      const n = st.dataset.step.split("-")[0];
      doneBy[n] = (doneBy[n] || 0) + (on ? 1 : 0);
    });
    Object.keys(PHASES).forEach(n => {
      if (doneBy[n] === undefined) doneBy[n] = Object.keys(state).filter(k => k.startsWith(n + "-")).length;
    });

    let sumPct = 0, count = 0, stepsDone = 0, stepsAll = 0, hoursLeft = 0, closed = 0;
    Object.keys(PHASES).forEach(n => {
      const p = PHASES[n];
      if (p.status === "skipped") return;
      const pct = phasePct(n, doneBy[n]);
      sumPct += pct; count++;
      stepsDone += Math.min(doneBy[n], p.total); stepsAll += p.total;
      if (pct >= 1) closed++; else hoursLeft += p.hours;
      const card = document.querySelector('[data-phase="' + n + '"]');
      if (card) {
        card.classList.toggle("-complete", pct >= 1);
        card.classList.toggle("-active", pct > 0 && pct < 1);
        const frac = card.querySelector(".frac");
        if (frac) frac.textContent = p.total ? (doneBy[n] + "/" + p.total) : Math.round(pct * 100) + "%";
        const fill = card.querySelector(".ring .fill");
        if (fill) fill.setAttribute("stroke-dashoffset", (C * (1 - pct)).toFixed(2));
      }
      const side = document.querySelector('.side a[data-phase="' + n + '"]');
      if (side) side.classList.toggle("-done", pct >= 1);
    });
    const total = count ? sumPct / count : 0;
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    set("pct", Math.round(total * 100) + "%");
    set("steps-done", stepsDone); set("steps-all", stepsAll);
    set("hours-left", Math.round(hoursLeft * 10) / 10);
    set("layers-done", closed + "/" + count);
    document.querySelectorAll(".bar[data-total]").forEach(b => {
      b.firstElementChild.style.width = (total * 100) + "%";
      b.classList.toggle("-full", total >= 1);
    });
    const cur = document.body.dataset.phase;
    if (cur !== undefined && PHASES[cur]) { set("cur-done", doneBy[cur]); set("cur-all", PHASES[cur].total); }
  }

  document.querySelectorAll(".step[data-step]").forEach(st => {
    const toggle = () => { if (state[st.dataset.step]) delete state[st.dataset.step]; else state[st.dataset.step] = 1; save(state); paint(); };
    st.querySelector(".box").addEventListener("click", toggle);
    st.querySelector(".txt").addEventListener("click", toggle);
    const more = st.querySelector(".more");
    if (more) more.addEventListener("click", (e) => { e.stopPropagation(); const b = st.nextElementSibling; if (b && b.classList.contains("step-body")) b.classList.toggle("-open"); });
  });

  const $ = (id) => document.getElementById(id);
  if ($("reset")) $("reset").addEventListener("click", () => { if (!confirm("Сбросить весь прогресс по этому роадмапу?")) return; state = {}; save(state); paint(); });
  if ($("export")) $("export").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify({ key: KEY, at: new Date().toISOString(), state }, null, 2)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = KEY + ".json"; a.click(); URL.revokeObjectURL(a.href);
  });
  if ($("import")) $("import").addEventListener("change", (e) => {
    const f = e.target.files[0]; if (!f) return;
    f.text().then(t => { try { const d = JSON.parse(t); state = d.state || d; save(state); paint(); } catch (err) { alert("Файл не похож на сохранённый прогресс."); } });
    e.target.value = "";
  });
  if (DEADLINE && $("days")) {
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const left = Math.round((new Date(DEADLINE) - today) / 86400000);
    $("days").textContent = left > 0 ? left : (left === 0 ? "сегодня" : "—");
  }
  paint();
  const first = [...document.querySelectorAll(".layer[data-phase]")].find(l => !l.classList.contains("-complete") && !l.classList.contains("-skipped"));
  if (first) first.open = true;
})();
"""

THEME_BOOT = ('<script>(()=>{let s=null;try{s=localStorage.getItem("theme")}catch(e){}'
              'document.documentElement.dataset.theme=s||(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light")})();</script>')


def ring() -> str:
    c = 2 * 3.14159 * 12
    return (f'<svg class="ring" viewBox="0 0 30 30" aria-hidden="true"><circle class="track" cx="15" cy="15" r="12"></circle>'
            f'<circle class="fill" cx="15" cy="15" r="12" stroke-dasharray="{c:.2f}" stroke-dashoffset="{c:.2f}"></circle></svg>')


def steps_html(sec: Section, with_bodies: bool) -> str:
    out = ['<ul class="steps">']
    brk = " -break" if sec.kind == "break" else ""
    for kind, item in sec.parts:
        if kind == "text":
            if with_bodies:
                out.append(f'<li class="interlude">{item}</li>')
            continue
        st: Step = item
        more = '<span class="more">подробнее</span>' if (with_bodies and st.body) else ""
        out.append(f'<li class="step{brk}" data-step="{st.id}"><input type="checkbox" id="s-{st.id}"><span class="box"></span>'
                   f'<span class="txt">{st.title}</span>{more}</li>')
        if with_bodies and st.body:
            out.append(f'<li class="step-body">{st.body}</li>')
    out.append("</ul>")
    return "".join(out)


def phases_json(phases: list[Phase]) -> str:
    return json.dumps({str(p.n): {"total": len(p.steps), "baseline": p.baseline, "status": p.status, "hours": p.hours}
                       for p in phases}, ensure_ascii=False)


def page_shell(title: str, body: str, key: str, deadline: str, phases: list[Phase], phase_n: int | None, desc: str) -> str:
    js = (JS.replace("__KEY__", f"rm-progress-{key}")
            .replace("__DEADLINE__", json.dumps(deadline))
            .replace("__PHASES__", phases_json(phases)))
    body_attr = f' data-phase="{phase_n}"' if phase_n is not None else ""
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">{THEME_BOOT}'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">'
            f'<title>{html.escape(title)}</title><meta name="description" content="{html.escape(desc)}">'
            f'<link rel="icon" href="{FAVICON}">{FONTS}<style>{CSS}</style></head>'
            f'<body{body_attr}>{body}<script>{js}</script><script src="/theme.js?v=2"></script></body></html>')


# ---------------------------------------------------------------- главная

def render_index(track: Track, intro_html: str, phases: list[Phase], meta: dict) -> str:
    deadline = meta.get("deadline", "")
    dl_label = meta.get("deadline_label", "")
    total_steps = sum(len(p.steps) for p in phases)
    total_hours = sum(p.hours for p in phases)
    unit_l = track.unit.lower()

    cards = []
    for p in phases:
        cls = " -skipped" if p.status == "skipped" else ""
        when = f'<span class="tag -when">{html.escape(p.when)}</span>' if p.when else ""
        note = html.escape(p.note) if p.note else ""
        base = f'<span class="base">самооценка {p.baseline}%</span>' if p.baseline else ""
        blocks = [f'<div class="note">{p.analogy}</div>'] if p.analogy else []
        for sec in p.sections:
            if sec.kind in ("practice", "break") and sec.steps:
                blocks.append(f'<div><div class="steps"><div class="h">{ICONS[sec.kind]} {sec.title}</div></div>{steps_html(sec, with_bodies=False)}</div>')
        if p.criterion:
            blocks.append(f'<div class="criterion"><b>{unit_l} {track.closed}, когда</b>{p.criterion}</div>')
        blocks.append(f'<a class="open-phase" href="./{p.n}/">Открыть {track.acc} целиком →</a>')
        cards.append(
            f'<details class="layer{cls}" data-phase="{p.n}">'
            f'<summary><span class="idx">{p.n:02d}</span>'
            f'<span class="headline"><h2>{html.escape(p.title)}</h2><span class="meta"><span>{note}</span>{when}{base}</span></span>'
            f'<span class="gauge"><span class="frac">0/{len(p.steps)}</span>{ring()}</span></summary>'
            f'<div class="body">{"".join(blocks)}</div></details>')

    countdown = (f'<div class="countdown"><div class="num" id="days">—</div><div class="cap">дней {html.escape(dl_label)}</div></div>'
                 if deadline else "")
    hours_meter = (f'<div class="meter"><span class="val" id="hours-left">{total_hours:g}</span><span class="lbl">часов осталось</span></div>'
                   if total_hours else "")
    sib = " · ".join(f'<a href="{u}">{TRACKS[k].title}</a>' for k, u in SIBLINGS[track.key])

    body = f"""
<div class="wrap">
  <header class="masthead">
    <div>
      <a class="back" href="/">← Иван Архипов</a>
      <p class="eyebrow">Роадмап · {html.escape(track.unit_pl.lower())} с чекбоксами</p>
      <h1>{html.escape(track.title)}</h1>
      <p class="sub">{html.escape(track.lead)}</p>
    </div>
    {countdown}
  </header>

  <section class="summary">
    <div class="meters">
      <div class="meter"><span class="val" id="pct">0%</span><span class="lbl">пройдено</span></div>
      <div class="meter -done"><span class="val" id="steps-done">0</span><span class="lbl">шагов из <span id="steps-all">{total_steps}</span></span></div>
      {hours_meter}
      <div class="meter"><span class="val" id="layers-done">0</span><span class="lbl">{track.unit_gen} закрыто</span></div>
    </div>
    <div class="bar" data-total><span></span></div>
    <div class="tools">
      <button type="button" id="export">Скачать прогресс</button>
      <label for="import">Загрузить прогресс</label><input type="file" id="import" accept="application/json">
      <button type="button" class="danger" id="reset">Сбросить</button>
    </div>
  </section>

  <p class="section-label">{track.unit_pl} по порядку</p>
  <div class="stack">{"".join(cards)}</div>

  <details class="layer"><summary><span class="idx">▪</span><span class="headline"><h2>Про этот роадмап</h2><span class="meta">зачем, прицел, срез, календарь</span></span><span></span></summary>
    <div class="body"><div class="note">{intro_html}</div></div>
  </details>

  <footer class="section-label" style="justify-content:space-between">
    <span>Иван Архипов · Москва</span>
    <span style="text-transform:none;letter-spacing:0"><a href="https://github.com/Lazysagotku/l2code">исходники</a> · {sib} · <a href="/">визитка</a></span>
  </footer>
</div>"""
    return page_shell(f"{track.title} - роадмап", body, track.key, deadline, phases, None, track.lead)


# ---------------------------------------------------------------- страница фазы

def render_phase_page(track: Track, phases: list[Phase], p: Phase, meta: dict) -> str:
    unit_l = track.unit.lower()
    toc, secs = [], []
    for k, sec in enumerate(p.sections):
        sid = sec.kind if sec.kind != "other" else f"s{k}"
        icon = ICONS.get(sec.kind, "▪")
        title = html.escape(sec.title) if sec.title else "Раздел"
        toc.append(f'<a href="#{sid}"><span class="i">{icon}</span>{title}</a>')
        inner = steps_html(sec, with_bodies=True) if sec.kind in ("practice", "break") else f'<div class="text">{sec.html}</div>'
        secs.append(f'<section class="sec -{sec.kind}" id="{sid}"><h2><span class="i">{icon}</span>{title}</h2>{inner}</section>')

    sib = [f'<a href="../{q.n}/" class="{"-cur" if q.n == p.n else ""}" data-phase="{q.n}"><span class="n">{q.n:02d}</span>{html.escape(q.title)}</a>'
           for q in phases]
    i = [q.n for q in phases].index(p.n)
    prev_ = phases[i - 1] if i > 0 else None
    next_ = phases[i + 1] if i + 1 < len(phases) else None
    pager = ('<nav class="pager">'
             + (f'<a href="../{prev_.n}/">← {prev_.n:02d} {html.escape(prev_.title)}</a>' if prev_ else "<span></span>")
             + (f'<a class="r" href="../{next_.n}/">{next_.n:02d} {html.escape(next_.title)} →</a>' if next_ else "<span></span>")
             + "</nav>")
    note = html.escape(p.note) if p.note else ""
    when = f" · {html.escape(p.when)}" if p.when else ""

    body = f"""
<div class="layout">
  <aside class="side">
    <a class="back" href="../">← {html.escape(track.title)}</a>
    <h2>{track.icon} {html.escape(track.title)}</h2>
    <div class="prog">пройдено <span id="pct">0%</span> · <span id="steps-done">0</span>/<span id="steps-all">0</span> шагов</div>
    <div class="bar" data-total><span></span></div>
    <nav><b>В {track.loc}</b>{"".join(toc)}</nav>
    <nav class="-siblings"><b>{track.unit_pl}</b>{"".join(sib)}</nav>
  </aside>
  <main class="content">
    <div class="topbar"><b>{track.unit} {p.n}. {html.escape(p.title)}</b><span><span id="cur-done">0</span> из <span id="cur-all">{len(p.steps)}</span> шагов пройдено</span></div>
    <h1>{html.escape(p.title)}</h1>
    <p class="lead">{note}{when}</p>
    {"".join(secs)}
    <p class="src">Исходник: <a href="{GITHUB}{p.source}" target="_blank" rel="noopener">{p.source}</a></p>
    {pager}
  </main>
</div>"""
    return page_shell(f"{track.unit} {p.n}. {p.title} - {track.title}", body, track.key, meta.get("deadline", ""),
                      phases, p.n, f"{track.title}: {unit_l} {p.n}, {p.title}")


# ---------------------------------------------------------------- сборка

def build(key: str) -> None:
    track = TRACKS[key]
    intro, phases, meta = load(track)
    folder = ROOT / track.folder
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text(render_index(track, intro, phases, meta), encoding="utf-8", newline="\n")
    for p in phases:
        d = folder / str(p.n)
        d.mkdir(exist_ok=True)
        (d / "index.html").write_text(render_phase_page(track, phases, p, meta), encoding="utf-8", newline="\n")
    print(f"{track.folder}/  главная + {len(phases)} страниц, {sum(len(p.steps) for p in phases)} шагов")


if __name__ == "__main__":
    for k in (sys.argv[1:] or list(TRACKS)):
        build(k)
