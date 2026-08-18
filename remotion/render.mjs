#!/usr/bin/env node
/**
 * Koebinar render entry.
 *
 * Default strategy: render one fully visible still per slide with Remotion,
 * then let FFmpeg repeat those pixels, apply the entrance fade, place audio at
 * exact frame-derived sample offsets, and encode the final H.264/AAC MP4.
 * Use --strategy full-remotion for compositions that require per-frame motion.
 */
import {spawn} from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
} from "node:fs";
import {dirname, isAbsolute, join, relative, resolve} from "node:path";
import {fileURLToPath} from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SUPPORTED_STRATEGIES = new Set(["stills-ffmpeg", "full-remotion"]);
const ENTRANCE_DURATION_SEC = 0.35;
const AUDIO_SAMPLE_RATE = 48_000;

function parseArgs(argv) {
  const out = {
    props: null,
    output: null,
    publicDir: null,
    strategy: process.env.KOEBINAR_REMOTION_RENDER_STRATEGY || "stills-ffmpeg",
  };
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === "--props") out.props = argv[++i];
    else if (argv[i] === "--output") out.output = argv[++i];
    else if (argv[i] === "--public-dir") out.publicDir = argv[++i];
    else if (argv[i] === "--strategy") out.strategy = argv[++i];
  }
  return out;
}

