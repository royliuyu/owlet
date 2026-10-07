/**
 * pdf.js setup. Kept apart from the viewer so the worker is configured once
 * and the rest of the app never imports pdfjs directly.
 */

import { GlobalWorkerOptions, getDocument, type PDFDocumentProxy } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { readToken } from '@/lib/api'

GlobalWorkerOptions.workerSrc = workerUrl

export type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist'

/** Same auth the fetch helpers use: a cookie session, or a bearer token. */
export function loadPdf(url: string): { promise: Promise<PDFDocumentProxy>; cancel: () => void } {
  const token = readToken()
  const task = getDocument({
    url,
    withCredentials: true,
    httpHeaders: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  return {
    promise: task.promise,
    cancel: () => {
      void task.destroy()
    },
  }
}
