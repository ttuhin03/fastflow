import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { theme } from "../theme";
import { Logo } from "./Logo";

// Prop-driven CTA card. Every video should end here with one explicit next step.
export const Outro: React.FC<{ headline: string; cta: string }> = ({
  headline,
  cta,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const logoScale = spring({ frame, fps, config: { damping: 12, mass: 0.5 } });
  const textIn = spring({ frame: frame - 8, fps, config: { damping: 200 }, durationInFrames: 18 });
  const ctaIn = spring({ frame: frame - 18, fps, config: { damping: 200 }, durationInFrames: 18 });

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(160deg, ${theme.bg} 0%, #16162A 100%)`,
        justifyContent: "center",
        alignItems: "center",
        flexDirection: "column",
        fontFamily: theme.fontFamily,
      }}
    >
      <div style={{ transform: `scale(${logoScale})`, marginBottom: 24 }}>
        <Logo size={72} />
      </div>
      <div
        style={{
          color: theme.white,
          fontSize: 52,
          fontWeight: 800,
          textAlign: "center",
          opacity: interpolate(textIn, [0, 1], [0, 1]),
          transform: `translateY(${interpolate(textIn, [0, 1], [16, 0])}px)`,
        }}
      >
        {headline}
      </div>
      <div
        style={{
          marginTop: 28,
          color: theme.white,
          backgroundColor: theme.indigo,
          borderRadius: 999,
          padding: "18px 42px",
          fontSize: 30,
          fontWeight: 700,
          opacity: interpolate(ctaIn, [0, 1], [0, 1]),
          transform: `translateY(${interpolate(ctaIn, [0, 1], [16, 0])}px)`,
        }}
      >
        {cta}
      </div>
    </AbsoluteFill>
  );
};
