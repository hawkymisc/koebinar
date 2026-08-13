import {chmod, readFile, writeFile} from 'node:fs/promises';

const [inputPath, privateKeyPath, certificatePath] = process.argv.slice(2);

if (!inputPath || !privateKeyPath || !certificatePath) {
  throw new Error('Usage: node extract-access-details.mjs INPUT PRIVATE_KEY CERTIFICATE');
}

const body = JSON.parse(await readFile(inputPath, 'utf8'));
const {privateKey, certKey} = body.accessDetails ?? {};

if (!privateKey || !certKey) {
  throw new Error('Lightsail access details do not contain a key pair');
}

await writeFile(privateKeyPath, privateKey, {mode: 0o600});
await writeFile(certificatePath, certKey, {mode: 0o600});
await Promise.all([
  chmod(privateKeyPath, 0o600),
  chmod(certificatePath, 0o600),
]);
