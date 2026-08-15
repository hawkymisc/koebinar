import React from "react";
import {
  AbsoluteFill,
  Audio,
  interpolate,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

type UnknownRecord = Record<string, unknown>;

export type SlideInput = {
  slideIndex?: number;
  slide_index?: number;
  title?: string;
  subtitle?: string;
  bullets?: unknown[];
  body?: unknown;
  content?: unknown;
  visual?: unknown;
  visual_aid?: string;
  layout?: string;
  theme?: string;
  elements?: UnknownRecord[];
  props?: {
    layout?: string;
    elements?: UnknownRecord[];
  };
};

export type TimelineSlide = {
  slide_index?: number;
  title?: string;
  start_frame?: number;
  end_frame?: number;
  duration_frames?: number;
  props?: SlideInput;
};

export type TimelineAudioClip = {
  slide_index?: number;
  sentence_index?: number;
  start_frame?: number;
  end_frame?: number;
  duration_frames?: number;
  duration_sec?: number;
  /** Relative path staged into Remotion's public directory. */
  src?: string;
  audio_src?: string;
  audio_uri?: string;
};

export type WebinarProps = {
  timeline: {
    fps?: number;
    total_frames?: number;
    slides?: TimelineSlide[];
    audio_clips?: TimelineAudioClip[];
  };
  slides: SlideInput[];
  fps?: number;
  width?: number;
  height?: number;
};

type Card = { title: string; description?: string };
type Metric = { label: string; value: string };
type CodeBlock = { language?: string; code: string };

type NormalizedSlide = {
  title: string;
  subtitle?: string;
  eyebrow?: string;
  bodyText?: string;
  bullets: string[];
  cards: Card[];
  metrics: Metric[];
  code?: CodeBlock;
  visualLabel?: string;
  layout?: string;
  theme?: string;
};

const asRecord = (value: unknown): UnknownRecord | undefined =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as UnknownRecord)
    : undefined;

const asText = (value: unknown): string | undefined => {
  if (typeof value === "string") return value.trim() || undefined;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return undefined;
};

const firstText = (record: UnknownRecord, keys: string[]): string | undefined => {
  for (const key of keys) {
    const value = asText(record[key]);
    if (value) return value;
  }
  return undefined;
};

const itemText = (value: unknown): string | undefined => {
  const direct = asText(value);
  if (direct) return direct;
  const record = asRecord(value);
  if (!record) return undefined;
  const primary = firstText(record, ["text", "title", "label", "name", "value"]);
  const detail = firstText(record, ["description", "detail", "body"]);
  if (primary && detail && primary !== detail) return `${primary} — ${detail}`;
  return primary || detail;
};

const unique = (values: string[], limit: number): string[] =>
  [...new Set(values.map((value) => value.trim()).filter(Boolean))].slice(0, limit);

