import {randomBytes} from 'node:crypto';
import {chmod, readFile, writeFile} from 'node:fs/promises';

const [tunnelTokenPath, outputPath] = process.argv.slice(2);

if (!tunnelTokenPath || !outputPath) {
  throw new Error('Usage: node prepare-production-env.mjs TUNNEL_TOKEN OUTPUT');
}

const tunnelToken = (await readFile(tunnelTokenPath, 'utf8')).trim();
if (!tunnelToken) {
  throw new Error('Tunnel token is empty');
}

const randomSecret = () => randomBytes(32).toString('base64url');
const contents = [
  `KOEBINAR_DEFAULT_AUTH_TOKEN=${randomSecret()}`,
  `KOEBINAR_MASTER_KEY=${randomSecret()}`,
  'KOEBINAR_ALLOW_SYSTEM_LLM_KEY=false',
  'KOEBINAR_ALLOW_SYSTEM_TTS_KEY=false',
  'KOEBINAR_SITE_ADDRESS=:80',
  `CLOUDFLARE_TUNNEL_TOKEN=${tunnelToken}`,
  '',
].join('\n');

await writeFile(outputPath, contents, {mode: 0o600});
await chmod(outputPath, 0o600);
