#!/usr/bin/env node
/**
 * Koebinar Remotion render entry.
 * Usage: node render.mjs --props /path/props.json --output /path/webinar.mp4
 *
 * Uses @remotion/renderer when installed. Writes a structured error to stderr
 * and exits non-zero when Chromium/Remotion cannot run.
 */
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

function parseArgs(argv) {
  const out = { props: null, output: null };
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === "--props") out.props = argv[++i];
    else if (argv[i] === "--output") out.output = argv[++i];
  }
  return out;
}

async function main() {
  const args = parseArgs(process.argv);
  if (!args.props || !args.output) {
    console.error("Usage: node render.mjs --props <file.json> --output <file.mp4>");
    process.exit(2);
  }
  const props = JSON.parse(readFileSync(args.props, "utf8"));
  const output = resolve(args.output);
  mkdirSync(dirname(output), { recursive: true });

  let bundle;
  let renderMedia;
  let selectComposition;
  try {
    ({ bundle } = await import("@remotion/bundler"));
    ({ renderMedia, selectComposition } = await import("@remotion/renderer"));
  } catch (e) {
    console.error("Remotion packages not installed. Run: cd remotion && npm install");
    console.error(String(e));
    process.exit(3);
  }

  const entry = resolve(__dirname, "src/index.ts");
  const browserExecutable = process.env.KOEBINAR_REMOTION_BROWSER_EXECUTABLE || undefined;
  console.log(JSON.stringify({ phase: "bundle", entry }));
  const bundled = await bundle({
    entryPoint: entry,
    webpackOverride: (config) => config,
  });

  const fps = props.fps || props.timeline?.fps || 30;
  const durationInFrames = Math.max(1, props.timeline?.total_frames || 90);
  const compositionId = "Webinar";
  const concurrency = Math.max(
    1,
    Number.parseInt(process.env.KOEBINAR_REMOTION_CONCURRENCY || "1", 10) || 1,
  );

  const composition = await selectComposition({
    serveUrl: bundled,
    id: compositionId,
    inputProps: props,
    browserExecutable,
  });

  console.log(
    JSON.stringify({
      phase: "render",
      composition: compositionId,
      durationInFrames: composition.durationInFrames || durationInFrames,
      fps: composition.fps || fps,
    })
  );

  await renderMedia({
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
    browserExecutable,
  });

  console.log(JSON.stringify({ phase: "done", output, generator: "koebinar-remotion" }));
}

main().catch((err) => {
  console.error("Remotion render failed:", err && err.stack ? err.stack : err);
  process.exit(1);
});
