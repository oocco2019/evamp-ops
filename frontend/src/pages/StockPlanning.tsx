import { useState } from 'react'
import { stockAPI, type VelocityResult } from '../services/api'

const defaultFrom = () => {
  const d = new Date()
  d.setDate(d.getDate() - 30)
  return d.toISOString().slice(0, 10)
}
const defaultTo = () => new Date().toISOString().slice(0, 10)

export default function StockPlanning() {
  const [sku, setSku] = useState('')
  const [from, setFrom] = useState(defaultFrom())
  const [to, setTo] = useState(defaultTo())
  const [weeks, setWeeks] = useState(4)
  const [result, setResult] = useState<VelocityResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleCalculate = async () => {
    if (!sku.trim()) {
      setError('Enter a SKU')
      return
    }
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await stockAPI.getVelocity(sku.trim(), from, to)
      setResult(res.data)
    } catch (e: unknown) {
      setResult(null)
      setError(e instanceof Error ? e.message : 'Failed to load velocity')
    } finally {
      setLoading(false)
    }
  }

  const suggestedQty =
    result != null ? Math.ceil(weeks * result.units_per_day * 7) : null

  return (
    <div className="px-4 py-6 sm:px-0">
      <h1 className="text-3xl font-bold text-gray-900 mb-4">Stock Planning</h1>
      <p className="text-gray-600 mb-6">
        Use sales velocity to estimate how many units to order. Based on units sold over a date range.
      </p>

      <div className="bg-white shadow rounded-lg p-4 mb-6 max-w-xl">
        <h2 className="text-lg font-semibold text-gray-800 mb-3">Velocity & suggested order</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">SKU</label>
            <input
              type="text"
              value={sku}
              onChange={(e) => setSku(e.target.value)}
              placeholder="e.g. WIDGET-01"
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">From</label>
            <input
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">To</label>
            <input
              type="date"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Weeks of stock to cover</label>
            <input
              type="number"
              min={1}
              max={52}
              value={weeks}
              onChange={(e) => setWeeks(parseInt(e.target.value, 10) || 1)}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
        </div>
        <button
          type="button"
          onClick={handleCalculate}
          disabled={loading}
          className="mt-3 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-sm font-medium"
        >
          {loading ? 'Calculating...' : 'Calculate'}
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          {error}
        </div>
      )}

      {result && (
        <div className="bg-white shadow rounded-lg p-4 max-w-xl">
          <h3 className="font-semibold text-gray-800 mb-2">Results for {result.sku}</h3>
          <ul className="space-y-1 text-sm text-gray-700">
            <li>Units sold in period: <strong>{result.units_sold}</strong></li>
            <li>Days in period: <strong>{result.days}</strong></li>
            <li>Units per day: <strong>{result.units_per_day}</strong></li>
            <li className="pt-2 border-t border-gray-200">
              Suggested order quantity ({weeks} weeks):{' '}
              <strong className="text-blue-600">{suggestedQty ?? 0} units</strong>
            </li>
          </ul>
        </div>
      )}
    </div>
  )
}
