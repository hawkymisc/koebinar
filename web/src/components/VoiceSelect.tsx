import type { VoiceInfo } from '../api/types'
import { usableVoices } from './voiceOptions'

interface VoiceSelectProps {
  id: string
  voices: VoiceInfo[]
  value: string
  disabled?: boolean
  onChange: (voiceId: string) => void
}

export function VoiceSelect({ id, voices, value, disabled, onChange }: VoiceSelectProps) {
  const options = usableVoices(voices)

  return (
    <label className="field" htmlFor={id}>
      ナレーション音声
      <select
        id={id}
        required
        value={value}
        disabled={disabled || options.length === 0}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">音声を選択してください</option>
        {options.map((voice) => (
          <option key={voice.voice_id} value={voice.voice_id}>
            {voice.name}（{voice.category}）
          </option>
        ))}
      </select>
      {options.length === 0 && (
        <small className="error-text">
          利用可能な音声がありません。<a href="/settings/integrations">連携設定で音声を同期・確認</a>してください。
        </small>
      )}
    </label>
  )
}