const limitText = (value: string | undefined, maxLength: number): string | undefined => {
  if (!value) return undefined;
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length <= maxLength ? normalized : `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
};

const limitCode = (value: string): string => {
  const lines = value.split(/\r?\n/).slice(0, 14).map((line) =>
    line.length <= 120 ? line : `${line.slice(0, 119)}…`
  );
  const clipped = lines.join("\n");
  return clipped.length <= 900 ? clipped : `${clipped.slice(0, 899)}…`;
};

const cardsFrom = (value: unknown): Card[] => {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      const record = asRecord(item);
      if (!record) {
        const title = asText(item);
        return title ? { title } : undefined;
      }
      const title = firstText(record, ["title", "label", "heading", "name", "value"]);
      if (!title) return undefined;
      return {
        title,
        description: firstText(record, ["description", "detail", "text", "body"]),
      };
    })
    .filter((card): card is Card => Boolean(card));
};

const metricsFrom = (value: unknown): Metric[] => {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      const record = asRecord(item);
      if (!record) return undefined;
      const label = firstText(record, ["label", "title", "name"]);
      const metricValue = firstText(record, ["value", "metric", "number"]);
      return label && metricValue ? { label, value: metricValue } : undefined;
    })
    .filter((metric): metric is Metric => Boolean(metric));
};

export const normalizeSlide = (slide: SlideInput, index: number): NormalizedSlide => {
  const bullets: string[] = [];
  const cards: Card[] = [];
  const metrics: Metric[] = [];
  let title = asText(slide.title);
  let subtitle = asText(slide.subtitle);
  let eyebrow: string | undefined;
  let bodyText = asText(slide.content);
  let code: CodeBlock | undefined;
  let visualLabel = asText(slide.visual_aid);

  if (Array.isArray(slide.bullets)) {
    bullets.push(...slide.bullets.map(itemText).filter((item): item is string => Boolean(item)));
  }

  const collectStructured = (value: unknown, key = "") => {
    const text = asText(value);
    if (text) {
      if (["body", "vision", "summary", "description", "content", "text"].includes(key) && !bodyText) {
        bodyText = text;
      }
      return;
    }
    if (Array.isArray(value)) {
      if (key.includes("metric")) metrics.push(...metricsFrom(value));
      else if (["phase", "phases", "cards", "features", "steps"].includes(key)) {
        cards.push(...cardsFrom(value));
      } else {
        bullets.push(...value.map(itemText).filter((item): item is string => Boolean(item)));
      }
      return;
    }
    const record = asRecord(value);
    if (!record) return;
    const type = asText(record.type)?.toLowerCase().replace(/-/g, "_");
    if (type === "code_block" || "code" in record) {
      const codeText = asText(record.code);
      if (codeText) code = { code: codeText, language: asText(record.language) };
      return;
    }
    if (type === "metrics" && Array.isArray(record.items)) {
      metrics.push(...metricsFrom(record.items));
      return;
    }
    if (["cards", "flow", "timeline"].includes(type || "") && Array.isArray(record.items)) {
      cards.push(...cardsFrom(record.items));
      return;
    }
    if (type === "bullets" || Array.isArray(record.items)) {
      const items = Array.isArray(record.items) ? record.items : [];
      const itemCards = cardsFrom(items);
      const heading = firstText(record, ["heading", "title", "label"]);
      if (type === "highlight_box" && itemCards.length > 0) cards.push(...itemCards);
      else bullets.push(...items.map(itemText).filter((item): item is string => Boolean(item)));
      if (heading && type === "highlight_box") cards.unshift({ title: heading });
      return;
    }
    for (const [nestedKey, nestedValue] of Object.entries(record)) {
      if (nestedKey !== "type") collectStructured(nestedValue, nestedKey);
    }
  };

  collectStructured(slide.body, "body");
  collectStructured(slide.visual, "visual");

  for (const element of slide.props?.elements || slide.elements || []) {
    const type = asText(element.type)?.toLowerCase() || "";
    const text = asText(element.text);
    if (type === "heading" && text) title ||= text;
    else if (type === "subheading" && text) subtitle ||= text;
    else if (["badge", "section-label"].includes(type) && text) eyebrow ||= text;
    else if (type === "bullet-list" && Array.isArray(element.items)) {
      bullets.push(...element.items.map(itemText).filter((item): item is string => Boolean(item)));
    } else if (type === "feature-cards") {
      cards.push(...cardsFrom(element.cards));
    } else if (type === "media-placeholder") {
      visualLabel ||= firstText(element, ["label", "text"]);
    } else if (type === "icon") {
      visualLabel ||= firstText(element, ["label", "name"]);
    } else if (["text", "footer"].includes(type) && text && !bodyText) {
      bodyText = text;
    }
  }

  return {
    title: limitText(title, 90) || `Slide ${index + 1}`,
    subtitle: limitText(subtitle, 150),
    eyebrow: limitText(eyebrow, 60),
    bodyText: limitText(bodyText, 280),
    bullets: unique(bullets, 6).map((bullet) => limitText(bullet, 180) || ""),
    cards: cards.filter((card, cardIndex, all) =>
      all.findIndex((candidate) => candidate.title === card.title) === cardIndex
    ).slice(0, 4).map((card) => ({
      title: limitText(card.title, 80) || "",
      description: limitText(card.description, 170),
    })),
    metrics: metrics.filter((metric, metricIndex, all) =>
      all.findIndex((candidate) => candidate.label === metric.label && candidate.value === metric.value) === metricIndex
    ).slice(0, 3).map((metric) => ({
      label: limitText(metric.label, 80) || "",
      value: limitText(metric.value, 40) || "",
    })),
    code: code ? { ...code, code: limitCode(code.code) } : undefined,
    visualLabel: limitText(visualLabel, 170),
    layout: slide.layout || slide.props?.layout,
    theme: slide.theme,
  };
};

const AudioTracks: React.FC<{ clips: TimelineAudioClip[] }> = ({ clips }) => (
  <AbsoluteFill>
    {clips.map((clip, index) => {
      const src = clip.src || clip.audio_src;
      if (!src) return null;
      const from = Math.max(0, clip.start_frame ?? 0);
      const inferredDuration = (clip.end_frame ?? from) - from;
      const duration = Math.max(1, clip.duration_frames ?? inferredDuration);
      return (
        <Sequence
          key={`${clip.slide_index ?? 0}-${clip.sentence_index ?? index}-${index}`}
          from={from}
          durationInFrames={duration}
          layout="none"
        >
          <Audio src={staticFile(src)} />
        </Sequence>
      );
    })}
  </AbsoluteFill>
);

const themeColors: Record<string, { bg: string; panel: string; accent: string; text: string; muted: string }> = {
  tech: { bg: "#07111f", panel: "#102337", accent: "#22d3ee", text: "#eef8ff", muted: "#a7c1d6" },
  casual: { bg: "#25160d", panel: "#3a2618", accent: "#fbbf24", text: "#fff8ed", muted: "#e8ccb1" },
  formal: { bg: "#f2f6fa", panel: "#ffffff", accent: "#1d4ed8", text: "#10213a", muted: "#53657b" },
};

const panelStyle = (panel: string, accent: string): React.CSSProperties => ({
  backgroundColor: panel,
  border: `1px solid ${accent}44`,
  borderRadius: 24,
  boxShadow: "0 20px 55px rgba(0,0,0,0.18)",
});

const VisualPanel: React.FC<{
  slide: NormalizedSlide;
  colors: (typeof themeColors)[string];
}> = ({ slide, colors }) => {
  if (slide.code) {
    return (
      <div style={{ ...panelStyle(colors.panel, colors.accent), padding: 30, height: "100%", overflow: "hidden" }}>
        <div style={{ color: colors.accent, fontSize: 18, marginBottom: 18, textTransform: "uppercase" }}>
          {slide.code.language || "code"}
        </div>
        <pre style={{ margin: 0, color: colors.text, fontSize: 23, lineHeight: 1.45, whiteSpace: "pre-wrap", overflow: "hidden", maxHeight: 560, wordBreak: "break-word" }}>
          {slide.code.code}
        </pre>
      </div>
    );
  }

  if (slide.cards.length > 0) {
    return (
      <div style={{ display: "grid", gridTemplateColumns: slide.cards.length > 1 ? "repeat(2, 1fr)" : "1fr", gap: 18, height: "100%", minHeight: 0, overflow: "hidden" }}>
        {slide.cards.map((card, index) => (
          <div key={`${card.title}-${index}`} style={{ ...panelStyle(colors.panel, colors.accent), padding: 26, minHeight: 0, overflow: "hidden" }}>
            <div style={{ width: 42, height: 6, borderRadius: 999, backgroundColor: colors.accent, marginBottom: 18 }} />
            <div style={{ fontSize: 28, fontWeight: 700, lineHeight: 1.2, maxHeight: 70, overflow: "hidden", wordBreak: "break-word" }}>{card.title}</div>
            {card.description ? (
              <div style={{ color: colors.muted, fontSize: 21, lineHeight: 1.45, marginTop: 12, maxHeight: 154, overflow: "hidden", wordBreak: "break-word", display: "-webkit-box", WebkitLineClamp: 5, WebkitBoxOrient: "vertical" }}>{card.description}</div>
            ) : null}
          </div>
        ))}
      </div>
    );
  }

  if (slide.metrics.length > 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 18, height: "100%", justifyContent: "center" }}>
        {slide.metrics.map((metric) => (
          <div key={`${metric.label}-${metric.value}`} style={{ ...panelStyle(colors.panel, colors.accent), padding: "24px 30px", overflow: "hidden", wordBreak: "break-word" }}>
            <div style={{ color: colors.accent, fontWeight: 800, fontSize: 40, maxHeight: 54, overflow: "hidden" }}>{metric.value}</div>
            <div style={{ color: colors.muted, fontSize: 23, marginTop: 6, maxHeight: 64, overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>{metric.label}</div>
          </div>
        ))}
      </div>
    );
  }

  if (slide.visualLabel) {
    return (
      <div style={{ ...panelStyle(colors.panel, colors.accent), height: "100%", padding: 34, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "end", gap: 18, height: "62%" }}>
          {[42, 72, 54, 94].map((height, index) => (
            <div key={index} style={{ flex: 1, height: `${height}%`, borderRadius: "16px 16px 4px 4px", background: `linear-gradient(180deg, ${colors.accent}, ${colors.accent}55)` }} />
          ))}
        </div>
        <div style={{ color: colors.muted, fontSize: 23, lineHeight: 1.35, maxHeight: 66, overflow: "hidden", wordBreak: "break-word" }}>{slide.visualLabel}</div>
      </div>
    );
  }

  return null;
};

const SlideView: React.FC<{ slide: SlideInput; index: number }> = ({ slide, index }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const normalized = normalizeSlide(slide, index);
  const colors = themeColors[normalized.theme || "tech"] || themeColors.tech;
  const entrance = interpolate(frame, [0, Math.max(1, fps * 0.35)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const hasPrimary = Boolean(normalized.bodyText || normalized.bullets.length);
  const hasVisual = Boolean(normalized.cards.length || normalized.metrics.length || normalized.code || normalized.visualLabel);
  const visibleBullets = normalized.bodyText ? normalized.bullets.slice(0, 4) : normalized.bullets;

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at 85% 10%, ${colors.accent}22, transparent 34%), ${colors.bg}`,
        color: colors.text,
        fontFamily: "Inter, Noto Sans JP, system-ui, sans-serif",
        padding: "58px 72px 50px",
        opacity: entrance,
      }}
    >
      <div style={{ transform: `translateY(${(1 - entrance) * 22}px)` }}>
        <div style={{ fontSize: 20, letterSpacing: 1.8, color: colors.accent, marginBottom: 16, textTransform: "uppercase" }}>
          {normalized.eyebrow || `Slide ${index + 1}`}
        </div>
        <h1 style={{ fontSize: 61, margin: 0, lineHeight: 1.12, maxWidth: 1550, maxHeight: 142, overflow: "hidden", wordBreak: "break-word" }}>{normalized.title}</h1>
        {normalized.subtitle ? (
          <div style={{ color: colors.muted, fontSize: 29, lineHeight: 1.35, marginTop: 15, maxWidth: 1460, maxHeight: 78, overflow: "hidden", wordBreak: "break-word" }}>
            {normalized.subtitle}
          </div>
        ) : null}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: hasPrimary && hasVisual ? "minmax(0, 1.08fr) minmax(420px, 0.92fr)" : "1fr",
          gap: 38,
          marginTop: 36,
          minHeight: 0,
          overflow: "hidden",
          flex: 1,
          transform: `translateY(${(1 - entrance) * 34}px)`,
        }}
      >
        {hasPrimary ? (
          <div style={{ minWidth: 0, minHeight: 0, height: "100%", overflow: "hidden", alignSelf: "start" }}>
            {normalized.bodyText ? (
              <div style={{ fontSize: 29, lineHeight: 1.5, color: colors.muted, marginBottom: 20, maxHeight: 132, overflow: "hidden", wordBreak: "break-word" }}>{normalized.bodyText}</div>
            ) : null}
            {visibleBullets.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 12, minHeight: 0, overflow: "hidden" }}>
                {visibleBullets.map((bullet, bulletIndex) => (
                  <div key={`${bullet}-${bulletIndex}`} style={{ ...panelStyle(colors.panel, colors.accent), boxSizing: "border-box", display: "flex", gap: 17, padding: "12px 20px", fontSize: 25, lineHeight: 1.35, maxHeight: 94, overflow: "hidden", wordBreak: "break-word", flexShrink: 0 }}>
                    <span style={{ color: colors.accent, fontWeight: 900 }}>●</span>
                    <span style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{bullet}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
        {hasVisual ? <VisualPanel slide={normalized} colors={colors} /> : null}
      </div>

      <div style={{ position: "absolute", bottom: 22, right: 42, fontSize: 17, color: colors.muted, opacity: 0.65 }}>
        Koebinar
      </div>
    </AbsoluteFill>
  );
};

export const WebinarComposition: React.FC<WebinarProps> = ({ timeline, slides }) => {
  const tlSlides = timeline?.slides || [];
  const audioClips = timeline?.audio_clips || [];
  if (tlSlides.length === 0) {
    return (
      <>
        <AbsoluteFill style={{ backgroundColor: "#07111f", color: "#fff", padding: 80 }}>
          <h1>Koebinar</h1>
        </AbsoluteFill>
        <AudioTracks clips={audioClips} />
      </>
    );
  }

  return (
    <>
      <AbsoluteFill>
        {tlSlides.map((timelineSlide, index) => {
          const start = timelineSlide.start_frame ?? 0;
          const duration = timelineSlide.duration_frames ?? Math.max(1, (timelineSlide.end_frame ?? start + 30) - start);
          const slideIndex = timelineSlide.slide_index ?? index;
          const explicitlyIndexedSlide = slides.find((candidate) =>
            candidate.slideIndex === slideIndex || candidate.slide_index === slideIndex
          );
          const slide = explicitlyIndexedSlide || slides[slideIndex] || slides[index] || timelineSlide.props || { title: timelineSlide.title };
          return (
            <Sequence key={`${slideIndex}-${index}`} from={start} durationInFrames={Math.max(1, duration)}>
              <SlideView slide={slide} index={slideIndex} />
            </Sequence>
          );
        })}
      </AbsoluteFill>
      <AudioTracks clips={audioClips} />
    </>
  );
};
