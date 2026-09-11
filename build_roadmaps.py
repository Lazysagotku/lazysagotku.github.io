# -*- coding: utf-8 -*-
"""Собирает интерактивные страницы роадмапов из markdown-файлов фаз.

Источник - l2code: один файл на фазу, внутри семь блоков (аналогия, теория,
практика, сломай намеренно, задание, из жизни, вопросы). Отсюда страница
берёт всё: шаги для чекбоксов - из практики и «сломай намеренно», остальное
рендерится как есть.

Прогресс живёт в localStorage браузера. Сервера нет намеренно: страница
должна открываться без VPN и без бэкенда, это GitHub Pages.

Запуск:  python build_roadmaps.py            - все четыре направления
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
    """Одна строка без обёртки в <p>."""
    out = md(text)
    if out.startswith("<p>") and out.endswith("</p>") and out.count("<p>") == 1:
        out = out[3:-4]
    return out


# ---------------------------------------------------------------- направления

@dataclass
class Track:
    key: str            # ключ localStorage и имя папки
    title: str
    lead: str
    folder: str         # папка в портфолио
    roadmap: str        # файл-оглавление в l2code
    phase_glob: str     # файлы фаз; пусто - фазы внутри roadmap
    unit: str           # «Слой» или «Фаза»
    unit_pl: str = ""   # «Слои» / «Фазы»
    unit_gen: str = ""  # «слоёв» / «фаз»
    deadline: str = ""  # ISO-дата для отсчёта, пусто - без отсчёта
    deadline_label: str = ""
    accent_note: str = ""


TRACKS = {
    "infra": Track(
        key="infra", title="Стенд с нуля",
        lead="Голый сервер, на который слоями ставится всё: Linux, nginx, CI/CD, мониторинг, PostgreSQL, релизный процесс, Kubernetes. Каждый слой проверяется руками и ломается намеренно.",
        folder="roadmap-infra", roadmap="Roadmap_Infra_Sept2026.md",
        phase_glob="Infra_Layer*.md", unit="Слой", unit_pl="Слои", unit_gen="слоёв",
        deadline="2026-09-16", deadline_label="до собеседования в Сбере",
    ),
    "python": Track(
        key="python", title="Python Backend",
        lead="Бэкенд-паттерны и идиомы поверх живого языка. Практика на трекере и разведчике - они написаны Claude и в опыт не идут, но как полигон лучше учебного проекта.",
        folder="roadmap-python", roadmap="PythonBackend_Roadmap.md",
        phase_glob="Python_Phase*.md", unit="Фаза", unit_pl="Фазы", unit_gen="фаз",
    ),
    "ai": Track(
        key="ai", title="AI Product Engineer",
        lead="Встраивание готовых LLM в продукт: инженерия вокруг модели, а не внутри неё. Фазы 1 и 2 нужны сейчас - под вакансии, где владение AI стоит в требованиях.",
        folder="roadmap-ai", roadmap="AIEngineer_Roadmap.md",
        phase_glob="AI_Phase*.md", unit="Фаза", unit_pl="Фазы", unit_gen="фаз",
    ),
    "csharp": Track(
        key="csharp", title="C# Backend",
        lead="Фоновый трек с 1 сентября. Закрывает вопрос «читаете ли код разработчиков» и доводит Life Notes. Фазы 1-3 завершены, дальше по мере роста.",
        folder="roadmap", roadmap="CSharp_Roadmap_Software.md",
        phase_glob="", unit="Фаза", unit_pl="Фазы", unit_gen="фаз",
    ),
}


# ---------------------------------------------------------------- разбор фазы

SECTION_KINDS = {
    "🎭": "analogy", "📖": "theory", "🔧": "practice", "💥": "break",
    "✅": "task", "🌍": "life", "❓": "questions",
}
SECTION_TITLES = {
    "analogy": "Аналогия", "theory": "Теория", "practice": "Практика",
    "break": "Сломай намеренно", "task": "Задание", "life": "Из жизни",
    "questions": "Вопросы с ответами", "other": "",
}

HEAD_RE = re.compile(r"^# (\S+) (?:Слой|Фаза) (\d+)\. (.+?)(?: \((.+)\))?\s*$")
STEP_RE = re.compile(r"^(\*{0,2})(\d+)\.\*{0,2}\s+(.+?)\s*$")


@dataclass
class Step:
    id: str
    title: str      # html
    body: str       # html, может быть пустым


@dataclass
class Section:
    kind: str
    title: str
    html: str = ""
    steps: list[Step] = field(default_factory=list)
    # для practice/break: чередование текстовых кусков и шагов, чтобы
    # сохранить порядок «преамбула - шаги - подразделы»
    parts: list[tuple[str, object]] = field(default_factory=list)


@dataclass
class Phase:
    n: int
    emoji: str
    title: str
    note: str           # «день 1, 2 часа» или «завершена»
    source: str         # имя файла в l2code
    sections: list[Section]

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


def _split_top(lines: list[str], marker: str) -> list[tuple[str, list[str]]]:
    """Режет по строкам, начинающимся с marker, игнорируя code-блоки."""
    chunks: list[tuple[str, list[str]]] = []
    head = ""
    body: list[str] = []
    in_code = False
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


def _parse_steps(section_kind: str, phase_n: int, body: list[str]) -> Section:
    """Практика и «сломай»: нумерованные пункты становятся шагами."""
    sec = Section(kind=section_kind, title=SECTION_TITLES[section_kind])
    buf: list[str] = []
    current: Step | None = None
    idx = 0
    in_code = False

    def flush_text():
        text = "\n".join(buf).strip()
        if text:
            sec.parts.append(("text", md(text)))
        buf.clear()

    def flush_step():
        nonlocal current
        if current is not None:
            current.body = md("\n".join(buf).strip()) if any(l.strip() for l in buf) else ""
            sec.steps.append(current)
            sec.parts.append(("step", current))
            current = None
        buf.clear()

    for line in body:
        if line.startswith("```"):
            in_code = not in_code
        m = None if in_code else STEP_RE.match(line)
        is_sub = (not in_code) and line.startswith("### ")
        if m:
            flush_step() if current else flush_text()
            idx += 1
            opened, rest = m.group(1), m.group(3).strip()
            # Три формата в исходниках: «**N. всё жирное:**», «**N. жирное** хвост»
            # и «N. **жирное:** хвост». Возвращаем открывающие звёздочки, если они
            # стояли перед номером, дальше markdown закроет жирное сам.
            title = ("**" + rest) if opened else rest
            # Целиком жирный заголовок - снять обёртку, в чекбоксе жирность лишняя
            if title.startswith("**") and title.endswith("**") and title.count("**") == 2:
                title = title[2:-2]
            # Двоеточие внутри жирного и в конце - убрать, это разделитель, а не текст
            title = title.replace(":**", "**").rstrip(":").strip()
            current = Step(id=f"{phase_n}-{section_kind}-{idx}", title=md_inline(title), body="")
        elif is_sub:
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
    # убрать служебный blockquote с навигацией сразу под заголовком
    rest = lines[1:]
    while rest and (not rest[0].strip() or rest[0].startswith(">")):
        rest.pop(0)

    sections: list[Section] = []
    for head, body in _split_top(rest, "## "):
        # хвостовые разделители между фазами - не содержимое
        while body and body[-1].strip() in ("", "---"):
            body.pop()
        if not head and not body:
            continue
        kind = _kind_of(head) if head else "other"
        if kind in ("practice", "break"):
            sections.append(_parse_steps(kind, n, body))
        else:
            clean = re.sub(r"^\S+\s+", "", head) if head else ""
            sec = Section(kind=kind, title=SECTION_TITLES.get(kind) or clean)
            sec.html = md("\n".join(body))
            if head and kind == "other":
                sec.title = clean
            sections.append(sec)
    return Phase(n=n, emoji=emoji, title=title, note=note, source=source, sections=sections)


def load_phases(track: Track) -> tuple[str, list[Phase]]:
    """Возвращает (intro_html, phases)."""
    roadmap_text = (L2CODE / track.roadmap).read_text(encoding="utf-8")
    phases: list[Phase] = []

    if track.phase_glob:
        for path in sorted(L2CODE.glob(track.phase_glob)):
            ph = parse_phase(path.read_text(encoding="utf-8"), path.name)
            if ph:
                phases.append(ph)
        phases.sort(key=lambda p: p.n)
        intro_src = roadmap_text.split("\n# 📂", 1)[0]
    else:
        # фазы лежат внутри самого роадмапа - режем по заголовкам первого уровня
        lines = roadmap_text.split("\n")
        starts = [i for i, l in enumerate(lines) if HEAD_RE.match(l)]
        tail_markers = [i for i, l in enumerate(lines) if l.startswith("# 📅") or l.startswith("# 🛠")]
        end = tail_markers[0] if tail_markers else len(lines)
        for k, s in enumerate(starts):
            e = starts[k + 1] if k + 1 < len(starts) else end
            ph = parse_phase("\n".join(lines[s:e]), track.roadmap)
            if ph:
                phases.append(ph)
        intro_src = "\n".join(lines[:starts[0]]) if starts else roadmap_text

    # вступление: без первого заголовка и без служебных blockquote
    intro_lines = [l for l in intro_src.split("\n")[1:]]
    intro_html = md("\n".join(intro_lines))
    return intro_html, phases


# ---------------------------------------------------------------- рендер

CSS = """
  :root {
    --bg: oklch(1 0 0); --surface: oklch(0.97 0.003 40); --raised: oklch(1 0 0);
    --dark: oklch(0.23 0.012 40); --on-dark: #fff;
    --ink: oklch(0.24 0.015 40); --muted: oklch(0.45 0.015 40);
    --accent: oklch(0.58 0.15 42); --accent-deep: oklch(0.46 0.125 42); --accent-soft: oklch(0.96 0.02 42);
    --done: oklch(0.55 0.12 145); --done-soft: oklch(0.94 0.05 145);
    --skip: oklch(0.55 0.13 25); --skip-soft: oklch(0.95 0.04 25);
    --line: oklch(0.9 0.004 40);
    --display: "Bitter", Georgia, serif;
    --body: "Golos Text", "Segoe UI", system-ui, sans-serif;
    --mono: ui-monospace, "Cascadia Mono", Consolas, monospace;
    --r: 14px; --ease: cubic-bezier(0.16, 1, 0.3, 1);
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink); font-family: var(--body); font-size: 1.04rem; line-height: 1.62; -webkit-font-smoothing: antialiased; }
  h1, h2, h3, h4 { font-family: var(--display); text-wrap: balance; margin: 0; }
  p { margin: 0; text-wrap: pretty; }
  a { color: var(--accent-deep); text-underline-offset: 3px; }
  :focus-visible { outline: 3px solid var(--accent-deep); outline-offset: 3px; border-radius: 4px; }
  .wrap { max-width: 58rem; margin-inline: auto; padding-inline: clamp(1.25rem, 5vw, 3rem); }
  code { font-family: var(--mono); font-size: 0.9em; background: var(--surface); padding: 0.1em 0.35em; border-radius: 5px; }
  pre { background: var(--dark); color: var(--on-dark); padding: 0.9rem 1.1rem; border-radius: 10px; overflow-x: auto; font-size: 0.88rem; line-height: 1.5; margin: 0.7rem 0; }
  pre code { background: none; padding: 0; color: inherit; font-size: inherit; }
  table { width: 100%; border-collapse: collapse; font-size: 0.93rem; margin: 0.7rem 0; display: block; overflow-x: auto; }
  th, td { text-align: left; padding: 0.45rem 0.6rem; border-bottom: 1px solid var(--line); vertical-align: top; }
  th { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
  blockquote { margin: 0.6rem 0; padding: 0.6rem 1rem; border-left: 3px solid var(--accent); background: var(--accent-soft); border-radius: 0 10px 10px 0; }
  blockquote p + p { margin-top: 0.5rem; }
  ul, ol { padding-left: 1.3rem; margin: 0.5rem 0; }
  li + li { margin-top: 0.25rem; }
  hr { border: 0; border-top: 1px solid var(--line); margin: 1.2rem 0; }

  header { padding-block: clamp(2.5rem, 7vh, 4rem) 1.5rem; }
  .back { font-size: 0.95rem; font-weight: 500; text-decoration: none; }
  .back:hover { text-decoration: underline; }
  .epigraph { margin-top: 0.9rem; font-family: var(--display); font-style: italic; font-size: 0.98rem; color: var(--muted); }
  h1 { font-size: clamp(2.1rem, 5.5vw, 3.2rem); font-weight: 800; letter-spacing: -0.01em; margin-top: 0.8rem; }
  .lead { margin-top: 0.8rem; color: var(--muted); max-width: 44em; font-size: 1.08rem; }

  .total { margin-top: 2rem; background: var(--dark); color: var(--on-dark); border-radius: var(--r); padding: 1.4rem 1.6rem 1.5rem; }
  .total .row { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline; gap: 0.5rem 1.5rem; }
  .total .label { font-weight: 600; }
  .total .num { font-family: var(--display); font-weight: 800; font-size: 2rem; color: oklch(0.75 0.13 55); font-variant-numeric: tabular-nums; }
  .total .track { position: relative; height: 10px; border-radius: 999px; background: oklch(0.34 0.015 40); margin-top: 0.8rem; overflow: hidden; }
  .total .fill { height: 100%; width: 0; border-radius: 999px; background: linear-gradient(90deg, var(--accent), oklch(0.74 0.15 60)); transition: width 0.7s var(--ease); }
  .total .fill.full { background: var(--done); }
  .stats { display: flex; flex-wrap: wrap; gap: 0.4rem 1.6rem; margin-top: 0.8rem; font-size: 0.92rem; color: oklch(0.72 0.015 40); }
  .stats b { color: var(--on-dark); font-variant-numeric: tabular-nums; }

  .next { margin-top: 1.4rem; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r); padding: 1.1rem 1.3rem; }
  .next h2 { font-size: 1.1rem; font-weight: 700; margin-bottom: 0.5rem; }
  .next ol { margin: 0; padding-left: 1.2rem; }
  .next li { font-size: 0.95rem; }
  .next li span { color: var(--muted); font-size: 0.85rem; }
  .next .empty { color: var(--muted); }

  .tools { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 1rem; }
  .tools button, .tools label { font: inherit; font-size: 0.85rem; padding: 0.35rem 0.9rem; border: 1px solid var(--line); border-radius: 999px; background: var(--raised); color: inherit; cursor: pointer; }
  .tools button:hover, .tools label:hover { border-color: var(--accent); }
  .tools .danger { margin-left: auto; opacity: 0.7; }
  .tools .danger:hover { opacity: 1; border-color: var(--skip); color: var(--skip); }
  .tools input[type=file] { display: none; }

  main { padding-block: clamp(2rem, 5vh, 3.5rem); }
  .section-title { font-size: clamp(1.4rem, 3vw, 1.8rem); font-weight: 700; margin-bottom: 1rem; }
  .section-title em { font-style: normal; color: var(--accent-deep); }

  details.intro { border: 1px solid var(--line); border-radius: var(--r); padding: 0.9rem 1.3rem; margin-bottom: 2rem; }
  details.intro summary { cursor: pointer; font-family: var(--display); font-weight: 700; font-size: 1.05rem; }
  details.intro .body { margin-top: 0.8rem; font-size: 0.97rem; }
  details.intro .body h2 { font-size: 1.2rem; margin-top: 1.3rem; }
  details.intro .body h3 { font-size: 1.05rem; margin-top: 1rem; }

  .phase { border: 1px solid var(--line); border-left: 4px solid var(--line); border-radius: var(--r); background: var(--raised); margin-bottom: 0.9rem; transition: border-color 0.3s; }
  .phase.active { border-left-color: var(--accent); }
  .phase.complete { border-left-color: var(--done); background: var(--surface); }
  .phase.status-done { border-left-color: var(--done); }
  .phase.status-skipped { border-left-color: var(--line); opacity: 0.75; }
  .phase > summary { list-style: none; cursor: pointer; padding: 1rem 1.3rem; display: grid; grid-template-columns: 2.6rem 1fr auto; gap: 0.9rem; align-items: center; }
  .phase > summary::-webkit-details-marker { display: none; }
  .phase .n { font-family: var(--display); font-weight: 800; font-size: 1.5rem; color: var(--muted); font-variant-numeric: tabular-nums; text-align: center; }
  .phase.active .n { color: var(--accent-deep); }
  .phase.complete .n, .phase.status-done .n { color: var(--done); }
  .phase h2 { font-size: 1.15rem; font-weight: 700; }
  .phase .meta { font-size: 0.85rem; color: var(--muted); margin-top: 0.15rem; display: flex; flex-wrap: wrap; gap: 0.3rem 0.8rem; }
  .phase .tag { font-size: 0.72rem; letter-spacing: 0.06em; text-transform: uppercase; padding: 0.1rem 0.5rem; border-radius: 999px; border: 1px solid var(--accent); color: var(--accent-deep); background: var(--accent-soft); }
  .gauge { display: flex; align-items: center; gap: 0.6rem; }
  .gauge .frac { font-family: var(--mono); font-size: 0.82rem; color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .ring { width: 32px; height: 32px; transform: rotate(-90deg); flex: none; }
  .ring circle { fill: none; stroke-width: 4; }
  .ring .trk { stroke: var(--line); }
  .ring .fil { stroke: var(--accent); stroke-linecap: round; transition: stroke-dashoffset 0.6s var(--ease); }
  .phase.complete .ring .fil { stroke: var(--done); }

  .phase .content { padding: 0 1.3rem 1.3rem; }
  .block { margin-top: 1.1rem; }
  .block > h3 { font-size: 0.82rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; }
  .block > h3 .i { font-size: 1rem; }
  .block.analogy .text { background: var(--surface); border-radius: 10px; padding: 0.8rem 1rem; }
  .block.theory > details > summary { cursor: pointer; color: var(--accent-deep); font-weight: 500; font-size: 0.95rem; }
  .block.theory .text { margin-top: 0.6rem; }
  .block .text h3 { font-size: 1.05rem; margin-top: 1.1rem; margin-bottom: 0.3rem; }
  .block .text h4 { font-size: 0.98rem; margin-top: 0.9rem; }
  .block .text p + p { margin-top: 0.5rem; }
  .block .text > p:first-child { margin-top: 0; }

  .steps { list-style: none; margin: 0; padding: 0; }
  .step { border: 1px solid var(--line); border-radius: 10px; margin-bottom: 0.45rem; background: var(--raised); }
  .step.done { background: var(--done-soft); border-color: var(--done); }
  .step .head { display: flex; gap: 0.7rem; align-items: flex-start; padding: 0.55rem 0.75rem; cursor: pointer; }
  .step input { position: absolute; opacity: 0; width: 0; height: 0; }
  .box { flex: none; width: 1.1rem; height: 1.1rem; margin-top: 0.2rem; border: 1.5px solid var(--muted); border-radius: 4px; background: var(--raised); position: relative; transition: background 0.2s, border-color 0.2s; }
  .box::after { content: ""; position: absolute; left: 0.32rem; top: 0.08rem; width: 0.3rem; height: 0.6rem; border: solid var(--on-dark); border-width: 0 2px 2px 0; transform: rotate(45deg) scale(0); transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1); }
  .step.done .box { background: var(--done); border-color: var(--done); }
  .step.done .box::after { transform: rotate(45deg) scale(1); }
  .step .t { flex: 1; font-size: 0.97rem; }
  .step.done .t { color: var(--muted); text-decoration: line-through; text-decoration-thickness: 1px; }
  .step .more { flex: none; font-size: 0.8rem; color: var(--muted); padding-top: 0.2rem; }
  .step .body { display: none; padding: 0 0.75rem 0.7rem 2.55rem; font-size: 0.93rem; }
  .step.open .body { display: block; }
  .step .body pre { font-size: 0.84rem; }
  .brk .step .head::before { content: "сломать"; flex: none; font-family: var(--mono); font-size: 0.66rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--skip); border: 1px solid currentColor; border-radius: 4px; padding: 0.05rem 0.35rem; margin-top: 0.25rem; order: 2; }
  .brk .step .t { order: 3; }
  .brk .step .more { order: 4; }
  .brk .step .box { order: 1; }
  .interlude { font-size: 0.93rem; margin: 0.6rem 0; }

  .block.task .text { background: var(--surface); border: 1px dashed var(--line); border-radius: 10px; padding: 0.8rem 1rem; font-size: 0.95rem; }
  .block.questions .text > p > strong { display: block; margin-top: 0.9rem; font-family: var(--display); font-size: 1rem; }
  .block.questions .text blockquote { margin-top: 0.3rem; }
  .src { margin-top: 1rem; font-size: 0.82rem; color: var(--muted); }

  footer { border-top: 1px solid var(--line); padding-block: 1.75rem; margin-top: 2rem; }
  footer .wrap { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 0.75rem 2rem; font-size: 0.92rem; color: var(--muted); }
  @media (max-width: 600px) {
    .phase > summary { grid-template-columns: 2rem 1fr; }
    .gauge { grid-column: 1 / -1; padding-left: 2.9rem; }
    .phase .content { padding-inline: 1rem; }
    .step .body { padding-left: 1rem; }
  }
  @media (prefers-reduced-motion: reduce) { .total .fill, .ring .fil, .box::after { transition: none; } }
