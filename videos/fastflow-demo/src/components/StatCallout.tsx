import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { theme } from "../theme";

// Prop-driven stat/feature callout row. Reusable for any "N badges" beat.
export const StatCallout: React.FC<{
  headline: string;
  badges: string[];
}> = ({ headline, badges }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const headlineIn = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 18 });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: theme.bg,
        justifyContent: "center",
        alignItems: "center",
        flexDirection: "column",
        fontFamily: theme.fontFamily,
      }}
    >
      <div
        style={{
          color: theme.white,
          fontSize: 56,
          fontWeight: 800,
          textAlign: "center",
          maxWidth: 1300,
          opacity: interpolate(headlineIn, [0, 1], [0, 1]),
          transform: `translateY(${interpolate(headlineIn, [0, 1], [20, 0])}px)`,
          marginBottom: 44,
        }}
      >
        {headline}
      </div>
      <div style={{ display: "flex", gap: 24 }}>
        {badges.map((b, i) => {
          const badgeIn = spring({
            frame: frame - 8 - i * 6,
            fps,
            config: { damping: 14, mass: 0.6 },
          });
          return (
            <div
              key={b}
              style={{
                opacity: interpolate(badgeIn, [0, 1], [0, 1]),
                transform: `scale(${badgeIn})`,
                backgroundColor: theme.bgAlt,
                border: `1px solid ${theme.indigo}`,
                borderRadius: 14,
                padding: "18px 30px",
                color: theme.indigoLight,
                fontSize: 28,
                fontWeight: 700,
              }}
            >
              {b}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
