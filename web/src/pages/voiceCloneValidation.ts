export const VOICE_CLONE_MAX_FILES = 5
export const VOICE_CLONE_MAX_FILE_BYTES = 10 * 1024 * 1024
export const VOICE_CLONE_MAX_TOTAL_BYTES = 25 * 1024 * 1024

const ALLOWED_SUFFIXES = new Set(['.mp3', '.wav', '.m4a', '.webm'])

export function validateVoiceCloneFiles(files: File[]): string | null {
  if (files.length < 1 || files.length > VOICE_CLONE_MAX_FILES) {
    return `音声ファイルは1〜${VOICE_CLONE_MAX_FILES}件選択してください。`
  }
  let total = 0
  for (const file of files) {
    const suffix = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
    if (!ALLOWED_SUFFIXES.has(suffix)) {
      return '音声ファイルは MP3、WAV、M4A、WebM に対応しています。'
    }
    if (file.size === 0) return '空の音声ファイルは使用できません。'
    if (file.size > VOICE_CLONE_MAX_FILE_BYTES) {
      return '音声ファイルは1件あたり10 MiB以下にしてください。'
    }
    total += file.size
  }
  if (total > VOICE_CLONE_MAX_TOTAL_BYTES) {
    return '音声ファイルの合計を25 MiB以下にしてください。'
  }
  return null
}