"""

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E"
           "%3Crect width='64' height='64' rx='12' fill='%23b0561f'/%3E%3Ctext x='32' y='43' "
           "font-family='Georgia,serif' font-weight='700' font-size='30' fill='white' "
           "text-anchor='middle'%3EИА%3C/text%3E%3C/svg%3E")

OTHER_LINKS = {
    "infra": [("/roadmap/", "C#"), ("/roadmap-python/", "Python"), ("/roadmap-ai/", "ИИ")],
    "python": [("/roadmap/", "C#"), ("/roadmap-ai/", "ИИ"), ("/roadmap-infra/", "Стенд")],
    "ai": [("/roadmap/", "C#"), ("/roadmap-python/", "Python"), ("/roadmap-infra/", "Стенд")],
    "csharp": [("/roadmap-python/", "Python"), ("/roadmap-ai/", "ИИ"), ("/roadmap-infra/", "Стенд")],
}


def ring(pct: float = 0) -> str:
    r, c = 13, 2 * 3.14159 * 13
    return (f'<svg class="ring" viewBox="0 0 32 32" aria-hidden="true">'
            f'<circle class="trk" cx="16" cy="16" r="{r}"></circle>'
            f'<circle class="fil" cx="16" cy="16" r="{r}" stroke-dasharray="{c:.2f}" '
            f'stroke-dashoffset="{c * (1 - pct):.2f}"></circle></svg>')


def render_steps_section(sec: Section, brk: bool) -> str:
    out = []
    for kind, item in sec.parts:
        if kind == "text":
            out.append(f'<div class="interlude">{item}</div>')
        else:
            st: Step = item
            has_body = bool(st.body)
            more = '<span class="more">подробнее</span>' if has_body else ""
            out.append(
                f'<li class="step" data-step="{st.id}">'
                f'<label class="head"><input type="checkbox" id="s-{st.id}"><span class="box"></span>'
                f'<span class="t">{st.title}</span>{more}</label>'
                + (f'<div class="body">{st.body}</div>' if has_body else "")
                + '</li>'
            )
    # шаги оборачиваем в список, текстовые вставки остаются как есть между ними
    html_parts = []
    in_list = False
    for piece in out:
        if piece.startswith('<li'):
            if not in_list:
                html_parts.append('<ul class="steps">'); in_list = True
            html_parts.append(piece)
        else:
            if in_list:
                html_parts.append('</ul>'); in_list = False
            html_parts.append(piece)
    if in_list:
        html_parts.append('</ul>')
    return "".join(html_parts)


ICONS = {"analogy": "🎭", "theory": "📖", "practice": "🔧", "break": "💥",
         "task": "✅", "life": "🌍", "questions": "❓", "other": "•"}


def render_phase(ph: Phase, unit: str) -> str:
    total = len(ph.steps)
    meta = [html.escape(ph.note)] if ph.note else []
    status_cls = f" status-{ph.status}" if ph.status else ""
    blocks = []
    for sec in ph.sections:
        icon = ICONS.get(sec.kind, "•")
        title = html.escape(sec.title) if sec.title else ""
        if sec.kind in ("practice", "break"):
            body = render_steps_section(sec, brk=(sec.kind == "break"))
            cls = "brk" if sec.kind == "break" else ""
            blocks.append(f'<div class="block {sec.kind} {cls}"><h3><span class="i">{icon}</span>{title}</h3>{body}</div>')
        elif sec.kind == "theory":
            blocks.append(f'<div class="block theory"><h3><span class="i">{icon}</span>{title}</h3>'
                          f'<details><summary>Развернуть теорию</summary><div class="text">{sec.html}</div></details></div>')
        else:
            head = f'<h3><span class="i">{icon}</span>{title}</h3>' if title else ""
            blocks.append(f'<div class="block {sec.kind}">{head}<div class="text">{sec.html}</div></div>')
    src = f'<p class="src">Исходник: <a href="{GITHUB}{ph.source}" target="_blank" rel="noopener">{ph.source}</a></p>'
    return (
        f'<details class="phase{status_cls}" data-phase="{ph.n}" data-total="{total}">'
        f'<summary><span class="n">{ph.n:02d}</span>'
        f'<span><h2>{html.escape(ph.title)}</h2><span class="meta">{" · ".join(meta)}</span></span>'
        f'<span class="gauge"><span class="frac">0/{total}</span>{ring(0)}</span></summary>'
        f'<div class="content">{"".join(blocks)}{src}</div></details>'
    )


def render_page(track: Track, intro_html: str, phases: list[Phase]) -> str:
    total_steps = sum(len(p.steps) for p in phases)
    links = " · ".join(f'<a href="{u}">{t}</a>' for u, t in OTHER_LINKS[track.key])
    deadline_js = json.dumps(track.deadline)
    phases_html = "".join(render_phase(p, track.unit) for p in phases)
    title = f"{track.title} - роадмап Ивана Архипова"
    lead = html.escape(track.lead)

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<script>
  (() => {{
    let saved = null;
    try {{ saved = localStorage.getItem("theme"); }} catch (e) {{}}
    document.documentElement.dataset.theme = saved
      || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }})();
</script>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{html.escape(title)}</title>
<meta name="description" content="{lead}">
<link rel="icon" href="{FAVICON}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bitter:wght@600;700;800&family=Golos+Text:wght@400;500;600&display=swap" rel="stylesheet">
<style>{CSS}</style>
<link rel="stylesheet" href="/theme.css?v=2">
</head>
<body>

<header>
  <div class="wrap">
    <a class="back" href="/">← Иван Архипов</a>
    <p class="epigraph">Не забывай, кто тебя отправил, и помни, что ты можешь доказать.</p>
    <h1>{html.escape(track.title)}</h1>
    <p class="lead">{lead}</p>

    <div class="total">
      <div class="row"><span class="label">Пройдено</span><span class="num" id="pct">0%</span></div>
      <div class="track"><div class="fill" id="fill"></div></div>
      <div class="stats">
        <span>шагов <b id="done">0</b> из <b>{total_steps}</b></span>
        <span>{track.unit_gen} закрыто <b id="phasesDone">0</b> из <b>{len(phases)}</b></span>
        <span id="deadline" hidden>{html.escape(track.deadline_label)}: <b id="days"></b></span>
      </div>
    </div>

    <div class="next">
      <h2>Следующие шаги</h2>
      <ol id="next"></ol>
    </div>

    <div class="tools">
      <button type="button" id="exportBtn">Скачать прогресс</button>
      <label for="importFile">Загрузить прогресс</label>
      <input type="file" id="importFile" accept="application/json">
      <button type="button" id="expandAll">Раскрыть всё</button>
      <button type="button" class="danger" id="resetBtn">Сбросить</button>
    </div>
  </div>
</header>

<main>
  <div class="wrap">
    <details class="intro">
      <summary>Про этот роадмап: зачем, прицел, срез, календарь</summary>
      <div class="body">{intro_html}</div>
    </details>

    <h2 class="section-title">{track.unit_pl} <em>по порядку</em></h2>
    <div id="phases">{phases_html}</div>
  </div>
</main>

<footer>
  <div class="wrap">
    <span>Иван Архипов · Москва</span>
    <span><a href="https://github.com/Lazysagotku/l2code">Курс на GitHub</a> · {links} · <a href="/">визитка</a></span>
  </div>
</footer>

<script>
(() => {{
  const KEY = "rm-progress-{track.key}";
  const DEADLINE = {deadline_js};
  const load = () => {{ try {{ return JSON.parse(localStorage.getItem(KEY)) || {{}}; }} catch (e) {{ return {{}}; }} }};
  const save = (s) => {{ try {{ localStorage.setItem(KEY, JSON.stringify(s)); }} catch (e) {{}} }};
  let state = load();

  const phases = [...document.querySelectorAll(".phase")];
  const allSteps = [...document.querySelectorAll(".step")];
  const C = 2 * Math.PI * 13;

  function paint() {{
    let done = 0, phasesDone = 0;
    phases.forEach(ph => {{
      const steps = [...ph.querySelectorAll(".step")];
      let d = 0;
      steps.forEach(st => {{
        const on = !!state[st.dataset.step];
        st.classList.toggle("done", on);
        const box = st.querySelector("input"); if (box) box.checked = on;
        if (on) d++;
      }});
      done += d;
      const total = steps.length;
      const p = total ? d / total : 0;
      if (total && p === 1) phasesDone++;
      ph.classList.toggle("complete", total > 0 && p === 1);
      ph.classList.toggle("active", p > 0 && p < 1);
      ph.querySelector(".frac").textContent = d + "/" + total;
      ph.querySelector(".ring .fil").setAttribute("stroke-dashoffset", (C * (1 - p)).toFixed(2));
    }});
    const total = allSteps.length;
    const pct = total ? Math.round(done / total * 100) : 0;
    document.getElementById("pct").textContent = pct + "%";
    document.getElementById("done").textContent = done;
    document.getElementById("phasesDone").textContent = phasesDone;
    const fill = document.getElementById("fill");
    fill.style.width = pct + "%";
    fill.classList.toggle("full", pct === 100);

    const next = allSteps.filter(st => !state[st.dataset.step]).slice(0, 5);
    const ol = document.getElementById("next");
    ol.innerHTML = next.length
      ? next.map(st => {{
          const ph = st.closest(".phase");
          const t = st.querySelector(".t").textContent;
          const name = ph.querySelector("h2").textContent;
          return `<li>${{t}} <span>· ${{ph.dataset.phase}}. ${{name}}</span></li>`;
        }}).join("")
      : '<li class="empty">Всё пройдено.</li>';
  }}

  allSteps.forEach(st => {{
    const box = st.querySelector("input");
    box.addEventListener("change", () => {{
      if (box.checked) state[st.dataset.step] = 1; else delete state[st.dataset.step];
      save(state); paint();
    }});
    const more = st.querySelector(".more");
    if (more) more.addEventListener("click", (e) => {{ e.preventDefault(); st.classList.toggle("open"); }});
  }});

  document.getElementById("expandAll").addEventListener("click", () => {{
    const any = phases.some(p => !p.open);
    phases.forEach(p => p.open = any);
  }});
  document.getElementById("resetBtn").addEventListener("click", () => {{
    if (!confirm("Сбросить весь прогресс по этому роадмапу?")) return;
    state = {{}}; save(state); paint();
  }});
  document.getElementById("exportBtn").addEventListener("click", () => {{
    const blob = new Blob([JSON.stringify({{ key: KEY, at: new Date().toISOString(), state }}, null, 2)], {{ type: "application/json" }});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = KEY + ".json"; a.click();
    URL.revokeObjectURL(a.href);
  }});
  document.getElementById("importFile").addEventListener("change", (e) => {{
    const f = e.target.files[0]; if (!f) return;
    f.text().then(txt => {{
      try {{ const d = JSON.parse(txt); state = d.state || d; save(state); paint(); }}
      catch (err) {{ alert("Файл не похож на сохранённый прогресс."); }}
    }});
    e.target.value = "";
  }});

  if (DEADLINE) {{
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const left = Math.round((new Date(DEADLINE) - today) / 86400000);
    if (left >= 0) {{
      document.getElementById("days").textContent = left === 0 ? "сегодня" : left + (left === 1 ? " день" : left < 5 ? " дня" : " дней");
      document.getElementById("deadline").hidden = false;
    }}
  }}

  paint();
  // первая незакрытая фаза раскрыта, чтобы страница открывалась на рабочем месте
  const first = phases.find(p => !p.classList.contains("complete") && !p.classList.contains("status-done") && !p.classList.contains("status-skipped"));
  if (first) first.open = true;
}})();
</script>
<script src="/theme.js?v=2"></script>
</body>
</html>
"""


def build(key: str) -> None:
    track = TRACKS[key]
    intro, phases = load_phases(track)
    out = ROOT / track.folder / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_page(track, intro, phases), encoding="utf-8", newline="\n")
    steps = sum(len(p.steps) for p in phases)
    print(f"{track.folder}/index.html  {len(phases)} {track.unit_gen}, {steps} шагов, {out.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    keys = sys.argv[1:] or list(TRACKS)
    for k in keys:
        build(k)
