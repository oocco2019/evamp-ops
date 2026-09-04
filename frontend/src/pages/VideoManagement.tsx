import { useState, useEffect, useRef, useCallback } from 'react'
import {
  listingVideoAPI,
  listingVideoJobAPI,
  type RemoveVideoFromListingsEvent,
  type VideoIdResponse,
  type ListingVideoJobStatus,
} from '../services/api'

const JOB_STORAGE_KEY = 'listing_video_job_id'
const POLL_INTERVAL_MS = 3000

function parseItemIdsFromText(text: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const part of text.split(/[\n,]+/)) {
    const s = part.trim()
    if (!s) continue
    const urlMatch = s.match(/\/itm\/(\d{9,14})(?:\?|$|\/)/)
    const id = urlMatch?.[1] ?? (/^\d{9,14}$/.test(s) ? s : null)
    if (id && !seen.has(id)) {
      seen.add(id)
      out.push(id)
    }
  }
  return out
}

function JobPanel({
  jobId,
  onClear,
}: {
  jobId: string
  onClear: () => void
}) {
  const [status, setStatus] = useState<ListingVideoJobStatus | null>(null)
  const [logs, setLogs] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const logContainerRef = useRef<HTMLPreElement | null>(null)
  const userScrolledUp = useRef(false)
  const lastLogIdRef = useRef(0)
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const poll = useCallback(async () => {
    try {
      const [statusRes, logsRes] = await Promise.all([
        listingVideoJobAPI.getStatus(jobId),
        listingVideoJobAPI.getLogs(jobId, lastLogIdRef.current),
      ])
      setStatus(statusRes.data)
      if (logsRes.data.logs.length > 0) {
        const newLines = logsRes.data.logs.map((l) => l.message)
        setLogs((prev) => [...prev, ...newLines])
        lastLogIdRef.current = logsRes.data.logs[logsRes.data.logs.length - 1].id
      }
      setError(null)
      if (['done', 'error'].includes(statusRes.data.status)) return
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Polling failed')
    }
    pollRef.current = setTimeout(() => { void poll() }, POLL_INTERVAL_MS)
  }, [jobId])

  useEffect(() => {
    lastLogIdRef.current = 0
    userScrolledUp.current = false
    setLogs([])
    void poll()
    return () => { if (pollRef.current) clearTimeout(pollRef.current) }
  }, [jobId, poll])

  useEffect(() => {
    const el = logContainerRef.current
    if (el && !userScrolledUp.current) el.scrollTop = el.scrollHeight
  }, [logs])

  const statusColor = (s: string) => {
    if (s === 'done') return 'text-green-700'
    if (s === 'error') return 'text-red-600'
    if (['running', 'scanning'].includes(s)) return 'text-blue-600'
    return 'text-gray-600'
  }

  return (
    <div className="mt-4 p-4 bg-gray-50 border border-gray-200 rounded">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs text-gray-500 font-mono">Job: {jobId}</div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setLogs([])}
            className="text-xs text-gray-500 underline hover:text-gray-700"
          >
            Clear log
          </button>
          <button
            type="button"
            onClick={onClear}
            className="text-xs text-gray-500 underline hover:text-gray-700"
          >
            Dismiss
          </button>
        </div>
      </div>
      {status && (
        <div className="flex flex-wrap gap-4 text-sm mb-2">
          <span className={`font-semibold ${statusColor(status.status)}`}>
            {status.status.toUpperCase()}
          </span>
          <span>Total: <b>{status.total}</b></span>
          <span>Updated: <b>{status.updated_count}</b></span>
          <span>Skipped: <b>{status.skipped_count}</b></span>
          <span>Failed: <b>{status.failed_count}</b></span>
        </div>
      )}
      {status?.error_message && (
        <p className="text-sm text-red-600 mb-2">{status.error_message}</p>
      )}
      {error && <p className="text-xs text-red-500 mb-1">{error}</p>}
      {logs.length > 0 && (
        <pre
          ref={logContainerRef}
          className="max-h-56 overflow-y-auto text-xs bg-white border border-gray-200 rounded p-2 whitespace-pre-wrap"
          onScroll={(e) => {
            const el = e.currentTarget
            // Consider "at bottom" if within 40px of the bottom
            userScrolledUp.current = el.scrollTop + el.clientHeight < el.scrollHeight - 40
          }}
        >
          {logs.join('\n')}
        </pre>
      )}
      {!status && !error && (
        <p className="text-xs text-gray-500 animate-pulse">Loading…</p>
      )}
    </div>
  )
}

