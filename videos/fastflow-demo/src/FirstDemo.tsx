import React from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { TitleCard } from "./components/TitleCard";
import { InteractiveShowcase } from "./components/InteractiveShowcase";
import { TerminalReplay, TerminalLine } from "./components/TerminalReplay";
import { StatCallout } from "./components/StatCallout";
import { Outro } from "./components/Outro";
import { theme } from "./theme";

// Scene timing (fps = 30). Kept tight per the "pacing, no dead air" lens:
// every beat cuts right after it lands, nothing lingers past its point.
// Interactive shots get a bit more room than a static screenshot would
// (cursor move + click + crossfade needs to read clearly before the cut).
const HOOK = { from: 0, duration: 75 };
const REVEAL = { from: 75, duration: 60 };
const SHOT_DASHBOARD = { from: 135, duration: 150 };
const SHOT_PIPELINES = { from: 285, duration: 150 };
const SHOT_DEPENDENCIES = { from: 435, duration: 150 };
const TERMINAL = { from: 585, duration: 150 };
const STATS = { from: 735, duration: 120 };
const OUTRO = { from: 855, duration: 120 };

export const TOTAL_DURATION = OUTRO.from + OUTRO.duration; // 885 frames = 29.5s @ 30fps

// Click coordinates captured against the real, current frontend by
// capture.mjs (see videos/fastflow-demo/click-points.json for the raw
// output) -- these are actual pixel positions of the elements clicked.
const CLICK_POINTS = {
  dashboardHover: { x: 1210.5, y: 450.5 },
  pipelinesRowClick: { x: 421, y: 419 },
  dependenciesExpand: { x: 940, y: 403 },
};

const terminalLines: TerminalLine[] = [
  { text: "$ git push origin main", revealAt: 20, prompt: true, color: theme.white },
  { text: "→ fastflow: syncing pipeline-nightly-etl", revealAt: 48, color: theme.gray },
  {
    text: "→ running in isolated container (uv sync, 0 image builds)",
    revealAt: 76,
    color: theme.gray,
  },
  {
    text: "✓ pipeline-nightly-etl finished in 4.2s",
    revealAt: 106,
    color: theme.green,
  },
];

export const FirstDemo: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: theme.bg }}>
      <Sequence from={HOOK.from} durationInFrames={HOOK.duration}>
        <TitleCard line="Airflow is heavy. CI/CD wasn't built for this." />
      </Sequence>

      <Sequence from={REVEAL.from} durationInFrames={REVEAL.duration}>
        <TitleCard line="Fast-Flow" subLine="git push. It runs." showLogo />
      </Sequence>

      <Sequence from={SHOT_DASHBOARD.from} durationInFrames={SHOT_DASHBOARD.duration}>
        <InteractiveShowcase
          before="screenshots/dashboard.png"
          after="screenshots/dashboard-hover.png"
          clickPoint={CLICK_POINTS.dashboardHover}
          actionLabel="Hover a day"
          caption="Live overview, run history, metrics heatmap"
        />
      </Sequence>

      <Sequence from={SHOT_PIPELINES.from} durationInFrames={SHOT_PIPELINES.duration}>
        <InteractiveShowcase
          before="screenshots/pipelines-list.png"
          after="screenshots/pipeline-detail.png"
          clickPoint={CLICK_POINTS.pipelinesRowClick}
          actionLabel="Open pipeline"
          caption="One Python script per pipeline — no DAG required"
        />
      </Sequence>

      <Sequence from={SHOT_DEPENDENCIES.from} durationInFrames={SHOT_DEPENDENCIES.duration}>
        <InteractiveShowcase
          before="screenshots/dependencies-collapsed.png"
          after="screenshots/dependencies-expanded.png"
          clickPoint={CLICK_POINTS.dependenciesExpand}
          actionLabel="Expand"
          caption="Built-in dependency & CVE checks on every run"
        />
      </Sequence>

      <Sequence from={TERMINAL.from} durationInFrames={TERMINAL.duration}>
        <TerminalReplay lines={terminalLines} />
      </Sequence>

      <Sequence from={STATS.from} durationInFrames={STATS.duration}>
        <StatCallout
          headline="Docker Compose or Kubernetes Jobs — same pipeline, your call."
          badges={["No DAG boilerplate", "uv JIT deps", "Isolated per run"]}
        />
      </Sequence>

      <Sequence from={OUTRO.from} durationInFrames={OUTRO.duration}>
        <Outro
          headline="The lightweight, container-native orchestrator."
          cta="Try it in 5 minutes → github.com/ttuhin03/fastflow"
        />
      </Sequence>
    </AbsoluteFill>
  );
};
