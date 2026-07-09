import React from "react";
import { theme } from "../theme";

// A synthetic pointer + click-ripple, positioned by the parent in absolute
// canvas coordinates. Used by InteractiveShowcase to fake a live click
// without a real screen recording.
export const Cursor: React.FC<{
  x: number;
  y: number;
  pressed: boolean;
  rippleProgress: number; // 0 = no ripple, 1 = fully expanded/faded
}> = ({ x, y, pressed, rippleProgress }) => {
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        transform: `translate(-4px, -2px) scale(${pressed ? 0.88 : 1})`,
        transformOrigin: "4px 2px",
        pointerEvents: "none",
        filter: "drop-shadow(0 6px 14px rgba(0,0,0,0.45))",
      }}
    >
      {rippleProgress > 0 && (
        <div
          style={{
            position: "absolute",
            left: 4 - 26 * rippleProgress,
            top: 2 - 26 * rippleProgress,
            width: 52 * rippleProgress,
            height: 52 * rippleProgress,
            borderRadius: "50%",
            border: `2px solid ${theme.indigoLight}`,
            opacity: 1 - rippleProgress,
          }}
        />
      )}
      <svg width="30" height="34" viewBox="0 0 30 34" fill="none">
        <path
          d="M2 2 L2 26 L8.5 20.5 L12.5 29 L17 27 L13 18.5 L21 18.5 Z"
          fill={theme.white}
          stroke="rgba(0,0,0,0.55)"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
};
