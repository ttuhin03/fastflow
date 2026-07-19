# Fast-Flow Marketing Site

A static, no-build-step marketing/landing page for Fast-Flow — meant to be linked
from the GitHub repo page to showcase the project.

## Preview locally

```bash
cd marketing-site
python3 -m http.server 4173
# open http://localhost:4173
```

No dependencies, no bundler — just HTML, CSS and a small vanilla JS file in
`assets/`. Colors, spacing, and type scale mirror the design tokens used in
`frontend/src/styles/variables.css` so it feels like the same product.

## Structure

```
marketing-site/
├── index.html          # single-page layout (hero, features, comparison, quick start, CTA)
├── assets/
│   ├── css/tokens.css  # design tokens mirrored from the app
│   ├── css/style.css   # page styles
│   ├── js/main.js      # scroll reveal, tab switching, copy-to-clipboard
│   └── img/            # logo + screenshots pulled from docs/static/img
└── README.md
```

## Deploying

Any static host works (GitHub Pages, Netlify, Vercel, S3). For GitHub Pages,
point it at this directory (e.g. via a `gh-pages` workflow or the "Pages"
build source set to `/marketing-site` on this branch once merged).
