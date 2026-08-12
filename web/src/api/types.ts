export type Lang = 'ja' | 'en'
export type Template = 'tech' | 'casual' | 'formal'
export type Style = 'casual' | 'keynote' | 'formal' | 'humorous'
export type SourceType = 'pdf' | 'url' | 'text'

export type WebinarStatus = 'created' | 'queued' | 'running' | 'completed' | 'failed' | 'partial'

export type PipelineStep =
  | 'outline'
  | 'slides'
  | 'script'
  | 'tts_script'
  | 'audio'
  | 'timeline'
  | 'video'

export const PIPELINE_STEPS: PipelineStep[] = [
  'outline',
  'slides',
  'script',
  'tts_script',
  'audio',
  'timeline',
  'video',
]

export interface PipelineArtifact {
  id: string
  webinar_id: string
  step: PipelineStep
  type: string
  storage_uri: string
  model_id?: string | null
  prompt_version?: string | null
  created_at: string
  meta: Record<string, unknown>
}

export interface Webinar {
  id: string
  theme: string
  audience: string
  duration_min: number
  lang: Lang
  template: Template
  style: Style
  voice_id: string
  instructions: string
  document_ids: string[]
  status: WebinarStatus
  current_step: PipelineStep | null
  error: string | null
  created_at: string
  artifacts: PipelineArtifact[]
  script: { slides: ScriptSlide[]; manually_edited?: boolean } | null
  job_id: string | null
  published_at: string | null
}

export interface PublicWebinar {
  id: string
  theme: string
  audience: string
  duration_min: number
  lang: Lang
  template: Template
  published_at: string
}

export interface ScriptSlide {
  slide_index?: number
  title?: string
  narration?: string
  [key: string]: unknown
}

export interface WebinarCreateInput {
  theme: string
  audience?: string
  duration_min?: number
  lang?: Lang
  template?: Template
  style?: Style
  voice_id?: string
  instructions?: string
  document_ids?: string[]
  auto_run?: boolean
  sync?: boolean
}

export interface KnowledgeDocument {
  id: string
  title: string
  source_type: SourceType
  storage_uri: string
  status: 'pending' | 'indexed' | 'failed'
  chunk_count: number
  metadata: Record<string, unknown>
  created_at: string
}

export interface KnowledgeCreateInput {
  title: string
  source_type: SourceType
  content: string
  metadata?: Record<string, unknown>
}

export interface Job {
  id: string
  webinar_id: string
  step: PipelineStep
  status: string
  error: string | null
  created_at: string
  updated_at: string
  attempts: number
}

export interface Citation {
  document_id: string
  chunk_id: string
  score: number
  source_title?: string
}

export interface Answer {
  id: string
  question_id: string
  text: string
  confidence: number
  answerability: 'answerable' | 'insufficient' | 'restricted'
  citations: Citation[]
}

export interface Question {
  id: string
  webinar_id: string
  message: string
  status: 'pending' | 'answered' | 'held' | 'failed'
  created_at: string
  answer: Answer | null
}
