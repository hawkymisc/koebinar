import React from "react";
import { Composition } from "remotion";
import { WebinarComposition, WebinarProps } from "./Webinar";

const defaultProps: WebinarProps = {
  timeline: {
    fps: 30,
    total_frames: 90,
    slides: [
      {
        slide_index: 0,
        title: "Koebinar",
        start_frame: 0,
        end_frame: 90,
        duration_frames: 90,
      },
    ],
    audio_clips: [],
  },
  slides: [{ title: "Koebinar", bullets: ["AI webinar agent"] }],
  fps: 30,
  width: 1920,
  height: 1080,
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Webinar"
        component={WebinarComposition}
        durationInFrames={defaultProps.timeline.total_frames || 90}
        fps={defaultProps.fps || 30}
        width={defaultProps.width || 1920}
        height={defaultProps.height || 1080}
        defaultProps={defaultProps}
        calculateMetadata={async ({ props }) => {
          const frames = props.timeline?.total_frames || 90;
          return {
            durationInFrames: Math.max(1, frames),
            fps: props.fps || 30,
            width: props.width || 1920,
            height: props.height || 1080,
          };
        }}
      />
    </>
  );
};
