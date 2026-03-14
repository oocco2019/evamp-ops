import { useState } from 'react'
import { listingVideoAPI, type VideoIdResponse } from '../services/api'

export default function VideoManagement() {
  const [input, setInput] = useState('')
  const [result, setResult] = useState<VideoIdResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

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

  return (
    <div className="px-4 py-6 sm:px-0">
      <h1 className="text-2xl font-bold text-gray-900 mb-2">Video ID getter</h1>
      <p className="text-sm text-gray-600 mb-6">
        Paste a listing URL or item number to get the video ID(s) for that listing.
      </p>

      <section className="bg-white rounded-lg border border-gray-200 p-6 max-w-2xl">
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
    </div>
  )
}
