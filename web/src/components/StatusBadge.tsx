import type { WebinarStatus } from '../api/types'

const LABELS: Record<WebinarStatus, string> = {
  created: '作成済み',
  queued: 'キュー待ち',
  running: '生成中',
  completed: '完了',
  failed: '失敗',
  partial: '一部完了',
}

export function StatusBadge({ status }: { status: WebinarStatus }) {
  return <span className={`badge badge-${status}`}>{LABELS[status] ?? status}</span>
}
