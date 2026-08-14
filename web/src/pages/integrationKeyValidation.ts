import type { Provider } from '../api/types'

export const API_KEY_PREFIXES: Record<Provider, string> = {
  orcarouter: 'sk-',
  elevenlabs: 'sk_',
}

const PROVIDER_NAMES: Record<Provider, string> = {
  orcarouter: 'OrcaRouter',
  elevenlabs: 'ElevenLabs',
}

export function validateApiKeyPrefix(provider: Provider, apiKey: string): string | null {
  const prefix = API_KEY_PREFIXES[provider]
  if (apiKey.startsWith(prefix)) return null
  return `${PROVIDER_NAMES[provider]}のAPIキーは「${prefix}」から始まる必要があります。キーIDではなくAPIキー全文をコピーしてください。`
}
