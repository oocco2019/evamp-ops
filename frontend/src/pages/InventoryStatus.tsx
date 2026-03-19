import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { inventoryStatusAPI, type OCInboundOrderRow, type OCSkuInventoryRow, type OCSkuMapping } from '../services/api'

export default function InventoryStatus() {
  const qc = useQueryClient()
  const [skuFilter, setSkuFilter] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [inventorySort, setInventorySort] = useState<{
    key: 'seller_skuid' | 'available' | 'in_transit' | 'reserved_allocated' | 'sold_3m_units' | 'sold_1m_units'
    dir: 'asc' | 'desc'
  }>({ key: 'seller_skuid', dir: 'asc' })

  const summaryQuery = useQuery({
    queryKey: ['inventory-status', 'summary'],
    queryFn: async () => (await inventoryStatusAPI.getSummary()).data,
  })

  const mappingsQuery = useQuery({
    queryKey: ['inventory-status', 'mappings', skuFilter],
    queryFn: async () => (await inventoryStatusAPI.listSkuMappings(skuFilter.trim() || undefined)).data,
  })
  const inventoryQuery = useQuery({
    queryKey: ['inventory-status', 'inventory'],
    queryFn: async () => (await inventoryStatusAPI.listInventory()).data,
  })
  const inboundOrdersQuery = useQuery({
    queryKey: ['inventory-status', 'inbound-orders', 6],
    queryFn: async () => (await inventoryStatusAPI.listInboundOrders({ months_back: 6 })).data,
  })

  const syncMappings = useMutation({
    mutationFn: inventoryStatusAPI.syncSkuMappings,
    onSuccess: (res) => {
      setNotice(`SKU mappings synced: ${res.data.synced} (skipped ${res.data.skipped}), inventory rows: ${res.data.inventory_rows}`)
      setError(null)
      qc.invalidateQueries({ queryKey: ['inventory-status'] })
    },
    onError: (e: unknown) => {
      const msg = e instanceof Error ? e.message : 'SKU sync failed'
      setError(msg)
    },
  })

  const summary = summaryQuery.data
  const mappings: OCSkuMapping[] = mappingsQuery.data ?? []
  const inventoryRows: OCSkuInventoryRow[] = inventoryQuery.data ?? []
  const inboundOrders: OCInboundOrderRow[] = inboundOrdersQuery.data ?? []
  const hasRequiredCredentials = summary?.has_required_credentials ?? false
  const sortedInventoryRows = [...inventoryRows].sort((a, b) => {
    const mult = inventorySort.dir === 'asc' ? 1 : -1
    if (inventorySort.key === 'seller_skuid') {
      return mult * (a.seller_skuid || '').localeCompare(b.seller_skuid || '')
    }
    return mult * ((a[inventorySort.key] as number) - (b[inventorySort.key] as number))
  })
  const handleInventorySort = (
    key: 'seller_skuid' | 'available' | 'in_transit' | 'reserved_allocated' | 'sold_3m_units' | 'sold_1m_units'
  ) => {
    setInventorySort((prev) => ({
      key,
      dir: prev.key === key ? (prev.dir === 'asc' ? 'desc' : 'asc') : (key === 'seller_skuid' ? 'asc' : 'desc'),
    }))
  }

  return (
    <div className="px-4 py-6 sm:px-0">
      <h1 className="text-3xl font-bold text-gray-900 mb-2">Inventory status</h1>
      <p className="text-sm text-gray-600 mb-6">
        Read-only OrangeConnex visibility inside the platform.
      </p>

      {notice && <div className="mb-4 rounded border border-green-200 bg-green-50 p-3 text-sm text-green-800">{notice}</div>}
      {error && <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div>}
      {summaryQuery.isError && (
        <div className="mb-4 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          Backend was likely restarted or is temporarily unavailable. Buttons remain enabled; retry when backend is up.
        </div>
      )}
      {!hasRequiredCredentials && (
        <div className="mb-4 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          Missing OC credentials (client_id, client_secret, refresh_token) in Settings &gt; OC Integration.
        </div>
      )}

      <section className="bg-white rounded-lg border border-gray-200 p-4">
        <div className="flex flex-wrap items-end gap-2 mb-3">
          <h2 className="text-lg font-semibold text-gray-800 mr-4">SKU mappings</h2>
          <label className="text-sm text-gray-700">
            SKU filter
            <input
              className="ml-2 rounded border border-gray-300 px-2 py-1"
              value={skuFilter}
              onChange={(e) => setSkuFilter(e.target.value)}
              placeholder="e.g. uke01"
            />
          </label>
          <span className="text-sm text-gray-500">Rows: {summary?.mapping_count ?? 0}</span>
          <button
            type="button"
            onClick={() => syncMappings.mutate()}
            className="ml-auto px-3 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
            disabled={syncMappings.isPending}
          >
            {syncMappings.isPending ? 'Syncing...' : 'Sync SKU mappings'}
          </button>
        </div>
        {mappingsQuery.isLoading ? (
          <p className="text-sm text-gray-500">Loading mappings...</p>
        ) : mappings.length === 0 ? (
          <p className="text-sm text-gray-500">No mappings yet. Run “Sync SKU mappings”.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm border border-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left">SKU</th>
                  <th className="px-3 py-2 text-left">Seller SKU</th>
                  <th className="px-3 py-2 text-left">Reference SKU</th>
                  <th className="px-3 py-2 text-left">MFSKUID</th>
                  <th className="px-3 py-2 text-left">Region</th>
                  <th className="px-3 py-2 text-left">Synced</th>
                </tr>
              </thead>
              <tbody>
                {mappings.map((row) => (
                  <tr key={row.id} className="border-t border-gray-100">
                    <td className="px-3 py-2">{row.sku_code}</td>
                    <td className="px-3 py-2">{row.seller_skuid}</td>
                    <td className="px-3 py-2">{row.reference_skuid}</td>
                    <td className="px-3 py-2 font-mono">{row.mfskuid}</td>
                    <td className="px-3 py-2">{row.service_region || '—'}</td>
                    <td className="px-3 py-2">{new Date(row.last_synced_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="bg-white rounded-lg border border-gray-200 p-4 mt-6">
        <h2 className="text-lg font-semibold text-gray-800 mb-3">OC inventory snapshot</h2>
        {inventoryQuery.isLoading ? (
          <p className="text-sm text-gray-500">Loading inventory...</p>
        ) : inventoryRows.length === 0 ? (
          <p className="text-sm text-gray-500">No inventory rows yet. Run “Sync SKU mappings”.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm border border-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th
                    className="px-3 py-2 text-left cursor-pointer hover:text-gray-900"
                    onClick={() => handleInventorySort('seller_skuid')}
                  >
                    Seller SKU {inventorySort.key === 'seller_skuid' && (inventorySort.dir === 'asc' ? '▲' : '▼')}
                  </th>
                  <th
                    className="px-3 py-2 text-right cursor-pointer hover:text-gray-900"
                    onClick={() => handleInventorySort('available')}
                  >
                    Available {inventorySort.key === 'available' && (inventorySort.dir === 'asc' ? '▲' : '▼')}
                  </th>
                  <th
                    className="px-3 py-2 text-right cursor-pointer hover:text-gray-900"
                    onClick={() => handleInventorySort('in_transit')}
                  >
                    In transit {inventorySort.key === 'in_transit' && (inventorySort.dir === 'asc' ? '▲' : '▼')}
                  </th>
                  <th
                    className="px-3 py-2 text-right cursor-pointer hover:text-gray-900"
                    onClick={() => handleInventorySort('reserved_allocated')}
                  >
                    Reserved alloc {inventorySort.key === 'reserved_allocated' && (inventorySort.dir === 'asc' ? '▲' : '▼')}
                  </th>
                  <th
                    className="px-3 py-2 text-right cursor-pointer hover:text-gray-900"
                    onClick={() => handleInventorySort('sold_3m_units')}
                  >
                    Sold last 3 months {inventorySort.key === 'sold_3m_units' && (inventorySort.dir === 'asc' ? '▲' : '▼')}
                  </th>
                  <th
                    className="px-3 py-2 text-right cursor-pointer hover:text-gray-900"
                    onClick={() => handleInventorySort('sold_1m_units')}
                  >
                    Sold last 1 month {inventorySort.key === 'sold_1m_units' && (inventorySort.dir === 'asc' ? '▲' : '▼')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedInventoryRows.map((row) => (
                  <tr key={row.id} className="border-t border-gray-100">
                    <td className="px-3 py-2 font-mono">{row.seller_skuid || '—'}</td>
                    <td className="px-3 py-2 text-right">{row.available}</td>
                    <td className="px-3 py-2 text-right">{row.in_transit}</td>
                    <td className="px-3 py-2 text-right">{row.reserved_allocated}</td>
                    <td className="px-3 py-2 text-right">{row.sold_3m_units}</td>
                    <td className="px-3 py-2 text-right">{row.sold_1m_units}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="bg-white rounded-lg border border-gray-200 p-4 mt-6">
        <h2 className="text-lg font-semibold text-gray-800 mb-3">Inbound orders</h2>
        <p className="text-sm text-gray-600 mb-3">
          Evamp-ops workflows always involve these OC marketplaces together: `UK`, `DE`, `US`, `AU`. This table pulls inbound orders from all four regions.
        </p>
        {inboundOrdersQuery.isLoading ? (
          <p className="text-sm text-gray-500">Loading inbound orders...</p>
        ) : inboundOrders.length === 0 ? (
          <p className="text-sm text-gray-500">No inbound orders found for UK/DE/US/AU in the last 6 months.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm border border-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left">Seller inbound no.</th>
                  <th className="px-3 py-2 text-left">OC inbound no.</th>
                  <th className="px-3 py-2 text-left">Status</th>
                  <th className="px-3 py-2 text-left">Warehouse</th>
                  <th className="px-3 py-2 text-left">SKU count</th>
                  <th className="px-3 py-2 text-left">Put away qty</th>
                  <th className="px-3 py-2 text-left">Shipping method</th>
                </tr>
              </thead>
              <tbody>
                {inboundOrders.map((row, idx) => (
                  <tr
                    key={`${row.seller_inbound_number}-${row.oc_inbound_number || idx}`}
                    className="border-t border-gray-100"
                  >
                    <td className="px-3 py-2 font-mono">
                      {row.seller_inbound_number || row.oc_inbound_number || '—'}
                    </td>
                    <td className="px-3 py-2 font-mono">{row.oc_inbound_number || '—'}</td>
                    <td className="px-3 py-2">{row.status || '—'}</td>
                    <td className="px-3 py-2">{row.warehouse_code || row.region || '—'}</td>
                    <td className="px-3 py-2">{row.sku_qty}</td>
                    <td className="px-3 py-2">{row.put_away_qty}</td>
                    <td className="px-3 py-2">{row.shipping_method || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
