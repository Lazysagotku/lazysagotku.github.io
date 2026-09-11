# lazysagotku.github.io

Personal card site of Ivan Arkhipov - developer with 7+ years in corporate systems (finance and government sector, Moscow).

Static, single page, no build step: `index.html` with inline CSS, two Google Fonts (Bitter + Golos Text), zero JavaScript.

## Deploy (GitHub Pages)

1. Create a **public** repository named exactly `lazysagotku.github.io` on GitHub.
2. From this folder:

```bash
git init
git add index.html README.md
git commit -m "Personal card site"
git branch -M main
git remote add origin https://github.com/Lazysagotku/lazysagotku.github.io.git
git push -u origin main
```

3. The site goes live at **https://lazysagotku.github.io** within a couple of minutes (Settings → Pages should show "Deploying from branch main" automatically for a repo with this name).

`PRODUCT.md` is a design context file for future edits with the impeccable skill; it does not affect the site and does not have to be committed.

## Editing

All content lives in `index.html`. Facts are sourced from `career-notes/Work_Experience.md` in the private workspace - keep the site consistent with it.

## Роадмапы

Страницы `roadmap*/index.html` **не редактируются руками** - они собираются из файлов фаз в `../l2code/`:

```
python build_roadmaps.py          # все четыре
python build_roadmaps.py infra    # одно направление
```

Источник правды - markdown в l2code (`Infra_Layer*.md`, `Python_Phase*.md`, `AI_Phase*.md`, `CSharp_Roadmap_Software.md`). Чекбоксы берутся из нумерованных пунктов в блоках «Практика» и «Сломай намеренно». Прогресс живёт в localStorage браузера, кнопки «Скачать / Загрузить прогресс» переносят его между устройствами файлом.
