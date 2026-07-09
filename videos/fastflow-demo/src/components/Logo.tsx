import React from "react";
import { theme } from "../theme";

// Reproduces frontend/public/favicon.svg (the app's real mark) at any size.
export const Logo: React.FC<{ size?: number }> = ({ size = 64 }) => {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none">
      <rect width="32" height="32" rx="6" fill={theme.indigo} />
      <g transform="translate(4, 4)">
        <path
          fill="white"
          d="M9.4 16.6L4.8 12l4.6-4.6L8 6l-6 6 6 6 1.4-1.4zm5.2 0l4.6-4.6-4.6-4.6L16 6l6 6-6 6-1.4-1.4z"
        />
      </g>
    </svg>
  );
};
