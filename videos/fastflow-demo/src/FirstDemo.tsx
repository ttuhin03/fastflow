import React from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { TitleCard } from "./components/TitleCard";
import { ScreenshotShowcase } from "./components/ScreenshotShowcase";
import { TerminalReplay, TerminalLine } from "./components/TerminalReplay";
import { StatCallout } from "./components/StatCallout";
import { Outro } from "./components/Outro";
import { theme } from "./theme";

// Scene timing (fps = 30). Kept tight per the "pacing, no dead air" lens:
// every beat cuts right after it lands, nothing lingers past its point.
const HOOK = { from: 0, duration: 75 };
const REVEAL = { from: 75, duration: 60 };
const SHOT_DASHBOARD = { from: 135, duration: 120 };
const SHOT_PIPELINES = { from: 255, duration: 120 };
const SHOT_DEPENDENCIES = { from: 375, duration: 120 };
const TERMINAL = { from: 495, duration: 150 };
const STATS = { from: 645, duration: 120 };
const OUTRO = { from: 765, duration: 120 };

export const TOTAL_DURATION = OUTRO.from + OUTRO.duration; // 885 frames = 29.5s @ 30fps

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
        <ScreenshotShowcase
          src="screenshots/dashboard.png"
          caption="Live overview, run history, metrics heatmap"
        />
      </Sequence>

      <Sequence from={SHOT_PIPELINES.from} durationInFrames={SHOT_PIPELINES.duration}>
        <ScreenshotShowcase
          src="screenshots/pipelines.png"
          caption="One Python script per pipeline — no DAG required"
        />
      </Sequence>

      <Sequence from={SHOT_DEPENDENCIES.from} durationInFrames={SHOT_DEPENDENCIES.duration}>
        <ScreenshotShowcase
          src="screenshots/dependencies.png"
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