export default function VideoManagement({ embedded = false }: { embedded?: boolean } = {}) {
  const [input, setInput] = useState('')
  const [result, setResult] = useState<VideoIdResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // SKU job state
  const [addVideoId, setAddVideoId] = useState('')
  const [addSku, setAddSku] = useState('')
  const [addJobId, setAddJobId] = useState<string | null>(() => localStorage.getItem(JOB_STORAGE_KEY))
  const [addStarting, setAddStarting] = useState(false)
  const [addStartError, setAddStartError] = useState<string | null>(null)

  // Item-IDs job state
  const [itemJobVideoId, setItemJobVideoId] = useState('')
  const [itemJobText, setItemJobText] = useState('')
  const [itemJobId, setItemJobId] = useState<string | null>(() => localStorage.getItem(JOB_STORAGE_KEY + '_items'))
  const [itemJobStarting, setItemJobStarting] = useState(false)
  const [itemJobStartError, setItemJobStartError] = useState<string | null>(null)

  // Remove state (still streaming)
  const [itemListText, setItemListText] = useState('')
  const [removing, setRemoving] = useState(false)
  const [removeLog, setRemoveLog] = useState<string[]>([])
  const [removeSummary, setRemoveSummary] = useState<string | null>(null)
  const [removeError, setRemoveError] = useState<string | null>(null)

  const parsedIds = parseItemIdsFromText(itemListText)
  const parsedItemJobIds = parseItemIdsFromText(itemJobText)

  // Persist job IDs
  useEffect(() => {
    if (addJobId) localStorage.setItem(JOB_STORAGE_KEY, addJobId)
    else localStorage.removeItem(JOB_STORAGE_KEY)
  }, [addJobId])

  useEffect(() => {
    if (itemJobId) localStorage.setItem(JOB_STORAGE_KEY + '_items', itemJobId)
    else localStorage.removeItem(JOB_STORAGE_KEY + '_items')
  }, [itemJobId])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const value = input.trim()
    if (!value) return
    setError(null)
    setResult(null)
    setLoading(true)
    try {
      const res = await listingVideoAPI.getVideoId(value)
      setResult(res.data)
      if (res.data.video_ids.length > 0) setAddVideoId(res.data.video_ids[0])
      if (res.data.video_ids.length > 0) setItemJobVideoId(res.data.video_ids[0])
      if (res.data.sku) setAddSku(res.data.sku)
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string }; status?: number } }
      const detail = ax.response?.data?.detail
      setError(typeof detail === 'string' ? detail : detail ? String(detail) : 'Failed to get video ID')
    } finally {
      setLoading(false)
    }
  }

  const handleStartSkuJob = async () => {
    const videoId = addVideoId.trim()
    const sku = addSku.trim()
    if (!videoId || !sku || addStarting) return
    const ok = window.confirm(
      `Add video to all active listings with SKU "${sku}"? This revises every matching listing.`,
    )
    if (!ok) return
    setAddStarting(true)
    setAddStartError(null)
    try {
      const res = await listingVideoJobAPI.start({
        video_id: videoId,
        sku,
      })
      setAddJobId(res.data.job_id)
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string } }; message?: string }
      const detail = ax.response?.data?.detail ?? ax.message ?? 'Failed to start job'
      setAddStartError(typeof detail === 'string' ? detail : String(detail))
    } finally {
      setAddStarting(false)
    }
  }

  const handleStartItemJob = async () => {
    if (parsedItemJobIds.length === 0 || itemJobStarting) return
    const videoId = itemJobVideoId.trim()
    if (!videoId) return
    const ok = window.confirm(
      `Add video to ${parsedItemJobIds.length} listing(s) by item ID?`,
    )
    if (!ok) return
    setItemJobStarting(true)
    setItemJobStartError(null)
    try {
      const res = await listingVideoJobAPI.start({
        video_id: videoId,
        item_ids: parsedItemJobIds,
      })
      setItemJobId(res.data.job_id)
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string } }; message?: string }
      const detail = ax.response?.data?.detail ?? ax.message ?? 'Failed to start job'
      setItemJobStartError(typeof detail === 'string' ? detail : String(detail))
    } finally {
      setItemJobStarting(false)
    }
  }

  const onFile = async (file: File | null) => {
    if (!file) return
    const text = await file.text()
    setItemListText((prev) => (prev.trim() ? `${prev.trim()}\n${text}` : text))
  }

  const handleRemove = async () => {
    if (parsedIds.length === 0 || removing) return
    const ok = window.confirm(
      `Remove videos from ${parsedIds.length} listing${parsedIds.length === 1 ? '' : 's'} on eBay?`,
    )
    if (!ok) return
    setRemoving(true)
    setRemoveError(null)
    setRemoveSummary(null)
    setRemoveLog([])
    try {
      await listingVideoAPI.removeVideoFromListingsStream(parsedIds, (ev: RemoveVideoFromListingsEvent) => {
        if (ev.type === 'progress') {
          setRemoveLog((prev) => [...prev, ev.message])
        } else if (ev.type === 'error') {
          setRemoveError(ev.detail)
        } else if (ev.type === 'done') {
          const skipped = ev.skipped ?? 0
          setRemoveSummary(
            `Done. Removed ${ev.updated} of ${ev.total}. Skipped (no video): ${skipped}. Failed: ${ev.failed.length}.`,
          )
          if (ev.failed.length) {
            setRemoveLog((prev) => [...prev, `Failed IDs: ${ev.failed.join(', ')}`])
          }
        }
      })
    } catch (err: unknown) {
      setRemoveError(err instanceof Error ? err.message : 'Remove videos failed')
    } finally {
      setRemoving(false)
    }
  }

  const Heading = embedded ? 'h2' : 'h1'

  return (
    <div className={embedded ? '' : 'px-4 py-6 sm:px-0'}>
      <Heading className={`font-bold text-gray-900 mb-2 ${embedded ? 'text-xl' : 'text-2xl'}`}>
        Listing videos
      </Heading>
      <p className="text-sm text-gray-600 mb-6">
        Look up a video ID, push it to every listing for a SKU, add it to specific listings by item ID, or remove
        videos. Jobs run on the server — safe to close your laptop and come back later.
      </p>

      {/* Get video ID */}
      <section className="bg-white rounded-lg border border-gray-200 p-6 max-w-2xl mb-6">
        <h3 className="text-base font-semibold text-gray-900 mb-3">Get video ID</h3>
        <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 flex-1 min-w-[280px]">
            <span className="text-sm font-medium text-gray-700">Listing URL or item number</span>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="https://www.ebay.co.uk/itm/136528644539 or 136528644539"
              className="rounded border border-gray-300 px-3 py-2"
            />
          </label>
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? 'Loading…' : 'Get video ID'}
          </button>
        </form>
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
        {result && (
          <div className="mt-4 p-3 bg-gray-50 rounded border border-gray-200">
            {result.title && <p className="text-sm text-gray-600 mb-1">{result.title}</p>}
            {result.sku && (
              <p className="text-sm text-gray-600 mb-1">
                <strong>SKU:</strong>{' '}
                <code className="bg-white px-1.5 py-0.5 rounded border border-gray-200 font-mono text-sm">
                  {result.sku}
                </code>
              </p>
            )}
            {result.video_ids.length > 0 ? (
              <p className="text-sm">
                <strong>Video ID(s):</strong>{' '}
                {result.video_ids.map((id) => (
                  <code key={id} className="bg-white px-1.5 py-0.5 rounded border border-gray-200 font-mono text-sm mr-1">
                    {id}
                  </code>
                ))}
              </p>
            ) : (
              <p className="text-sm text-amber-600">No video on this listing.</p>
            )}
          </div>
        )}
      </section>

      {/* Add video to SKU — job-based */}
      <section className="bg-white rounded-lg border border-gray-200 p-6 max-w-2xl mb-6">
        <h3 className="text-base font-semibold text-gray-900 mb-1">Add video to SKU</h3>
        <p className="text-sm text-gray-600 mb-4">
          Finds all active listings with this SKU and adds the video. Runs as a server job — safe to close your
          browser. Progress reloads automatically on return.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium text-gray-700">Video ID</span>
            <input
              type="text"
              value={addVideoId}
              onChange={(e) => setAddVideoId(e.target.value)}
              placeholder="Exact video ID"
              className="rounded border border-gray-300 px-3 py-2 font-mono text-sm"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium text-gray-700">SKU</span>
            <input
              type="text"
              value={addSku}
              onChange={(e) => setAddSku(e.target.value)}
              placeholder="e.g. uke03"
              className="rounded border border-gray-300 px-3 py-2 font-mono text-sm"
            />
          </label>
        </div>
        <button
          type="button"
          disabled={addStarting || !addVideoId.trim() || !addSku.trim()}
          onClick={() => void handleStartSkuJob()}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {addStarting ? 'Starting…' : 'Add to all listings with this SKU'}
        </button>
        {addStartError && <p className="mt-3 text-sm text-red-600">{addStartError}</p>}
        {addJobId && (
          <JobPanel
            jobId={addJobId}
            onClear={() => setAddJobId(null)}
          />
        )}
      </section>

      {/* Add video to specific item IDs — job-based */}
      <section className="bg-white rounded-lg border border-gray-200 p-6 max-w-2xl mb-6">
        <h3 className="text-base font-semibold text-gray-900 mb-1">Add video to specific listings</h3>
        <p className="text-sm text-gray-600 mb-4">
          Paste item numbers or listing URLs (one per line). Useful when only a few listings need the video rather
          than the full SKU. Listings that already have this video are skipped automatically.
        </p>
        <label className="flex flex-col gap-1 mb-3">
          <span className="text-sm font-medium text-gray-700">Video ID</span>
          <input
            type="text"
            value={itemJobVideoId}
            onChange={(e) => setItemJobVideoId(e.target.value)}
            placeholder="Exact video ID"
            className="rounded border border-gray-300 px-3 py-2 font-mono text-sm max-w-sm"
          />
        </label>
        <label className="flex flex-col gap-1 mb-3">
          <span className="text-sm font-medium text-gray-700">Item IDs</span>
          <textarea
            value={itemJobText}
            onChange={(e) => setItemJobText(e.target.value)}
            rows={5}
            placeholder={'136528644539\nhttps://www.ebay.co.uk/itm/135094023963'}
            className="w-full rounded border border-gray-300 px-3 py-2 font-mono text-sm"
          />
        </label>
        <div className="flex items-center gap-3">
          <button
            type="button"
            disabled={itemJobStarting || parsedItemJobIds.length === 0 || !itemJobVideoId.trim()}
            onClick={() => void handleStartItemJob()}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {itemJobStarting ? 'Starting…' : `Add video to ${parsedItemJobIds.length} listing(s)`}
          </button>
          <span className="text-sm text-gray-500 tabular-nums">
            {parsedItemJobIds.length} valid ID{parsedItemJobIds.length === 1 ? '' : 's'}
          </span>
        </div>
        {itemJobStartError && <p className="mt-3 text-sm text-red-600">{itemJobStartError}</p>}
        {itemJobId && (
          <JobPanel
            jobId={itemJobId}
            onClear={() => setItemJobId(null)}
          />
        )}
      </section>

      {/* Remove videos (still streaming) */}
      <section className="bg-white rounded-lg border border-gray-200 p-6 max-w-2xl">
        <h3 className="text-base font-semibold text-gray-900 mb-1">Remove videos</h3>
        <p className="text-sm text-gray-600 mb-4">
          Paste item IDs or listing URLs (one per line or comma-separated), or upload a text/CSV file. Then confirm
          to revise each listing and drop its video.
        </p>
        <label className="block text-sm font-medium text-gray-700 mb-1">Item ID list</label>
        <textarea
          value={itemListText}
          onChange={(e) => setItemListText(e.target.value)}
          rows={8}
          placeholder={'136528644539\nhttps://www.ebay.co.uk/itm/135094023963'}
          className="w-full rounded border border-gray-300 px-3 py-2 font-mono text-sm mb-3"
        />
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <label className="text-sm text-gray-700">
            <span className="sr-only">Upload item ID file</span>
            <input
              type="file"
              accept=".txt,.csv,text/plain,text/csv"
              onChange={(e) => {
                const f = e.target.files?.[0] ?? null
                void onFile(f)
                e.target.value = ''
              }}
              className="text-sm"
            />
          </label>
          <span className="text-sm text-gray-500 tabular-nums">
            {parsedIds.length} valid ID{parsedIds.length === 1 ? '' : 's'}
          </span>
          <button
            type="button"
            disabled={removing || parsedIds.length === 0}
            onClick={() => void handleRemove()}
            className="px-4 py-2 bg-red-700 text-white rounded hover:bg-red-800 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {removing ? 'Removing…' : 'Remove videos'}
          </button>
        </div>
        {removeError && <p className="text-sm text-red-600 mb-2">{removeError}</p>}
        {removeSummary && <p className="text-sm text-gray-800 mb-2">{removeSummary}</p>}
        {removeLog.length > 0 && (
          <div className="relative">
            <button
              type="button"
              onClick={() => setRemoveLog([])}
              className="absolute top-1 right-1 text-xs text-gray-400 underline hover:text-gray-600"
            >
              Clear
            </button>
            <pre className="max-h-48 overflow-y-auto text-xs bg-gray-50 border border-gray-200 rounded p-3 whitespace-pre-wrap">
              {removeLog.join('\n')}
            </pre>
          </div>
        )}
      </section>
    </div>
  )
}