function positiveInteger(value, fallback, label) {
  const parsed = Number(value ?? fallback);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${label} must be a positive integer`);
  }
  return parsed;
}

function slideSpans(timeline, totalFrames) {
  const slides = timeline?.slides;
  if (!Array.isArray(slides) || slides.length === 0) {
    throw new Error("timeline.slides must contain at least one slide");
  }
  let cursor = 0;
  const spans = slides.map((slide, index) => {
    const start = Number(slide?.start_frame);
    const end = Number(slide?.end_frame);
    if (!Number.isInteger(start) || !Number.isInteger(end) || start !== cursor || end <= start) {
      throw new Error(`slide ${index} must form a positive contiguous frame range`);
    }
    if (slide.duration_frames != null && Number(slide.duration_frames) !== end - start) {
      throw new Error(`slide ${index} duration_frames does not match its frame range`);
    }
    cursor = end;
    return {index, start, end, duration: end - start};
  });
  if (cursor !== totalFrames) {
    throw new Error(`slide ranges end at ${cursor}, expected total_frames ${totalFrames}`);
  }
  return spans;
}

function resolveAudioInputs(timeline, publicDir, fps, totalFrames) {
  const clips = timeline?.audio_clips || [];
  if (!Array.isArray(clips)) throw new Error("timeline.audio_clips must be an array");
  if (clips.length === 0) return [];
  if (!publicDir) throw new Error("--public-dir is required when audio clips are present");

  const root = resolve(publicDir);
  return clips.map((clip, index) => {
    const source = clip?.src || clip?.audio_src;
    if (typeof source !== "string" || source.length === 0) {
      throw new Error(`audio clip ${index} has no staged source`);
    }
    const path = resolve(root, source);
    const fromRoot = relative(root, path);
    if (fromRoot.startsWith("..") || isAbsolute(fromRoot)) {
      throw new Error(`audio clip ${index} escapes the public directory`);
    }
    if (!existsSync(path) || statSync(path).size <= 0) {
      throw new Error(`audio clip ${index} is missing or empty`);
    }
    const startFrame = Number(clip.start_frame);
    const endFrame = Number(clip.end_frame);
    if (
      !Number.isInteger(startFrame) ||
      !Number.isInteger(endFrame) ||
      startFrame < 0 ||
      endFrame <= startFrame ||
      endFrame > totalFrames
    ) {
      throw new Error(`audio clip ${index} has an invalid frame range`);
    }
    return {
      path,
      startSamples: Math.round((startFrame * AUDIO_SAMPLE_RATE) / fps),
      durationSamples: Math.round(((endFrame - startFrame) * AUDIO_SAMPLE_RATE) / fps),
    };
  });
}

function numberArg(value) {
  return Number(value).toFixed(9).replace(/0+$/, "").replace(/\.$/, "");
}

function buildFfmpegArgs({stills, spans, audioInputs, fps, totalFrames, output}) {
  const args = ["-hide_banner", "-loglevel", "error"];
  for (const still of stills) {
    args.push("-loop", "1", "-framerate", String(fps), "-i", still);
  }
  for (const audio of audioInputs) args.push("-i", audio.path);

  const filters = [];
  const videoLabels = [];
  spans.forEach((span, index) => {
    const fadeDuration = Math.min(ENTRANCE_DURATION_SEC, span.duration / fps);
    filters.push(
      `[${index}:v]trim=end_frame=${span.duration},` +
        `setpts=N/(${fps}*TB),fade=t=in:st=0:d=${numberArg(fadeDuration)},` +
        `format=yuv420p[v${index}]`,
    );
    videoLabels.push(`[v${index}]`);
  });
  if (videoLabels.length === 1) filters.push(`${videoLabels[0]}null[vout]`);
  else filters.push(`${videoLabels.join("")}concat=n=${videoLabels.length}:v=1:a=0[vout]`);

  if (audioInputs.length > 0) {
    const audioLabels = [];
    audioInputs.forEach((audio, index) => {
      const inputIndex = stills.length + index;
      filters.push(
        `[${inputIndex}:a]aresample=${AUDIO_SAMPLE_RATE},` +
          `aformat=sample_fmts=fltp:channel_layouts=stereo,` +
          `atrim=end_sample=${audio.durationSamples},asetpts=PTS-STARTPTS,` +
          `apad=whole_len=${audio.durationSamples},atrim=end_sample=${audio.durationSamples},` +
          `adelay=${audio.startSamples}S:all=1[a${index}]`,
      );
      audioLabels.push(`[a${index}]`);
    });
    const totalSamples = Math.round((totalFrames * AUDIO_SAMPLE_RATE) / fps);
    const mix = audioLabels.length === 1
      ? `${audioLabels[0]}anull`
      : `${audioLabels.join("")}amix=inputs=${audioLabels.length}:duration=longest:` +
        "dropout_transition=0:normalize=0";
    filters.push(
      `${mix},apad=whole_len=${totalSamples},atrim=end_sample=${totalSamples},` +
        "asetpts=N/SR/TB[aout]",
    );
  }

  args.push("-filter_complex", filters.join(";"), "-map", "[vout]");
  if (audioInputs.length > 0) args.push("-map", "[aout]");
  args.push(
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-pix_fmt", "yuv420p",
    "-r", String(fps),
    "-frames:v", String(totalFrames),
  );
  if (audioInputs.length > 0) {
    args.push("-c:a", "aac", "-b:a", "320k", "-ar", String(AUDIO_SAMPLE_RATE), "-ac", "2");
  }
  args.push(
    "-t", numberArg(totalFrames / fps),
    "-movflags", "+faststart",
    "-map_metadata", "-1",
    "-y",
    output,
  );
  return args;
}

function runFfmpeg(args) {
  const ffmpegExecutable = process.env.KOEBINAR_FFMPEG_EXECUTABLE || "ffmpeg";
  console.log(JSON.stringify({phase: "ffmpeg", executable: ffmpegExecutable}));
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(ffmpegExecutable, args, {stdio: ["ignore", "pipe", "pipe"]});
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout = `${stdout}${chunk}`.slice(-8_000);
    });
    child.stderr.on("data", (chunk) => {
      stderr = `${stderr}${chunk}`.slice(-8_000);
    });
    child.on("error", rejectPromise);
    child.on("close", (code) => {
      if (code === 0) resolvePromise();
      else rejectPromise(new Error(`FFmpeg exited ${code}: ${stderr || stdout}`));
    });
  });
}

async function renderStillsWithFfmpeg({
  bundled,
  props,
  output,
  publicDir,
  browserExecutable,
  renderer,
}) {
  const fps = positiveInteger(props.fps || props.timeline?.fps, 30, "fps");
  const totalFrames = positiveInteger(props.timeline?.total_frames, 90, "total_frames");
  const spans = slideSpans(props.timeline, totalFrames);
  const audioInputs = resolveAudioInputs(props.timeline, publicDir, fps, totalFrames);
  const stillProps = {...props, timeline: {...props.timeline, audio_clips: []}};
  const scratch = mkdtempSync(join(dirname(output), ".koebinar-stills-"));
  let browser;
  try {
    browser = await renderer.openBrowser("chrome", {browserExecutable});
    const composition = await renderer.selectComposition({
      serveUrl: bundled,
      id: "Webinar",
      inputProps: stillProps,
      browserExecutable,
      puppeteerInstance: browser,
    });
    const stills = [];
    for (const span of spans) {
      const settledFrame = Math.min(
        span.end - 1,
        span.start + Math.ceil(fps * ENTRANCE_DURATION_SEC),
      );
      const still = join(scratch, `slide-${String(span.index).padStart(4, "0")}.png`);
      console.log(
        JSON.stringify({
          phase: "render-still",
          slide: span.index,
          frame: settledFrame,
          total_slides: spans.length,
        }),
      );
      await renderer.renderStill({
        composition,
        serveUrl: bundled,
        output: still,
        frame: settledFrame,
        imageFormat: "png",
        inputProps: stillProps,
        browserExecutable,
        puppeteerInstance: browser,
      });
      stills.push(still);
    }
    await browser.close({silent: true});
    browser = undefined;
    await runFfmpeg(buildFfmpegArgs({stills, spans, audioInputs, fps, totalFrames, output}));
    return spans.length;
  } finally {
    if (browser) await browser.close({silent: true});
    rmSync(scratch, {recursive: true, force: true});
  }
}

async function renderFullRemotion({bundled, props, output, browserExecutable, renderer}) {
  const fps = props.fps || props.timeline?.fps || 30;
  const durationInFrames = Math.max(1, props.timeline?.total_frames || 90);
  const concurrency = Math.max(
    1,
    Number.parseInt(process.env.KOEBINAR_REMOTION_CONCURRENCY || "1", 10) || 1,
  );
  const composition = await renderer.selectComposition({
    serveUrl: bundled,
    id: "Webinar",
    inputProps: props,
    browserExecutable,
  });
  let lastReportedPercent = -5;
  await renderer.renderMedia({
    composition: {
      ...composition,
      durationInFrames: composition.durationInFrames || durationInFrames,
      fps: composition.fps || fps,
      width: props.width || composition.width || 1920,
      height: props.height || composition.height || 1080,
    },
    serveUrl: bundled,
    codec: "h264",
    outputLocation: output,
    inputProps: props,
    concurrency,
    x264Preset: "veryfast",
    browserExecutable,
    onProgress: ({progress, renderedFrames, encodedFrames, stitchStage}) => {
      const progressPercent = Math.floor(progress * 100);
      if (progressPercent < lastReportedPercent + 5 && progressPercent !== 100) return;
      lastReportedPercent = progressPercent;
      console.log(
        JSON.stringify({
          phase: "render",
          progress_percent: progressPercent,
          rendered_frames: renderedFrames,
          encoded_frames: encodedFrames,
          stitch_stage: stitchStage,
        }),
      );
    },
  });
}

async function main() {
  const args = parseArgs(process.argv);
  if (!args.props || !args.output) {
    console.error(
      "Usage: node render.mjs --props <file.json> --output <file.mp4> " +
        "[--public-dir <dir>] [--strategy stills-ffmpeg|full-remotion]",
    );
    process.exit(2);
  }
  if (!SUPPORTED_STRATEGIES.has(args.strategy)) {
    throw new Error(`Unsupported render strategy: ${args.strategy}`);
  }
  const props = JSON.parse(readFileSync(args.props, "utf8"));
  const output = resolve(args.output);
  mkdirSync(dirname(output), {recursive: true});
  const publicDir = args.publicDir ? resolve(args.publicDir) : undefined;
  if (publicDir) mkdirSync(publicDir, {recursive: true});

  let bundle;
  let renderer;
  try {
    ({bundle} = await import("@remotion/bundler"));
    renderer = await import("@remotion/renderer");
  } catch (error) {
    console.error("Remotion packages not installed. Run: cd remotion && npm install");
    throw error;
  }

  const entry = resolve(__dirname, "src/index.ts");
  const browserExecutable = process.env.KOEBINAR_REMOTION_BROWSER_EXECUTABLE || undefined;
  console.log(JSON.stringify({phase: "bundle", entry, strategy: args.strategy}));
  const bundleOptions = {
    entryPoint: entry,
    webpackOverride: (config) => config,
  };
  if (publicDir) bundleOptions.publicDir = publicDir;
  const bundled = await bundle(bundleOptions);

  if (args.strategy === "full-remotion") {
    await renderFullRemotion({bundled, props, output, browserExecutable, renderer});
    console.log(JSON.stringify({phase: "done", output, strategy: args.strategy}));
    return;
  }

  const renderedStills = await renderStillsWithFfmpeg({
    bundled,
    props,
    output,
    publicDir,
    browserExecutable,
    renderer,
  });
  console.log(
    JSON.stringify({
      phase: "done",
      output,
      strategy: args.strategy,
      rendered_stills: renderedStills,
    }),
  );
}

main().catch((error) => {
  console.error("Remotion render failed:", error?.stack || error);
  process.exit(1);
});
