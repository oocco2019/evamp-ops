import { useCallback, useEffect, useRef, useState } from 'react'
import {
  LabelComposeResult,
  LabelComposeSlot,
  returnsAPI,
} from '../services/api'

const A4_W = 595
const A4_H = 842
const ACCEPT = '.pdf,.png,application/pdf,image/png'

function b64ToBlob(b64: string, mime: string): Blob {
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return new Blob([bytes], { type: mime })
}

export default function ReturnsPage() {
  const [files, setFiles] = useState<File[]>([])
  const [draggingOver, setDraggingOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<LabelComposeResult | null>(null)
  const [slots, setSlots] = useState<LabelComposeSlot[]>([])
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const previewRef = useRef<HTMLDivElement>(null)
  const slotsRef = useRef<LabelComposeSlot[]>([])
  const resultRef = useRef<LabelComposeResult | null>(null)
  const filesRef = useRef<File[]>([])
  const dragState = useRef<{
    index: number
    startX: number
    startY: number
    origX: number
    origY: number
    moved: boolean
  } | null>(null)

  useEffect(() => {
    slotsRef.current = slots
  }, [slots])
  useEffect(() => {
    resultRef.current = result
  }, [result])
  useEffect(() => {
    filesRef.current = files
  }, [files])

  useEffect(() => {
    return () => {
      if (pdfUrl) URL.revokeObjectURL(pdfUrl)
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }
  }, [pdfUrl, previewUrl])

  const applyResult = useCallback((data: LabelComposeResult, markDirty = false) => {
    setResult(data)
    setSlots(data.slots)
    setDirty(markDirty)
    const nextPdf = URL.createObjectURL(b64ToBlob(data.pdf_base64, 'application/pdf'))
    const nextPreview = URL.createObjectURL(
      b64ToBlob(data.preview_png_base64, 'image/png')
    )
    setPdfUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return nextPdf
    })
    setPreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return nextPreview
    })
  }, [])

  const runCompose = useCallback(
    async (
      fileList: File[],
      arrangementIndex: number,
      slotOverrides?: LabelComposeSlot[],
      persistCache = true,
      markDirty = false
    ) => {
      if (!fileList.length) return
      setBusy(true)
      setError(null)
      try {
        const fd = new FormData()
        for (const f of fileList) fd.append('files', f)
        fd.append('arrangement_index', String(arrangementIndex))
        fd.append('persist_cache', persistCache ? 'true' : 'false')
        if (slotOverrides) {
          fd.append('slot_overrides', JSON.stringify(slotOverrides))
        }
        const { data } = await returnsAPI.compose(fd)
        applyResult(data, markDirty)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Compose failed')
      } finally {
        setBusy(false)
      }
    },
    [applyResult]
  )

  const acceptFiles = (list: FileList | File[]) => {
    const next = Array.from(list).filter((f) => {
      const n = f.name.toLowerCase()
      return (
        n.endsWith('.pdf') ||
        n.endsWith('.png') ||
        f.type.includes('pdf') ||
        f.type.includes('png')
      )
    })
    if (!next.length) {
      setError('Drop PDF or PNG label files.')
      return
    }
    setFiles(next)
    setResult(null)
    setSlots([])
    void runCompose(next, 0)
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDraggingOver(false)
    if (e.dataTransfer.files?.length) acceptFiles(e.dataTransfer.files)
  }

  const regenerate = () => {
    if (!files.length || !result) return
    // No fixed pool — keep requesting the next variant forever
    void runCompose(files, result.arrangement_index + 1, undefined, false)
  }

  const saveLayout = async () => {
    if (!result || !slots.length) return
    setBusy(true)
    setError(null)
    try {
      await returnsAPI.saveTemplate(result.fingerprint, {
        slots,
        arrangement_index: result.arrangement_index,
      })
      await runCompose(files, result.arrangement_index, slots, true, false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
      setBusy(false)
    }
  }

  const downloadBlobUrl = (url: string | null, filename: string) => {
    if (!url) return
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.rel = 'noopener'
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  const downloadPdf = () => downloadBlobUrl(pdfUrl, 'returns-labels.pdf')
  const downloadPng = () => downloadBlobUrl(previewUrl, 'returns-labels.png')

  const onSlotPointerDown = (index: number, e: React.PointerEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const slot = slots[index]
    dragState.current = {
      index,
      startX: e.clientX,
      startY: e.clientY,
      origX: slot.x,
      origY: slot.y,
      moved: false,
    }
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
  }

  const onSlotPointerMove = (e: React.PointerEvent) => {
    const st = dragState.current
    if (!st) return
    const el = previewRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    if (rect.width < 1 || rect.height < 1) return
    const dxPt = ((e.clientX - st.startX) / rect.width) * A4_W
    const dyPt = -((e.clientY - st.startY) / rect.height) * A4_H
    if (Math.abs(dxPt) > 0.5 || Math.abs(dyPt) > 0.5) st.moved = true
    setSlots((prev) =>
      prev.map((s, i) =>
        i === st.index ? { ...s, x: st.origX + dxPt, y: st.origY + dyPt } : s
      )
    )
    setDirty(true)
  }

  const onSlotPointerUp = () => {
    const st = dragState.current
    dragState.current = null
    if (!st?.moved) return
    const current = slotsRef.current
    const res = resultRef.current
    const fl = filesRef.current
    if (!res || !fl.length || !current.length) return
    // Recompose so the preview image matches the new positions
    void runCompose(fl, res.arrangement_index, current, false, true)
  }

  return (
    <div className="px-4 py-6 sm:px-0 space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Returns</h1>
      </div>

      <section className="bg-white rounded-lg border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-3">Labels</h2>
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDraggingOver(true)
          }}
          onDragLeave={() => setDraggingOver(false)}
          onDrop={onDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`border-2 border-dashed rounded-lg px-6 py-14 text-center cursor-pointer transition-colors
            ${draggingOver ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400 bg-gray-50'}`}
        >
          <p className="text-sm text-gray-700">
            Drop PDF / PNG files here, or click to choose
          </p>
          <p className="mt-1 text-xs text-gray-500">
            Content is auto-cropped; largest label sits on top, the rest pack below.
          </p>
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPT}
            multiple
            className="hidden"
            onChange={(e) => {
              if (e.target.files?.length) acceptFiles(e.target.files)
              e.target.value = ''
            }}
          />
        </div>
        {files.length > 0 && (
          <p className="mt-3 text-xs text-gray-500">
            {files.length} file{files.length === 1 ? '' : 's'} selected
            {busy ? ' · composing…' : ''}
            {result?.cache_hit ? ' · cached layout' : ''}
          </p>
        )}
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      </section>

      {result && previewUrl && (
        <section className="bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <h2 className="text-lg font-semibold text-gray-900">Preview</h2>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={regenerate}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-md text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                Regenerate
                {result ? ` (#${result.arrangement_index + 1})` : ''}
              </button>
              <button
                type="button"
                disabled={busy || !dirty}
                onClick={() => void saveLayout()}
                className="px-3 py-1.5 text-sm border border-gray-300 rounded-md text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                Save layout
              </button>
              <button
                type="button"
                disabled={busy || !pdfUrl}
                onClick={downloadPdf}
                className="px-4 py-1.5 text-sm font-medium bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
              >
                PDF
              </button>
              <button
                type="button"
                disabled={busy || !previewUrl}
                onClick={downloadPng}
                className="px-4 py-1.5 text-sm font-medium bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
              >
                PNG
              </button>
            </div>
          </div>
          <div
            ref={previewRef}
            className="relative mx-auto bg-white border border-gray-300 shadow-sm overflow-hidden select-none"
            style={{
              width: 'min(100%, 420px)',
              aspectRatio: `${A4_W} / ${A4_H}`,
            }}
          >
            <img
              src={previewUrl}
              alt="Composed A4 preview"
              draggable={false}
              className="absolute inset-0 w-full h-full object-fill pointer-events-none"
            />
            {slots.map((slot, index) => (
              <div
                key={`${slot.source_index}-${index}`}
                role="presentation"
                onPointerDown={(e) => onSlotPointerDown(index, e)}
                onPointerMove={onSlotPointerMove}
                onPointerUp={onSlotPointerUp}
                onPointerCancel={onSlotPointerUp}
                className="absolute border-2 border-blue-500/80 bg-blue-500/15 cursor-move hover:border-blue-600 touch-none"
                style={{
                  left: `${(slot.x / A4_W) * 100}%`,
                  top: `${((A4_H - slot.y - slot.height) / A4_H) * 100}%`,
                  width: `${(slot.width / A4_W) * 100}%`,
                  height: `${(slot.height / A4_H) * 100}%`,
                }}
                title={`Label ${slot.source_index + 1}`}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
