# Aymantium

Static personal archive built with Python, Jinja2, and Markdown.

## Setup

```sh
python3 -m pip install -r requirements.txt
```

## Build

```sh
python3 scripts/build.py
```

## Preview

```sh
python3 -m http.server 8000 --directory dist
```

## Tests

```sh
python3 -m unittest discover -s tests -v
```

## Content

Add Markdown files under `content/`. Drafts are excluded unless `DRAFTS=1` is set.

## Environment

- `SITE_URL` — absolute site URL (default `https://aymantium.github.io`).
- `BASE_PATH` — subpath for project sites (default empty).
- `DRAFTS` — set to `1` to include drafts.

## Deployment

GitHub Actions builds and deploys on push to `main`. Enable GitHub Pages with source "GitHub Actions" in repository settings.

## Fonts

Geist Mono is self-hosted in `assets/fonts/`. License: `assets/fonts/LICENSE.txt`.
