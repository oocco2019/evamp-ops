import { useState, useEffect, useCallback } from 'react'
import { stockAPI, type PurchaseOrder } from '../services/api'

export default function SupplierOrders() {
  const [orders, setOrders] = useState<PurchaseOrder[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [formOrderDate, setFormOrderDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [formOrderValue, setFormOrderValue] = useState('')
  const [formLeadTime, setFormLeadTime] = useState(90)
  const [formLines, setFormLines] = useState<{ sku_code: string; quantity: number }[]>([
    { sku_code: '', quantity: 1 },
  ])
  const [submitting, setSubmitting] = useState(false)

  const refreshOrders = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await stockAPI.listPurchaseOrders(
        statusFilter.trim() || undefined
      )
      setOrders(res.data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load purchase orders')
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => {
    refreshOrders()
  }, [refreshOrders])

  const addLine = () => {
    setFormLines((prev) => [...prev, { sku_code: '', quantity: 1 }])
  }

  const updateLine = (index: number, field: 'sku_code' | 'quantity', value: string | number) => {
    setFormLines((prev) => {
      const next = [...prev]
      if (field === 'quantity') next[index].quantity = Math.max(1, Number(value) || 1)
      else next[index].sku_code = String(value)
      return next
    })
  }

  const removeLine = (index: number) => {
    if (formLines.length <= 1) return
    setFormLines((prev) => prev.filter((_, i) => i !== index))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const validLines = formLines.filter((l) => l.sku_code.trim())
    if (validLines.length === 0) {
      setError('Add at least one line with a SKU')
      return
    }
    if (!formOrderValue.trim() || parseFloat(formOrderValue) < 0) {
      setError('Order value must be a positive number')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await stockAPI.createPurchaseOrder({
        order_date: formOrderDate,
        order_value: formOrderValue.trim(),
        lead_time_days: formLeadTime,
        line_items: validLines.map((l) => ({ sku_code: l.sku_code.trim(), quantity: l.quantity })),
      })
      setShowForm(false)
      setFormOrderValue('')
      setFormLines([{ sku_code: '', quantity: 1 }])
      refreshOrders()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to create purchase order')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (id: number) => {
    if (!window.confirm('Delete this purchase order?')) return
    try {
      await stockAPI.deletePurchaseOrder(id)
      refreshOrders()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to delete')
    }
  }

  return (
    <div className="px-4 py-6 sm:px-0">
      <h1 className="text-3xl font-bold text-gray-900 mb-4">Supplier Orders</h1>
      <p className="text-gray-600 mb-6">
        Create and manage purchase orders (SM06-SM07).
      </p>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          {error}
        </div>
      )}

      <div className="flex flex-wrap gap-2 mb-4">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded border border-gray-300 px-3 py-2 text-sm"
        >
          <option value="">All statuses</option>
          <option value="In Progress">In Progress</option>
          <option value="Done">Done</option>
        </select>
        <button
          type="button"
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm font-medium"
        >
          {showForm ? 'Cancel' : 'New purchase order'}
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="bg-white shadow rounded-lg p-4 mb-6 max-w-2xl"
        >
          <h2 className="text-lg font-semibold text-gray-800 mb-3">New purchase order</h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Order date</label>
              <input
                type="date"
                value={formOrderDate}
                onChange={(e) => setFormOrderDate(e.target.value)}
                required
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Order value</label>
              <input
                type="text"
                value={formOrderValue}
                onChange={(e) => setFormOrderValue(e.target.value)}
                placeholder="0.00"
                required
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Lead time (days)</label>
              <input
                type="number"
                min={0}
                value={formLeadTime}
                onChange={(e) => setFormLeadTime(parseInt(e.target.value, 10) || 0)}
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
          </div>
          <div className="mb-3">
            <div className="flex justify-between items-center mb-2">
              <span className="text-sm font-medium text-gray-700">Line items</span>
              <button type="button" onClick={addLine} className="text-sm text-blue-600 hover:underline">
                Add line
              </button>
            </div>
            <div className="space-y-2">
              {formLines.map((line, i) => (
                <div key={i} className="flex gap-2 items-center">
                  <input
                    type="text"
                    value={line.sku_code}
                    onChange={(e) => updateLine(i, 'sku_code', e.target.value)}
                    placeholder="SKU code"
                    className="flex-1 rounded border border-gray-300 px-3 py-2 text-sm"
                  />
                  <input
                    type="number"
                    min={1}
                    value={line.quantity}
                    onChange={(e) => updateLine(i, 'quantity', e.target.value)}
                    className="w-20 rounded border border-gray-300 px-3 py-2 text-sm"
                  />
                  <button
                    type="button"
                    onClick={() => removeLine(i)}
                    disabled={formLines.length <= 1}
                    className="text-red-600 hover:underline disabled:opacity-50 text-sm"
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 text-sm font-medium"
          >
            {submitting ? 'Creating...' : 'Create'}
          </button>
        </form>
      )}

      <div className="bg-white shadow rounded-lg overflow-hidden">
        {loading ? (
          <div className="p-6 text-gray-500">Loading...</div>
        ) : orders.length === 0 ? (
          <div className="p-6 text-gray-500">No purchase orders. Create one to get started.</div>
        ) : (
          <ul className="divide-y divide-gray-200">
            {orders.map((po) => (
              <li key={po.id} className="p-4 flex flex-wrap justify-between items-start gap-2">
                <div>
                  <p className="font-medium text-gray-900">
                    PO #{po.id} – {po.order_date} – {po.status}
                  </p>
                  <p className="text-sm text-gray-600">
                    Value: {po.order_value} · Lead time: {po.lead_time_days} days
                    {po.actual_delivery_date && ` · Delivered: ${po.actual_delivery_date}`}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {po.line_items.map((li) => `${li.sku_code} × ${li.quantity}`).join(', ')}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => handleDelete(po.id)}
                  className="text-sm text-red-600 hover:underline"
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
