import { useState, useEffect, useCallback, useMemo } from 'react'
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
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

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

  // Pipeline metrics
  const metrics = useMemo(() => {
    const inProgressOrders = orders.filter((o) => o.status === 'In Progress')
    const today = new Date()
    
    const totalUnitsInbound = inProgressOrders.reduce(
      (sum, o) => sum + o.line_items.reduce((s, li) => s + li.quantity, 0),
      0
    )
    const totalValueInbound = inProgressOrders.reduce(
      (sum, o) => sum + parseFloat(o.order_value || '0'),
      0
    )
    
    // Overdue = order_date + lead_time_days < today
    const overduePOs = inProgressOrders.filter((o) => {
      const orderDate = new Date(o.order_date)
      orderDate.setDate(orderDate.getDate() + o.lead_time_days)
      return orderDate < today
    })
    const overdueCount = overduePOs.length
    const overdueValue = overduePOs.reduce(
      (sum, o) => sum + parseFloat(o.order_value || '0'),
      0
    )
    
    // Average lead time (for completed orders)
    const completedOrders = orders.filter((o) => o.status === 'Done' && o.actual_delivery_date)
    let avgLeadTime = 0
    if (completedOrders.length > 0) {
      const totalDays = completedOrders.reduce((sum, o) => {
        const orderDate = new Date(o.order_date)
        const deliveryDate = new Date(o.actual_delivery_date!)
        const days = Math.floor((deliveryDate.getTime() - orderDate.getTime()) / (1000 * 60 * 60 * 24))
        return sum + days
      }, 0)
      avgLeadTime = Math.round(totalDays / completedOrders.length)
    }
    
    return { totalUnitsInbound, totalValueInbound, overdueCount, overdueValue, avgLeadTime }
  }, [orders])

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

  const handleToggleStatus = async (po: PurchaseOrder) => {
    const newStatus = po.status === 'In Progress' ? 'Done' : 'In Progress'
    const deliveryDate = newStatus === 'Done' ? new Date().toISOString().slice(0, 10) : undefined
    try {
      await stockAPI.updatePurchaseOrder(po.id, {
        status: newStatus,
        actual_delivery_date: deliveryDate,
      })
      refreshOrders()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to update status')
    }
  }

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleExportCSV = () => {
    const exportOrders = selectedIds.size > 0 
      ? orders.filter((o) => selectedIds.has(o.id))
      : orders
    
    const rows = [
      ['PO ID', 'Status', 'Order Date', 'Order Value', 'Deposit (20%)', 'Final (80%)', 'Lead Time', 'Delivery Date', 'SKUs'].join(','),
    ]
    for (const po of exportOrders) {
      const value = parseFloat(po.order_value || '0')
      const deposit = (value * 0.2).toFixed(2)
      const final = (value * 0.8).toFixed(2)
      const skus = po.line_items.map((li) => `${li.sku_code}x${li.quantity}`).join('; ')
      rows.push([
        po.id,
        po.status,
        po.order_date,
        po.order_value,
        deposit,
        final,
        po.lead_time_days,
        po.actual_delivery_date || '',
        `"${skus}"`,
      ].join(','))
    }
    
    const csv = rows.join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `purchase_orders_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const getETA = (po: PurchaseOrder) => {
    const orderDate = new Date(po.order_date)
    orderDate.setDate(orderDate.getDate() + po.lead_time_days)
    return orderDate.toISOString().slice(0, 10)
  }

  const isOverdue = (po: PurchaseOrder) => {
    if (po.status === 'Done') return false
    const eta = new Date(getETA(po))
    return eta < new Date()
  }

  return (
    <div className="px-4 py-6 sm:px-0">
      <h1 className="text-3xl font-bold text-gray-900 mb-4">Supplier Orders</h1>
      <p className="text-gray-600 mb-6">
        Track purchase orders from suppliers.
      </p>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          {error}
        </div>
      )}

      {/* Pipeline Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        <div className="bg-white shadow rounded-lg p-4">
          <p className="text-sm text-gray-500">Units Inbound</p>
          <p className="text-2xl font-bold text-gray-900">{metrics.totalUnitsInbound}</p>
        </div>
        <div className="bg-white shadow rounded-lg p-4">
          <p className="text-sm text-gray-500">Value Inbound</p>
          <p className="text-2xl font-bold text-gray-900">{metrics.totalValueInbound.toFixed(2)}</p>
        </div>
        <div className="bg-white shadow rounded-lg p-4">
          <p className="text-sm text-gray-500">Overdue POs</p>
          <p className={`text-2xl font-bold ${metrics.overdueCount > 0 ? 'text-red-600' : 'text-gray-900'}`}>
            {metrics.overdueCount}
          </p>
        </div>
        <div className="bg-white shadow rounded-lg p-4">
          <p className="text-sm text-gray-500">Overdue Value</p>
          <p className={`text-2xl font-bold ${metrics.overdueValue > 0 ? 'text-red-600' : 'text-gray-900'}`}>
            {metrics.overdueValue.toFixed(2)}
          </p>
        </div>
        <div className="bg-white shadow rounded-lg p-4">
          <p className="text-sm text-gray-500">Avg Lead Time</p>
          <p className="text-2xl font-bold text-gray-900">{metrics.avgLeadTime} days</p>
        </div>
      </div>

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
        <button
          type="button"
          onClick={handleExportCSV}
          disabled={orders.length === 0}
          className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 text-sm font-medium"
        >
          Export CSV {selectedIds.size > 0 ? `(${selectedIds.size} selected)` : '(all)'}
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

      {/* Purchase Orders Table */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        {loading ? (
          <div className="p-6 text-gray-500">Loading...</div>
        ) : orders.length === 0 ? (
          <div className="p-6 text-gray-500">No purchase orders. Create one to get started.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead>
                <tr className="bg-gray-50">
                  <th className="px-3 py-3 text-left font-medium text-gray-700">
                    <input
                      type="checkbox"
                      checked={selectedIds.size === orders.length && orders.length > 0}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedIds(new Set(orders.map((o) => o.id)))
                        } else {
                          setSelectedIds(new Set())
                        }
                      }}
                      className="rounded"
                    />
                  </th>
                  <th className="px-3 py-3 text-left font-medium text-gray-700">PO #</th>
                  <th className="px-3 py-3 text-left font-medium text-gray-700">Status</th>
                  <th className="px-3 py-3 text-left font-medium text-gray-700">Order Date</th>
                  <th className="px-3 py-3 text-right font-medium text-gray-700">Value</th>
                  <th className="px-3 py-3 text-right font-medium text-gray-700">Deposit (20%)</th>
                  <th className="px-3 py-3 text-right font-medium text-gray-700">Final (80%)</th>
                  <th className="px-3 py-3 text-left font-medium text-gray-700">ETA</th>
                  <th className="px-3 py-3 text-left font-medium text-gray-700">SKUs</th>
                  <th className="px-3 py-3 text-right font-medium text-gray-700">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {orders.map((po) => {
                  const value = parseFloat(po.order_value || '0')
                  const deposit = value * 0.2
                  const final = value * 0.8
                  const overdue = isOverdue(po)
                  return (
                    <tr key={po.id} className={overdue ? 'bg-red-50' : 'hover:bg-gray-50'}>
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          checked={selectedIds.has(po.id)}
                          onChange={() => toggleSelect(po.id)}
                          className="rounded"
                        />
                      </td>
                      <td className="px-3 py-2 font-medium text-gray-900">{po.id}</td>
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          onClick={() => handleToggleStatus(po)}
                          className={`px-2 py-1 rounded text-xs font-medium ${
                            po.status === 'Done'
                              ? 'bg-green-100 text-green-800'
                              : 'bg-amber-100 text-amber-800'
                          }`}
                        >
                          {po.status}
                        </button>
                      </td>
                      <td className="px-3 py-2 text-gray-700">{po.order_date}</td>
                      <td className="px-3 py-2 text-right text-gray-700">{value.toFixed(2)}</td>
                      <td className="px-3 py-2 text-right text-gray-600">{deposit.toFixed(2)}</td>
                      <td className="px-3 py-2 text-right text-gray-600">{final.toFixed(2)}</td>
                      <td className="px-3 py-2 text-gray-700">
                        {po.status === 'Done' && po.actual_delivery_date ? (
                          <span className="text-green-600">{po.actual_delivery_date}</span>
                        ) : (
                          <span className={overdue ? 'text-red-600 font-medium' : ''}>
                            {getETA(po)} {overdue && '(overdue)'}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-gray-600 max-w-xs truncate" title={po.line_items.map((li) => `${li.sku_code}x${li.quantity}`).join(', ')}>
                        {po.line_items.map((li) => `${li.sku_code}x${li.quantity}`).join(', ')}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button
                          type="button"
                          onClick={() => handleDelete(po.id)}
                          className="text-red-600 hover:underline text-sm"
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
