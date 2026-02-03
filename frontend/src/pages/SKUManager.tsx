import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { stockAPI, type SKU } from '../services/api'

export default function SKUManager() {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [adding, setAdding] = useState(false)
  const [newSku, setNewSku] = useState({
    sku_code: '',
    title: '',
    landed_cost: '',
    postage_price: '',
  })
  const [editingCode, setEditingCode] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<Pick<SKU, 'title' | 'landed_cost' | 'postage_price'>>({})

  const { data: skus, isLoading } = useQuery({
    queryKey: ['skus', search],
    queryFn: async () => {
      const response = await stockAPI.listSKUs(search || undefined)
      return response.data
    },
  })

  const createMutation = useMutation({
    mutationFn: stockAPI.createSKU,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skus'] })
      queryClient.invalidateQueries({ queryKey: ['analytics'] })
      setAdding(false)
      setNewSku({
        sku_code: '',
        title: '',
        landed_cost: '',
        postage_price: '',
      })
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ sku_code, data }: { sku_code: string; data: Partial<SKU> }) =>
      stockAPI.updateSKU(sku_code, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skus'] })
      queryClient.invalidateQueries({ queryKey: ['analytics'] })
      setEditingCode(null)
      setEditForm({})
    },
  })

  const deleteMutation = useMutation({
    mutationFn: stockAPI.deleteSKU,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skus'] })
      queryClient.invalidateQueries({ queryKey: ['analytics'] })
    },
  })

  const handleAddSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    createMutation.mutate({
      sku_code: newSku.sku_code.trim(),
      title: newSku.title.trim(),
      landed_cost: newSku.landed_cost ? Number(newSku.landed_cost) : undefined,
      postage_price: newSku.postage_price ? Number(newSku.postage_price) : undefined,
    })
  }

  const startEdit = (sku: SKU) => {
    setEditingCode(sku.sku_code)
    setEditForm({
      title: sku.title,
      landed_cost: sku.landed_cost,
      postage_price: sku.postage_price,
    })
  }

  const handleEditSubmit = (e: React.FormEvent, sku_code: string) => {
    e.preventDefault()
    updateMutation.mutate({ sku_code, data: editForm })
  }

  return (
    <div className="px-4 py-6 sm:px-0">
      <div className="bg-white shadow rounded-lg p-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">SKU Manager</h1>
            <p className="mt-2 text-gray-600">
              Manage your product catalog with costs and profit calculations.
            </p>
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="Search SKU or title..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="border border-gray-300 rounded-md px-3 py-2 w-48"
            />
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700"
            >
              Add SKU
            </button>
          </div>
        </div>

        {/* Add SKU form */}
        {adding && (
          <form onSubmit={handleAddSubmit} className="mb-6 p-4 bg-gray-50 rounded-lg border border-gray-200">
            <h3 className="font-medium mb-3">New SKU</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-3">
              <input
                type="text"
                placeholder="SKU code *"
                value={newSku.sku_code}
                onChange={(e) => setNewSku((s) => ({ ...s, sku_code: e.target.value }))}
                className="border border-gray-300 rounded-md px-3 py-2"
                required
              />
              <input
                type="text"
                placeholder="Title *"
                value={newSku.title}
                onChange={(e) => setNewSku((s) => ({ ...s, title: e.target.value }))}
                className="border border-gray-300 rounded-md px-3 py-2"
                required
              />
              <input
                type="number"
                step="0.01"
                min="0"
                placeholder="Landed cost (USD)"
                value={newSku.landed_cost}
                onChange={(e) => setNewSku((s) => ({ ...s, landed_cost: e.target.value }))}
                className="border border-gray-300 rounded-md px-3 py-2"
              />
              <input
                type="number"
                step="0.01"
                min="0"
                placeholder="Postage (USD)"
                value={newSku.postage_price}
                onChange={(e) => setNewSku((s) => ({ ...s, postage_price: e.target.value }))}
                className="border border-gray-300 rounded-md px-3 py-2"
              />
            </div>
            <div className="mt-3 flex gap-2">
              <button type="submit" disabled={createMutation.isPending} className="bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50">
                Save
              </button>
              <button type="button" onClick={() => setAdding(false)} className="bg-gray-200 text-gray-800 px-4 py-2 rounded-md hover:bg-gray-300">
                Cancel
              </button>
            </div>
          </form>
        )}

        {/* SKU table */}
        {isLoading ? (
          <p className="text-gray-500">Loading SKUs...</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">SKU</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Title</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Landed cost (USD)</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Postage (USD)</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {skus && skus.length > 0 ? (
                  skus.map((sku) => (
                    <tr key={sku.sku_code}>
                      {editingCode === sku.sku_code ? (
                        <>
                          <td className="px-4 py-2 text-sm text-gray-900">{sku.sku_code}</td>
                          <td className="px-4 py-2">
                            <input
                              type="text"
                              value={editForm.title ?? ''}
                              onChange={(e) => setEditForm((f) => ({ ...f, title: e.target.value }))}
                              className="border border-gray-300 rounded px-2 py-1 w-full"
                            />
                          </td>
                          <td className="px-4 py-2">
                            <input
                              type="number"
                              step="0.01"
                              min="0"
                              value={editForm.landed_cost ?? ''}
                              onChange={(e) => setEditForm((f) => ({ ...f, landed_cost: e.target.value ? Number(e.target.value) : undefined }))}
                              className="border border-gray-300 rounded px-2 py-1 w-24"
                            />
                          </td>
                          <td className="px-4 py-2">
                            <input
                              type="number"
                              step="0.01"
                              min="0"
                              value={editForm.postage_price ?? ''}
                              onChange={(e) => setEditForm((f) => ({ ...f, postage_price: e.target.value ? Number(e.target.value) : undefined }))}
                              className="border border-gray-300 rounded px-2 py-1 w-24"
                            />
                          </td>
                          <td className="px-4 py-2 text-right">
                            <button
                              type="button"
                              onClick={(e) => handleEditSubmit(e, sku.sku_code)}
                              disabled={updateMutation.isPending}
                              className="text-blue-600 hover:text-blue-800 mr-2"
                            >
                              Save
                            </button>
                            <button type="button" onClick={() => { setEditingCode(null); setEditForm({}) }} className="text-gray-600 hover:text-gray-800">
                              Cancel
                            </button>
                          </td>
                        </>
                      ) : (
                        <>
                          <td className="px-4 py-2 text-sm font-medium text-gray-900">{sku.sku_code}</td>
                          <td className="px-4 py-2 text-sm text-gray-700">{sku.title}</td>
                          <td className="px-4 py-2 text-sm text-gray-700">{sku.landed_cost != null ? Number(sku.landed_cost) : '-'}</td>
                          <td className="px-4 py-2 text-sm text-gray-700">{sku.postage_price != null ? Number(sku.postage_price) : '-'}</td>
                          <td className="px-4 py-2 text-right">
                            <button type="button" onClick={() => startEdit(sku)} className="text-blue-600 hover:text-blue-800 mr-2">
                              Edit
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                if (window.confirm(`Delete SKU ${sku.sku_code}?`)) deleteMutation.mutate(sku.sku_code)
                              }}
                              className="text-red-600 hover:text-red-800"
                            >
                              Delete
                            </button>
                          </td>
                        </>
                      )}
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-gray-500">
                      No SKUs yet. Add one above or import orders from eBay first.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
