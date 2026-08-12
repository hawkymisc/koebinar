import { expect, test } from '@playwright/test'

const API_BASE = 'http://127.0.0.1:18002/api/v1'
const AUTH = { Authorization: 'Bearer mvp-token' }

test('資料投入から生成済みMP4の再生まで完遂する', async ({ page, request }) => {
  test.setTimeout(240_000)
  const browserErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(message.text())
  })
  page.on('pageerror', (error) => browserErrors.push(error.message))

  const orca = await request.post(`${API_BASE}/integrations/orcarouter`, {
    headers: AUTH,
    data: { api_key: 'sk-orca-valid-test-key-0001' },
  })
  expect(orca.ok()).toBeTruthy()
  const elevenlabs = await request.post(`${API_BASE}/integrations/elevenlabs`, {
    headers: AUTH,
    data: { api_key: 'xi-el-valid-test-key-0001', accept_free_tier: false },
  })
  expect(elevenlabs.ok()).toBeTruthy()

  await page.goto('/')
  await page.getByLabel('資料ファイル').setInputFiles('../tests/fixtures/e2e-knowledge.txt')
  const uploaded = page.getByLabel(/e2e-knowledge\.txt/)
  await expect(uploaded).toBeChecked()

  await page.getByLabel('テーマ').fill('厳格完了判定 E2E')
  await page.getByLabel('対象者').fill('完了判定を監査する担当者')
  await page.getByLabel('尺（分）').fill('1')
  await page.getByLabel('追加指示').fill('結論を先に示し、選択資料だけを根拠にする')
  await page.getByRole('button', { name: '作成', exact: true }).click()

  await expect(page.getByRole('heading', { name: '厳格完了判定 E2E' })).toBeVisible({
    timeout: 180_000,
  })
  await expect(page.getByText('完了', { exact: true })).toBeVisible()

  const video = page.locator('video')
  await expect(video).toBeVisible()
  await expect
    .poll(() => video.evaluate((element) => element.readyState), { timeout: 30_000 })
    .toBeGreaterThanOrEqual(1)
  const media = await video.evaluate(async (element) => {
    element.muted = true
    await element.play()
    await new Promise((resolve) => setTimeout(resolve, 1_000))
    return {
      currentTime: element.currentTime,
      duration: element.duration,
      videoWidth: element.videoWidth,
      videoHeight: element.videoHeight,
      error: element.error?.message ?? null,
    }
  })
  expect(media.error).toBeNull()
  expect(media.currentTime).toBeGreaterThan(0)
  expect(media.duration).toBeGreaterThan(0)
  expect(media.videoWidth).toBe(1920)
  expect(media.videoHeight).toBe(1080)

  const webinarId = new URL(page.url()).pathname.split('/').at(-1)
  expect(webinarId).toBeTruthy()
  const persisted = await request.get(`${API_BASE}/webinars/${webinarId}`, { headers: AUTH })
  expect(persisted.ok()).toBeTruthy()
  const webinar = await persisted.json()
  expect(webinar.instructions).toBe('結論を先に示し、選択資料だけを根拠にする')
  expect(webinar.document_ids).toHaveLength(1)
  const videoArtifact = webinar.artifacts.find((artifact: { type: string }) => artifact.type === 'video')
  expect(videoArtifact).toBeTruthy()
  expect(videoArtifact.meta.renderer).toBe('remotion')

  const documents = await request.get(`${API_BASE}/knowledge/documents`, { headers: AUTH })
  expect(documents.ok()).toBeTruthy()
  const selectedDocument = (await documents.json()).find(
    (document: { id: string }) => document.id === webinar.document_ids[0],
  )
  expect(selectedDocument.metadata).toMatchObject({
    filename: 'e2e-knowledge.txt',
    original_format: 'txt',
  })

  const videoResponse = await request.get(`${API_BASE}/webinars/${webinarId}/video`, {
    headers: AUTH,
  })
  expect(videoResponse.ok()).toBeTruthy()
  expect(videoResponse.headers()['content-type']).toContain('video/mp4')
  expect((await videoResponse.body()).byteLength).toBeGreaterThan(1_000)
  expect(browserErrors).toEqual([])
})
