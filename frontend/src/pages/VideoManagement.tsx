import { useState } from 'react'
import { listingVideoAPI, type VideoIdResponse, type AddVideoToSkuResponse } from '../services/api'

export default function VideoManagement() {
  const [input, setInput] = useState('')
  const [result, setResult] = useState<VideoIdResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const [videoIdForAdd, setVideoIdForAdd] = useState('')
  const [skuForAdd, setSkuForAdd] = useState('')
  const [addResult, setAddResult] = useState<AddVideoToSkuResponse | null>(null)
  const [addError, setAddError] = useState<string | null>(null)
  const [addLoading, setAddLoading] = useState(false)

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
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string }; status?: number } }
      const detail = ax.response?.data?.detail
      setError(typeof detail === 'string' ? detail : detail ? String(detail) : 'Failed to get video ID')
    } finally {
      setLoading(false)
    }
  }

  const handleAddVideoToSku = async (e: React.FormEvent) => {
    e.preventDefault()
    const vid = videoIdForAdd.trim()
    const sku = skuForAdd.trim()
    if (!vid || !sku) return
    setAddError(null)
    setAddResult(null)
    setAddLoading(true)
    try {
      const res = await listingVideoAPI.addVideoToSku(vid, sku)
      setAddResult(res.data)
    } catch (err: unknown) {
      const ax = err as { response?: { data?: { detail?: string }; status?: number } }
      const detail = ax.response?.data?.detail
      setAddError(typeof detail === 'string' ? detail : detail ? String(detail) : 'Failed to add video to SKU')
    } finally {
      setAddLoading(false)
    }
  }

  return (
    <div className="px-4 py-6 sm:px-0">
      <h1 className="text-2xl font-bold text-gray-900 mb-2">Video management</h1>
      <p className="text-sm text-gray-600 mb-6">
        Get a video ID from a listing, then add that video to all listings for a SKU (one inventory item per SKU; ~10 SKUs across 2k+ listings).
      </p>

      <section className="bg-white rounded-lg border border-gray-200 p-6 max-w-2xl mb-8">
        <h2 className="text-lg font-semibold text-gray-900 mb-2">1. Get video ID from listing</h2>
        <p className="text-sm text-gray-600 mb-3">
          Paste a listing URL, item number, or SKU. Copy the video ID(s) to use below.
        </p>
        <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 flex-1 min-w-[280px]">
            <span className="text-sm font-medium text-gray-700">Listing URL or item number</span>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="https://www.ebay.co.uk/itm/136528644539 or uke03"
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
            {result.video_ids.length > 0 ? (
              <p className="text-sm">
                <strong>Video ID(s):</strong>{' '}
                {result.video_ids.map((id) => (
                  <code key={id} className="bg-white px-1.5 py-0.5 rounded border border-gray-200 font-mono text-sm">
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

      <section className="bg-white rounded-lg border border-gray-200 p-6 max-w-2xl">
        <h2 className="text-lg font-semibold text-gray-900 mb-2">2. Add video to all listings for a SKU</h2>
        <p className="text-sm text-gray-600 mb-3">
          Enter a video ID (from above or paste one) and a SKU. The video will be added to the inventory item for that SKU; all listings using this SKU will show the video.
        </p>
        <form onSubmit={handleAddVideoToSku} className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 min-w-[200px]">
            <span className="text-sm font-medium text-gray-700">Video ID</span>
            <input
              type="text"
              value={videoIdForAdd}
              onChange={(e) => setVideoIdForAdd(e.target.value)}
              placeholder="e8835dc819c0a49f652575e8fffff7a1"
              className="rounded border border-gray-300 px-3 py-2 font-mono text-sm"
            />
          </label>
          <label className="flex flex-col gap-1 min-w-[120px]">
            <span className="text-sm font-medium text-gray-700">SKU</span>
            <input
              type="text"
              value={skuForAdd}
              onChange={(e) => setSkuForAdd(e.target.value)}
              placeholder="uke03"
              className="rounded border border-gray-300 px-3 py-2"
            />
          </label>
          <button
            type="submit"
            disabled={addLoading || !videoIdForAdd.trim() || !skuForAdd.trim()}
            className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {addLoading ? 'Adding…' : 'Add video to SKU'}
          </button>
        </form>
        {addError && <p className="mt-3 text-sm text-red-600">{addError}</p>}
        {addResult && (
          <div className="mt-4 p-3 bg-gray-50 rounded border border-gray-200">
            <p className="text-sm text-green-700 font-medium">Video added to SKU {addResult.sku}</p>
            <p className="text-sm text-gray-600 mt-1">
              All listings using this SKU now have video ID(s):{' '}
              {addResult.video_ids.map((id) => (
                <code key={id} className="bg-white px-1.5 py-0.5 rounded border border-gray-200 font-mono text-sm">
                  {id}
                </code>
              ))}
            </p>
          </div>
        )}
      </section>
    </div>
  )
}
