import React from "react";
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig } from "remotion";

export type SlideInput = {
  title?: string;
  bullets?: string[];
  theme?: string;
};

export type TimelineSlide = {
  slide_index?: number;
  title?: string;
  start_frame?: number;
  end_frame?: number;
  duration_frames?: number;
};

export type WebinarProps = {
  timeline: {
    fps?: number;
    total_frames?: number;
    slides?: TimelineSlide[];
  };
  slides: SlideInput[];
  fps?: number;
  width?: number;
  height?: number;
};

const themeColors: Record<string, { bg: string; accent: string; text: string }> = {
  tech: { bg: "#0b1220", accent: "#22d3ee", text: "#e2e8f0" },
  casual: { bg: "#2b1d14", accent: "#fbbf24", text: "#fff7ed" },
  formal: { bg: "#f8fafc", accent: "#1e293b", text: "#0f172a" },
};

const SlideView: React.FC<{ slide: SlideInput; index: number }> = ({ slide, index }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const theme = themeColors[slide.theme || "tech"] || themeColors.tech;
  const opacity = Math.min(1, frame / Math.max(1, fps * 0.3));

  return (
    <AbsoluteFill
      style={{
        backgroundColor: theme.bg,
        color: theme.text,
        fontFamily: "sans-serif",
        padding: 80,
        opacity,
      }}
    >
      <div style={{ fontSize: 28, color: theme.accent, marginBottom: 24 }}>
        Slide {index + 1} · AI-generated narration
      </div>
      <h1 style={{ fontSize: 72, margin: 0, lineHeight: 1.15 }}>{slide.title || `Slide ${index + 1}`}</h1>
      <ul style={{ marginTop: 48, fontSize: 36, lineHeight: 1.5 }}>
        {(slide.bullets || []).map((b, i) => (
          <li key={i} style={{ marginBottom: 12 }}>
            {b}
          </li>
        ))}
      </ul>
      <div
        style={{
          position: "absolute",
          bottom: 40,
          right: 60,
          fontSize: 20,
          opacity: 0.7,
        }}
      >
        Koebinar
      </div>
    </AbsoluteFill>
  );
};

export const WebinarComposition: React.FC<WebinarProps> = ({ timeline, slides }) => {
  const tlSlides = timeline?.slides || [];
  if (tlSlides.length === 0) {
    return (
      <AbsoluteFill style={{ backgroundColor: "#0b1220", color: "#fff", padding: 80 }}>
        <h1>Koebinar</h1>
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill>
      {tlSlides.map((ts, i) => {
        const start = ts.start_frame ?? 0;
        const dur = ts.duration_frames ?? Math.max(1, (ts.end_frame ?? start + 30) - start);
        const slideProps = slides[i] || slides[ts.slide_index ?? i] || { title: ts.title };
        return (
          <Sequence key={i} from={start} durationInFrames={Math.max(1, dur)}>
            <SlideView slide={slideProps} index={i} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
