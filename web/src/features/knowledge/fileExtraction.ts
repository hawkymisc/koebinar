import JSZip from 'jszip'
import pdfWorkerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'

export const MAX_FILE_BYTES = 20 * 1024 * 1024
export const MAX_PPTX_EXPANDED_BYTES = 100 * 1024 * 1024

export interface ExtractedKnowledgeFile {
  title: string
  content: string
  metadata: {
    filename: string
    original_format: 'txt' | 'md' | 'pdf' | 'pptx'
  }
}

function extensionOf(filename: string): ExtractedKnowledgeFile['metadata']['original_format'] | null {
  const extension = filename.toLowerCase().split('.').pop()
  if (extension === 'txt' || extension === 'md' || extension === 'pdf' || extension === 'pptx') {
    return extension
  }
  return null
}

function parseXml(xml: string): XMLDocument {
  const document = new DOMParser().parseFromString(xml, 'application/xml')
  if (document.querySelector('parsererror')) {
    throw new Error('PPTX内のXMLを読み取れませんでした')
  }
  return document
}

function elementsByLocalName(document: XMLDocument, name: string): Element[] {
  return Array.from(document.getElementsByTagName('*')).filter((element) => element.localName === name)
}

function textRuns(xml: string): string {
  return elementsByLocalName(parseXml(xml), 't')
    .map((element) => element.textContent?.trim() ?? '')
    .filter(Boolean)
    .join('\n')
}

function normalizeZipPath(path: string): string {
  const parts: string[] = []
  for (const part of path.split('/')) {
    if (!part || part === '.') continue
    if (part === '..') parts.pop()
    else parts.push(part)
  }
  return parts.join('/')
}

function resolveTarget(basePath: string, target: string): string {
  const base = basePath.split('/').slice(0, -1).join('/')
  return normalizeZipPath(`${base}/${target}`)
}

async function relationshipMap(zip: JSZip, relationshipPath: string): Promise<Map<string, string>> {
  const file = zip.file(relationshipPath)
  if (!file) return new Map()
  const document = parseXml(await file.async('text'))
  return new Map(
    elementsByLocalName(document, 'Relationship').flatMap((element) => {
      const id = element.getAttribute('Id')
      const target = element.getAttribute('Target')
      return id && target ? [[id, target] as const] : []
    }),
  )
}

function expandedSize(zip: JSZip): number {
  return Object.values(zip.files).reduce((total, file) => {
    const size = (file as unknown as { _data?: { uncompressedSize?: number } })._data?.uncompressedSize
    return total + (size ?? 0)
  }, 0)
}

export async function extractPptxText(buffer: ArrayBuffer): Promise<string> {
  const zip = await JSZip.loadAsync(buffer)
  if (expandedSize(zip) > MAX_PPTX_EXPANDED_BYTES) {
    throw new Error('PPTXの展開後サイズが上限を超えています')
  }

  const presentationFile = zip.file('ppt/presentation.xml')
  if (!presentationFile) throw new Error('PPTXのプレゼンテーション情報がありません')
  const presentation = parseXml(await presentationFile.async('text'))
  const relationships = await relationshipMap(zip, 'ppt/_rels/presentation.xml.rels')
  const slidePaths = elementsByLocalName(presentation, 'sldId').flatMap((element) => {
    const relationshipId = element.getAttribute('r:id')
      ?? element.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'id')
    const target = relationshipId ? relationships.get(relationshipId) : null
    return target ? [resolveTarget('ppt/presentation.xml', target)] : []
  })

  const slides: string[] = []
  for (const slidePath of slidePaths) {
    const slideFile = zip.file(slidePath)
    if (!slideFile) continue
    const parts = [textRuns(await slideFile.async('text'))]
    const filename = slidePath.split('/').pop() ?? ''
    const relationshipPath = `ppt/slides/_rels/${filename}.rels`
    const slideRelationships = await relationshipMap(zip, relationshipPath)
    const noteTarget = [...slideRelationships.values()].find((target) => target.includes('notesSlide'))
    const slideNumber = filename.match(/slide(\d+)\.xml$/)?.[1]
    const notePath = noteTarget
      ? resolveTarget(slidePath, noteTarget)
      : slideNumber
        ? `ppt/notesSlides/notesSlide${slideNumber}.xml`
        : null
    const noteFile = notePath ? zip.file(notePath) : null
    if (noteFile) parts.push(textRuns(await noteFile.async('text')))
    const slideText = parts.filter(Boolean).join('\n')
    if (slideText) slides.push(slideText)
  }
  const content = slides.join('\n\n').trim()
  if (!content) throw new Error('PPTXからテキストを抽出できませんでした')
  return content
}

async function extractPdfText(buffer: ArrayBuffer): Promise<string> {
  const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs')
  pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl
  const pdf = await pdfjs.getDocument({ data: new Uint8Array(buffer) }).promise
  const pages: string[] = []
  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
    const page = await pdf.getPage(pageNumber)
    const text = await page.getTextContent()
    const pageText = text.items
      .map((item) => ('str' in item ? item.str : ''))
      .filter(Boolean)
      .join(' ')
      .trim()
    if (pageText) pages.push(pageText)
  }
  const content = pages.join('\n\n').trim()
  if (!content) throw new Error('PDFにテキスト層がありません（OCRには対応していません）')
  return content
}

export async function extractKnowledgeFile(file: File): Promise<ExtractedKnowledgeFile> {
  const format = extensionOf(file.name)
  if (!format) throw new Error(`対応していないファイル形式です: ${file.name}`)
  if (file.size > MAX_FILE_BYTES) {
    throw new Error(`ファイルサイズが上限（${MAX_FILE_BYTES / 1024 / 1024}MB）を超えています`)
  }

  let content: string
  if (format === 'txt' || format === 'md') content = await file.text()
  else if (format === 'pdf') content = await extractPdfText(await file.arrayBuffer())
  else content = await extractPptxText(await file.arrayBuffer())

  if (!content.trim()) throw new Error(`${file.name} からテキストを抽出できませんでした`)
  return {
    title: file.name,
    content,
    metadata: { filename: file.name, original_format: format },
  }
}
