# Fast-Flow marketing site

Static marketing site for [Fast-Flow](https://github.com/ttuhin03/fastflow) — no build step.

## Preview locally

```bash
cd website
python3 -m http.server 4173
# open http://localhost:4173
```

## Structure

```
website/
├── index.html       # interactive marketing landing page
├── manifesto.html   # Anti-Overhead Manifesto
├── support.js       # DC runtime (loads React from CDN)
├── .nojekyll        # keep GitHub Pages from running Jekyll
└── README.md
```

## Deploy with GitHub Pages

The workflow [`.github/workflows/deploy-website.yml`](../.github/workflows/deploy-website.yml) publishes this folder on every push to `main` that touches `website/`.

One-time setup in the repo:

1. **Settings → Pages → Build and deployment → Source**: GitHub Actions
2. Merge this branch (or push `website/` to `main`)
3. Site URL: `https://ttuhin03.github.io/fastflow/`

You can also run the workflow manually via **Actions → Deploy marketing website → Run workflow**.
