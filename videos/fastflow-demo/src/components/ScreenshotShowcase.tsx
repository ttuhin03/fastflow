import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { theme } from "../theme";

// Prop-driven: any real app screenshot + a one-line caption that carries the
// message for sound-off viewers. Slow Ken Burns zoom keeps a static frame alive.
export const ScreenshotShowcase: React.FC<{
  src: string;
  caption: string;
  zoomFrom?: number;
  zoomTo?: number;
}> = ({ src, caption, zoomFrom = 1.06, zoomTo = 1.16 }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const fadeIn = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 12, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp" }
  );
  const opacity = Math.min(fadeIn, fadeOut);

  const scale = interpolate(frame, [0, durationInFrames], [zoomFrom, zoomTo]);

  const captionSpring = interpolate(frame, [6, 6 + fps * 0.4], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ backgroundColor: theme.bg }}>
      <AbsoluteFill style={{ opacity }}>
        <AbsoluteFill
          style={{
            justifyContent: "center",
            alignItems: "center",
            padding: 90,
          }}
        >
          <div
            style={{
              width: "100%",
              height: "100%",
              borderRadius: 20,
              overflow: "hidden",
              boxShadow: "0 40px 100px rgba(99,102,241,0.25)",
              border: `1px solid rgba(255,255,255,0.08)`,
            }}
          >
            <Img
              src={staticFile(src)}
              style={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
                objectPosition: "top",
                transform: `scale(${scale})`,
              }}
            />
          </div>
        </AbsoluteFill>
        <div
          style={{
            position: "absolute",
            bottom: 56,
            left: 0,
            right: 0,
            display: "flex",
            justifyContent: "center",
            opacity: captionSpring,
            transform: `translateY(${interpolate(captionSpring, [0, 1], [16, 0])}px)`,
          }}
        >
          <div
            style={{
              backgroundColor: "rgba(11,11,20,0.85)",
              border: `1px solid rgba(99,102,241,0.4)`,
              borderRadius: 999,
              padding: "16px 36px",
              color: theme.white,
              fontFamily: theme.fontFamily,
              fontSize: 30,
              fontWeight: 600,
            }}
          >
            {caption}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
