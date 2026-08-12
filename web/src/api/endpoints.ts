import { apiRequest, API_BASE, getToken } from './client'
import type {
  Job,
  KnowledgeCreateInput,
  KnowledgeDocument,
  PublicWebinar,
  Question,
  ScriptSlide,
  Webinar,
  WebinarCreateInput,
} from './types'

export function listWebinars(): Promise<Webinar[]> {
  return apiRequest<Webinar[]>('/webinars')
}

export function getWebinar(id: string): Promise<Webinar> {
  return apiRequest<Webinar>(`/webinars/${id}`)
}

export function patchPublication(id: string, published: boolean): Promise<Webinar> {
  return apiRequest<Webinar>(`/webinars/${id}/publication`, {
    method: 'PATCH',
    body: { published },
  })
}

export function getPublicWebinar(id: string): Promise<PublicWebinar> {
  return apiRequest<PublicWebinar>(`/public/webinars/${id}`, { auth: false })
}

export function publicVideoUrl(id: string): string {
  return `${API_BASE}/public/webinars/${id}/video`
}

export function createWebinar(input: WebinarCreateInput): Promise<Webinar> {
  return apiRequest<Webinar>('/webinars', { method: 'POST', body: input })
}

export function patchScript(id: string, slides: ScriptSlide[]): Promise<Webinar> {
  return apiRequest<Webinar>(`/webinars/${id}/script`, { method: 'PATCH', body: { slides } })
}

export function runStep(id: string, step: string, sync?: boolean): Promise<Webinar> {
  const qs = sync === undefined ? '' : `?sync=${sync}`
  return apiRequest<Webinar>(`/webinars/${id}/steps/${step}/run${qs}`, { method: 'POST' })
}

export function listJobs(id: string): Promise<{ jobs: Job[] }> {
  return apiRequest<{ jobs: Job[] }>(`/webinars/${id}/jobs`)
}

export function listDocuments(): Promise<KnowledgeDocument[]> {
  return apiRequest<KnowledgeDocument[]>('/knowledge/documents')
}

export function createDocument(input: KnowledgeCreateInput): Promise<KnowledgeDocument> {
  return apiRequest<KnowledgeDocument>('/knowledge/documents', { method: 'POST', body: input })
}

export function createQuestion(webinarId: string, message: string): Promise<Question> {
  return apiRequest<Question>('/questions', {
    method: 'POST',
    body: { webinar_id: webinarId, message },
    auth: false,
  })
}

export function getQuestion(id: string): Promise<Question> {
  return apiRequest<Question>(`/questions/${id}`, { auth: false })
}

export function createPublicQuestion(webinarId: string, message: string): Promise<Question> {
  return apiRequest<Question>(`/public/webinars/${webinarId}/questions`, {
    method: 'POST',
    body: { message },
    auth: false,
  })
}

export function getPublicQuestion(webinarId: string, questionId: string): Promise<Question> {
  return apiRequest<Question>(`/public/webinars/${webinarId}/questions/${questionId}`, {
    auth: false,
  })
}

export async function fetchVideoObjectUrl(id: string): Promise<string> {
  const response = await fetch(`${API_BASE}/webinars/${id}/video`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  })
  if (!response.ok) {
    throw new Error(`video fetch failed: ${response.status}`)
  }
  const blob = await response.blob()
  return URL.createObjectURL(blob)
}
