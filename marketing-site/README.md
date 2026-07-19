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

Deployed to GitHub Pages automatically via `.github/workflows/pages.yml`,
which publishes this directory whenever it changes on `main`. In the repo
settings, set **Pages → Build and deployment → Source** to "GitHub Actions"
(one-time setup) and the workflow takes care of the rest.

Any other static host also works (Netlify, Vercel, S3) if you'd rather point
one of those at this directory instead.
