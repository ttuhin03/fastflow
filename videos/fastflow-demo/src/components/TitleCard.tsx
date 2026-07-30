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

// Prop-driven title/hook card: big line, optional sub line, optional logo lockup.
export const TitleCard: React.FC<{
  line: string;
  subLine?: string;
  showLogo?: boolean;
}> = ({ line, subLine, showLogo }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const lineIn = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 18 });
  const lineOpacity = interpolate(lineIn, [0, 1], [0, 1]);
  const lineY = interpolate(lineIn, [0, 1], [24, 0]);

  const subIn = spring({
    frame: frame - 10,
    fps,
    config: { damping: 200 },
    durationInFrames: 18,
  });
  const subOpacity = interpolate(subIn, [0, 1], [0, 1]);

  const logoScale = spring({ frame, fps, config: { damping: 12, mass: 0.5 } });

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
      {showLogo && (
        <div style={{ transform: `scale(${logoScale})`, marginBottom: 28 }}>
          <Logo size={88} />
        </div>
      )}
      <div
        style={{
          color: theme.white,
          fontSize: 68,
          fontWeight: 800,
          textAlign: "center",
          maxWidth: 1400,
          lineHeight: 1.15,
          letterSpacing: -1,
          opacity: lineOpacity,
          transform: `translateY(${lineY}px)`,
        }}
      >
        {line}
      </div>
      {subLine && (
        <div
          style={{
            color: theme.indigoLight,
            fontSize: 34,
            fontWeight: 600,
            marginTop: 20,
            textAlign: "center",
            opacity: subOpacity,
          }}
        >
          {subLine}
        </div>
      )}
    </AbsoluteFill>
  );
};
