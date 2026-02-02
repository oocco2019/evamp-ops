import { useState, useEffect, useCallback } from 'react'
import { stockAPI, type SKU } from '../services/api'

interface PlanRow {
  sku_code: string
  title: string
  landed_cost: number
  profit_per_unit: number
  units: number
}

export default function StockPlanning() {
  const [skus, setSkus] = useState<SKU[]>([])
  const [planRows, setPlanRows] = useState<PlanRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [showMessageModal, setShowMessageModal] = useState(false)
  const [orderMessage, setOrderMessage] = useState('')
  const [generatingMessage, setGeneratingMessage] = useState(false)

  const loadSkus = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await stockAPI.listSKUs()
      const sorted = [...res.data].sort((a, b) => a.sku_code.localeCompare(b.sku_code))
      setSkus(sorted)
      // Initialize plan rows with units = 0
      setPlanRows(
        sorted.map((s) => ({
          sku_code: s.sku_code,
          title: s.title,
          landed_cost: Number(s.landed_cost) || 0,
          profit_per_unit: Number(s.profit_per_unit) || 0,
          units: 0,
        }))
      )
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load SKUs')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadSkus()
  }, [loadSkus])

  const updateUnits = (skuCode: string, units: number) => {
    setPlanRows((prev) =>
      prev.map((row) => (row.sku_code === skuCode ? { ...row, units: Math.max(0, units) } : row))
    )
  }

  // Calculate totals
  const calculateCost = (row: PlanRow) => row.landed_cost * row.units
  const calculateCostUSD = (row: PlanRow) => calculateCost(row) * 1.35
  const calculateProfit = (row: PlanRow) => row.units * row.profit_per_unit * 0.8

  const totalUnits = planRows.reduce((sum, r) => sum + r.units, 0)
  const totalCost = planRows.reduce((sum, r) => sum + calculateCost(r), 0)
  const totalCostUSD = planRows.reduce((sum, r) => sum + calculateCostUSD(r), 0)
  const totalProfit = planRows.reduce((sum, r) => sum + calculateProfit(r), 0)

  // Only show rows with units > 0 in summary
  const activeRows = planRows.filter((r) => r.units > 0)

  const handleCopyPlan = () => {
    if (activeRows.length === 0) return
    const lines = activeRows.map(
      (r) => `${r.sku_code}\t${r.title}\t${r.units}\t${calculateCost(r).toFixed(2)}`
    )
    const text = `SKU\tTitle\tUnits\tCost\n${lines.join('\n')}\n\nTotal: ${totalUnits} units, Cost: ${totalCost.toFixed(2)}`
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleClearAll = () => {
    setPlanRows((prev) => prev.map((row) => ({ ...row, units: 0 })))
  }

  const handleGenerateOrderMessage = async () => {
    if (activeRows.length === 0) return
    setGeneratingMessage(true)
    setError(null)
    try {
      const items = activeRows.map((r) => ({
        sku_code: r.sku_code,
        title: r.title,
        quantity: r.units,
      }))
      const res = await stockAPI.generateOrderMessage(items)
      setOrderMessage(res.data.message)
      setShowMessageModal(true)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to generate message')
    } finally {
      setGeneratingMessage(false)
    }
  }

  const handleCopyMessage = () => {
    navigator.clipboard.writeText(orderMessage)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="px-4 py-6 sm:px-0">
      <h1 className="text-3xl font-bold text-gray-900 mb-4">Stock Planning</h1>
      <p className="text-gray-600 mb-6">
        Enter units to order for each SKU. Costs and profit are calculated automatically.
      </p>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          {error}
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-white shadow rounded-lg p-4">
          <p className="text-sm text-gray-500">Total Units</p>
          <p className="text-2xl font-bold text-gray-900">{totalUnits}</p>
        </div>
        <div className="bg-white shadow rounded-lg p-4">
          <p className="text-sm text-gray-500">Total Cost</p>
          <p className="text-2xl font-bold text-gray-900">{totalCost.toFixed(2)}</p>
        </div>
        <div className="bg-white shadow rounded-lg p-4">
          <p className="text-sm text-gray-500">Cost USD (×1.35)</p>
          <p className="text-2xl font-bold text-gray-900">{totalCostUSD.toFixed(2)}</p>
        </div>
        <div className="bg-white shadow rounded-lg p-4">
          <p className="text-sm text-gray-500">Est. Profit (×0.8)</p>
          <p className="text-2xl font-bold text-green-600">{totalProfit.toFixed(2)}</p>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex gap-2 mb-4">
        <button
          type="button"
          onClick={handleGenerateOrderMessage}
          disabled={activeRows.length === 0 || generatingMessage}
          className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 text-sm font-medium"
        >
          {generatingMessage ? 'Generating...' : 'Generate supplier order'}
        </button>
        <button
          type="button"
          onClick={handleCopyPlan}
          disabled={activeRows.length === 0}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-sm font-medium"
        >
          {copied ? 'Copied!' : 'Copy plan to clipboard'}
        </button>
        <button
          type="button"
          onClick={handleClearAll}
          disabled={totalUnits === 0}
          className="px-4 py-2 bg-gray-100 text-gray-700 rounded hover:bg-gray-200 disabled:opacity-50 text-sm font-medium"
        >
          Clear all
        </button>
      </div>

      {/* Order Message Modal */}
      {showMessageModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] flex flex-col">
            <div className="p-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-800">Supplier Order Message</h3>
              <button
                type="button"
                onClick={() => setShowMessageModal(false)}
                className="text-gray-500 hover:text-gray-700"
              >
                &times;
              </button>
            </div>
            <div className="p-4 flex-1 overflow-y-auto">
              <textarea
                value={orderMessage}
                onChange={(e) => setOrderMessage(e.target.value)}
                className="w-full h-64 rounded border border-gray-300 px-3 py-2 text-sm font-mono"
                placeholder="Order message..."
              />
            </div>
            <div className="p-4 border-t border-gray-200 flex gap-2 justify-end">
              <button
                type="button"
                onClick={handleCopyMessage}
                className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm font-medium"
              >
                {copied ? 'Copied!' : 'Copy to clipboard'}
              </button>
              <button
                type="button"
                onClick={() => setShowMessageModal(false)}
                className="px-4 py-2 bg-gray-100 text-gray-700 rounded hover:bg-gray-200 text-sm font-medium"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* SKU Table */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        {loading ? (
          <div className="p-6 text-gray-500">Loading SKUs...</div>
        ) : planRows.length === 0 ? (
          <div className="p-6 text-gray-500">No SKUs found. Add SKUs in the SKU Manager first.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead>
                <tr className="bg-gray-50">
                  <th className="px-4 py-3 text-left font-medium text-gray-700">SKU</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-700">Title</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">Landed Cost</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">Units</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">Cost</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">Cost USD</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">Profit</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {planRows.map((row) => {
                  const cost = calculateCost(row)
                  const costUSD = calculateCostUSD(row)
                  const profit = calculateProfit(row)
                  return (
                    <tr
                      key={row.sku_code}
                      className={row.units > 0 ? 'bg-blue-50' : 'hover:bg-gray-50'}
                    >
                      <td className="px-4 py-2 font-medium text-gray-900">{row.sku_code}</td>
                      <td className="px-4 py-2 text-gray-700 max-w-xs truncate" title={row.title}>
                        {row.title}
                      </td>
                      <td className="px-4 py-2 text-right text-gray-600">
                        {row.landed_cost.toFixed(2)}
                      </td>
                      <td className="px-4 py-2 text-right">
                        <input
                          type="number"
                          min={0}
                          value={row.units || ''}
                          onChange={(e) =>
                            updateUnits(row.sku_code, parseInt(e.target.value, 10) || 0)
                          }
                          className="w-20 rounded border border-gray-300 px-2 py-1 text-right text-sm"
                          placeholder="0"
                        />
                      </td>
                      <td className="px-4 py-2 text-right text-gray-700">
                        {row.units > 0 ? cost.toFixed(2) : '-'}
                      </td>
                      <td className="px-4 py-2 text-right text-gray-700">
                        {row.units > 0 ? costUSD.toFixed(2) : '-'}
                      </td>
                      <td className="px-4 py-2 text-right text-green-600 font-medium">
                        {row.units > 0 ? profit.toFixed(2) : '-'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
              {totalUnits > 0 && (
                <tfoot>
                  <tr className="bg-gray-100 font-semibold">
                    <td className="px-4 py-3" colSpan={3}>
                      Totals
                    </td>
                    <td className="px-4 py-3 text-right">{totalUnits}</td>
                    <td className="px-4 py-3 text-right">{totalCost.toFixed(2)}</td>
                    <td className="px-4 py-3 text-right">{totalCostUSD.toFixed(2)}</td>
                    <td className="px-4 py-3 text-right text-green-600">{totalProfit.toFixed(2)}</td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
