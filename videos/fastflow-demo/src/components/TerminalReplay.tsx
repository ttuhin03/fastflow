import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";

export type TerminalLine = {
  text: string;
  // frame (relative to scene start) at which this line should be fully typed
  revealAt: number;
  color?: string;
  prompt?: boolean;
};

// Prop-driven terminal replay: pass any sequence of lines + reveal frames.
// Reusable for future videos that need to "show" a CLI instead of narrate it.
export const TerminalReplay: React.FC<{ lines: TerminalLine[] }> = ({ lines }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <AbsoluteFill
      style={{
        backgroundColor: theme.bg,
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <div
        style={{
          width: 1400,
          borderRadius: 16,
          overflow: "hidden",
          border: "1px solid rgba(255,255,255,0.08)",
          boxShadow: "0 40px 100px rgba(0,0,0,0.5)",
        }}
      >
        <div
          style={{
            backgroundColor: "#1A1A2A",
            padding: "14px 20px",
            display: "flex",
            gap: 8,
            alignItems: "center",
          }}
        >
          {["#FF5F57", "#FEBC2E", "#28C840"].map((c) => (
            <div key={c} style={{ width: 14, height: 14, borderRadius: 7, backgroundColor: c }} />
          ))}
          <div
            style={{
              marginLeft: 16,
              color: theme.gray,
              fontFamily: theme.monoFontFamily,
              fontSize: 20,
            }}
          >
            fastflow — pipeline run
          </div>
        </div>
        <div style={{ backgroundColor: theme.bgAlt, padding: "36px 40px", minHeight: 340 }}>
          {lines.map((line, i) => {
            const charsTotal = line.text.length;
            const typeStart = line.revealAt - fps * 0.5;
            const progress = Math.max(
              0,
              Math.min(1, (frame - typeStart) / (fps * 0.5))
            );
            const visibleChars = line.prompt
              ? Math.round(charsTotal * progress)
              : frame >= typeStart
              ? charsTotal
              : 0;
            if (frame < typeStart) return null;
            return (
              <div
                key={i}
                style={{
                  fontFamily: theme.monoFontFamily,
                  fontSize: 27,
                  color: line.color ?? theme.white,
                  marginBottom: 14,
                  whiteSpace: "pre",
                }}
              >
                {line.text.slice(0, visibleChars)}
                {line.prompt && visibleChars < charsTotal && (
                  <span style={{ opacity: frame % 20 < 10 ? 1 : 0 }}>▌</span>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};
