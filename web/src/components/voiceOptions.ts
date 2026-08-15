import type { VoiceInfo } from '../api/types'

export function usableVoices(voices: VoiceInfo[]): VoiceInfo[] {
  return voices.filter((voice) => voice.active && voice.usable)
}
