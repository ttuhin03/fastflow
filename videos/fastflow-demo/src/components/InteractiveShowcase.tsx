import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  Easing,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { theme } from "../theme";
import { Cursor } from "./Cursor";

// Card geometry matches ScreenshotShowcase (padding: 90 on a 1920x1080 canvas)
// so the two components can be cut between without a visual jump.
const CARD_PADDING = 90;
const CARD_W = 1920 - CARD_PADDING * 2;
const CARD_H = 1080 - CARD_PADDING * 2;
const IMG_W = 1920;
const IMG_H = 1080;

// object-fit: cover / object-position: top math -> maps a point in the
// original 1920x1080 screenshot to its on-canvas position inside the card,
// so the fake cursor lands exactly on the real UI element it's "clicking".
function mapPoint(px: number, py: number) {
  const scale = Math.max(CARD_W / IMG_W, CARD_H / IMG_H);
  return {
    x: CARD_PADDING + px * scale,
    y: CARD_PADDING + py * scale,
  };
}

// Real, current-frontend before/after screenshots + a synthetic cursor that
// moves in and "clicks" -- makes the demo read as interactive instead of a
// slideshow of static screenshots ("interactive" feedback on the first cut).
export const InteractiveShowcase: React.FC<{
  before: string;
  after: string;
  clickPoint: { x: number; y: number };
  caption: string;
  actionLabel: string;
}> = ({ before, after, clickPoint, caption, actionLabel }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  const fadeIn = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(
    frame,
    [durationInFrames - 12, durationInFrames],
    [1, 0],
    { extrapolateLeft: "clamp" }
  );
  const opacity = Math.min(fadeIn, fadeOut);

  const MOVE_START = 14;
  const MOVE_END = 58;
  const CLICK_AT = 62;
  const SWAP_AT = 72;

  const target = mapPoint(clickPoint.x, clickPoint.y);
  const start = { x: target.x - 300, y: target.y - 180 };

  const moveT = interpolate(frame, [MOVE_START, MOVE_END], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
  const cursorX = interpolate(moveT, [0, 1], [start.x, target.x]);
  const cursorY = interpolate(moveT, [0, 1], [start.y, target.y]);
  const cursorVisible = frame >= MOVE_START - 4;

  const pressed = frame >= CLICK_AT && frame < CLICK_AT + 10;
  const rippleProgress = interpolate(frame, [CLICK_AT, CLICK_AT + 22], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.quad),
  });

  const afterOpacity = interpolate(frame, [SWAP_AT, SWAP_AT + 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const labelOpacity = interpolate(
    frame,
    [MOVE_END - 8, MOVE_END + 2, CLICK_AT + 4, CLICK_AT + 14],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  const captionSpring = interpolate(frame, [SWAP_AT + 6, SWAP_AT + 24], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ backgroundColor: theme.bg }}>
      <AbsoluteFill style={{ opacity }}>
        <AbsoluteFill
          style={{ justifyContent: "center", alignItems: "center", padding: CARD_PADDING }}
        >
          <div
            style={{
              width: "100%",
              height: "100%",
              borderRadius: 20,
              overflow: "hidden",
              position: "relative",
              boxShadow: "0 40px 100px rgba(99,102,241,0.25)",
              border: `1px solid rgba(255,255,255,0.08)`,
            }}
          >
            <Img
              src={staticFile(before)}
              style={{
                position: "absolute",
                inset: 0,
                width: "100%",
                height: "100%",
                objectFit: "cover",
                objectPosition: "top",
              }}
            />
            <Img
              src={staticFile(after)}
              style={{
                position: "absolute",
                inset: 0,
                width: "100%",
                height: "100%",
                objectFit: "cover",
                objectPosition: "top",
                opacity: afterOpacity,
              }}
            />
          </div>
        </AbsoluteFill>

        {cursorVisible && (
          <>
            <Cursor x={cursorX} y={cursorY} pressed={pressed} rippleProgress={rippleProgress} />
            <div
              style={{
                position: "absolute",
                left: cursorX + 26,
                top: cursorY - 6,
                opacity: labelOpacity,
                backgroundColor: theme.indigo,
                color: theme.white,
                fontFamily: theme.fontFamily,
                fontSize: 20,
                fontWeight: 700,
                padding: "5px 12px",
                borderRadius: 8,
                whiteSpace: "nowrap",
              }}
            >
              {actionLabel}
            </div>
          </>
        )}

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
