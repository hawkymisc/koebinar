import {chmod, readFile, writeFile} from 'node:fs/promises';

const [configPath, accountId, tunnelId, outputPath] = process.argv.slice(2);

if (!configPath || !accountId || !tunnelId || !outputPath) {
  throw new Error('Usage: node fetch-tunnel-token.mjs CONFIG ACCOUNT TUNNEL OUTPUT');
}

const config = await readFile(configPath, 'utf8');
const match = config.match(/^oauth_token\s*=\s*"([^"]+)"/m);

if (!match) {
  throw new Error('Wrangler OAuth token was not found');
}

const response = await fetch(
  `https://api.cloudflare.com/client/v4/accounts/${accountId}/cfd_tunnel/${tunnelId}/token`,
  {headers: {Authorization: `Bearer ${match[1]}`}},
);
const body = await response.json();

if (!response.ok || !body.success || typeof body.result !== 'string') {
  throw new Error(`Cloudflare API failed with status ${response.status}`);
}

await writeFile(outputPath, `${body.result}\n`, {mode: 0o600});
await chmod(outputPath, 0o600);
