import React from "react";
import { Composition } from "remotion";
import { FirstDemo, TOTAL_DURATION } from "./FirstDemo";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="FirstDemo"
      component={FirstDemo}
      durationInFrames={TOTAL_DURATION}
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
