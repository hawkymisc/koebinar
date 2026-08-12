import JSZip from 'jszip'
import { describe, expect, it, vi } from 'vitest'
import {
  MAX_FILE_BYTES,
  extractKnowledgeFile,
  extractPptxText,
} from './fileExtraction'

vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => ({
  GlobalWorkerOptions: { workerSrc: '' },
  getDocument: () => ({
    promise: Promise.resolve({
      numPages: 2,
      getPage: async (page: number) => ({
        getTextContent: async () => ({
          items: page === 1 ? [{ str: 'PDF page one' }] : [{ str: 'PDF page two' }],
        }),
      }),
    }),
  }),
}))

describe('extractKnowledgeFile', () => {
  it('extracts text files and reports provenance', async () => {
    const result = await extractKnowledgeFile(
      new File(['# Product\nSecure webinar generation'], 'product.md', { type: 'text/markdown' }),
    )

    expect(result).toEqual({
      title: 'product.md',
      content: '# Product\nSecure webinar generation',
      metadata: { filename: 'product.md', original_format: 'md' },
    })
  })

  it('extracts PDF pages in order in the browser', async () => {
    const result = await extractKnowledgeFile(
      new File(['fake-pdf'], 'brief.pdf', { type: 'application/pdf' }),
    )
    expect(result.content).toBe('PDF page one\n\nPDF page two')
    expect(result.metadata.original_format).toBe('pdf')
  })

  it('rejects unsupported and oversized files before parsing', async () => {
    await expect(extractKnowledgeFile(new File(['x'], 'image.png'))).rejects.toThrow(
      '対応していないファイル形式',
    )
    const oversized = new File([new Uint8Array(MAX_FILE_BYTES + 1)], 'huge.txt')
    await expect(extractKnowledgeFile(oversized)).rejects.toThrow('ファイルサイズ')
  })
})

describe('extractPptxText', () => {
  it('uses presentation order and includes speaker notes', async () => {
    const zip = new JSZip()
    zip.file(
      'ppt/presentation.xml',
      '<p:presentation xmlns:p="p" xmlns:r="r"><p:sldIdLst><p:sldId r:id="rId2"/><p:sldId r:id="rId1"/></p:sldIdLst></p:presentation>',
    )
    zip.file(
      'ppt/_rels/presentation.xml.rels',
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="slides/slide1.xml"/><Relationship Id="rId2" Target="slides/slide2.xml"/></Relationships>',
    )
    zip.file('ppt/slides/slide1.xml', '<p:sld xmlns:p="p" xmlns:a="a"><a:t>First</a:t></p:sld>')
    zip.file('ppt/slides/slide2.xml', '<p:sld xmlns:p="p" xmlns:a="a"><a:t>Second</a:t></p:sld>')
    zip.file(
      'ppt/notesSlides/notesSlide2.xml',
      '<p:notes xmlns:p="p" xmlns:a="a"><a:t>Second note</a:t></p:notes>',
    )
    const buffer = await zip.generateAsync({ type: 'arraybuffer' })

    await expect(extractPptxText(buffer)).resolves.toBe('Second\nSecond note\n\nFirst')
  })
})
