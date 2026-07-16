# Fast-Flow demo video (Remotion)

Remotion source for Fast-Flow's marketing videos. `FirstDemo` (`src/FirstDemo.tsx`)
is a ~30s capability demo built from reusable, prop-driven scene components in
`src/components/`:

- `TitleCard` — hook / headline / logo reveal card
- `ScreenshotShowcase` — real app screenshot with Ken Burns pan + caption
- `TerminalReplay` — typed CLI replay (pass any `TerminalLine[]`)
- `StatCallout` — headline + animated badge row
- `Outro` — logo + CTA card

Each component takes props only (no hardcoded copy), so the next video is
assembled from these blocks rather than written from scratch.

## Develop

```bash
cd videos/fastflow-demo
npm install
npm start          # opens Remotion Studio
```

## Render

```bash
npm run render      # writes out/first-demo.mp4 (1920x1080, 30fps)
```

## Assets

`public/screenshots/*.png` are real Fast-Flow UI screenshots copied from
`docs/static/img/` (dashboard, pipelines, dependencies). Brand color
(`#6366F1`) and the logo mark are taken from `frontend/public/favicon.svg`.
No stock footage, fonts, or music are used.
