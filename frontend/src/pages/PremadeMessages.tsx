import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { messagesAPI, type PremadeMessage } from '../services/api'

export default function PremadeMessagesPage() {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editName, setEditName] = useState('')
  const [editContent, setEditContent] = useState('')
  const [error, setError] = useState<string | null>(null)
  const dragIdRef = useRef<number | null>(null)
  const [dragOverId, setDragOverId] = useState<number | null>(null)

  const { data: items = [], isLoading } = useQuery({
    queryKey: ['premade-messages'],
    queryFn: async () => (await messagesAPI.listPremadeMessages()).data,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['premade-messages'] })

  const createMut = useMutation({
    mutationFn: () => messagesAPI.createPremadeMessage({ name: name.trim(), content: content.trim() }),
    onSuccess: () => {
      setName('')
      setContent('')
      setError(null)
      invalidate()
    },
    onError: (e: unknown) => {
      const ax = e as { response?: { data?: { detail?: string } }; message?: string }
      setError(ax.response?.data?.detail ?? ax.message ?? 'Create failed')
    },
  })

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: number; data: { name: string; content: string } }) =>
      messagesAPI.updatePremadeMessage(id, data),
    onSuccess: () => {
      setEditingId(null)
      setError(null)
      invalidate()
    },
    onError: (e: unknown) => {
      const ax = e as { response?: { data?: { detail?: string } }; message?: string }
      setError(ax.response?.data?.detail ?? ax.message ?? 'Update failed')
    },
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => messagesAPI.deletePremadeMessage(id),
    onSuccess: () => {
      setError(null)
      invalidate()
    },
    onError: (e: unknown) => {
      const ax = e as { response?: { data?: { detail?: string } }; message?: string }
      setError(ax.response?.data?.detail ?? ax.message ?? 'Delete failed')
    },
  })

  const reorderMut = useMutation({
    mutationFn: (ordered_ids: number[]) => messagesAPI.reorderPremadeMessages(ordered_ids),
    onSuccess: (res) => {
      queryClient.setQueryData(['premade-messages'], res.data)
      setError(null)
    },
    onError: (e: unknown) => {
      const ax = e as { response?: { data?: { detail?: string } }; message?: string }
      setError(ax.response?.data?.detail ?? ax.message ?? 'Reorder failed')
      invalidate()
    },
  })

  const startEdit = (row: PremadeMessage) => {
    setEditingId(row.id)
    setEditName(row.name)
    setEditContent(row.content)
  }

  const onDropReorder = (targetId: number) => {
    const fromId = dragIdRef.current
    dragIdRef.current = null
    setDragOverId(null)
    if (fromId == null || fromId === targetId) return
    const ids = items.map((i) => i.id)
    const fromIdx = ids.indexOf(fromId)
    const toIdx = ids.indexOf(targetId)
    if (fromIdx < 0 || toIdx < 0) return
    const next = [...ids]
    next.splice(fromIdx, 1)
    next.splice(toIdx, 0, fromId)
    // Optimistic UI
    const byId = new Map(items.map((i) => [i.id, i]))
    queryClient.setQueryData(
      ['premade-messages'],
      next.map((id, sort_order) => ({ ...byId.get(id)!, sort_order })),
    )
    reorderMut.mutate(next)
  }

  return (
    <div className="px-4 py-6 sm:px-0 max-w-3xl mx-auto">
      <div className="mb-6 flex items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Premade messages</h1>
          <p className="text-sm text-gray-600 mt-1">
            Saved replies for Messages. Drag rows to set dropdown order.
          </p>
        </div>
        <Link
          to="/messages"
          className="text-sm text-blue-600 hover:underline"
        >
          ← Messages
        </Link>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-800">{error}</div>
      )}

      <section className="bg-white border border-gray-200 rounded-lg p-4 mb-6">
        <h2 className="text-sm font-semibold text-gray-900 mb-3">Add message</h2>
        <label className="block text-sm text-gray-700 mb-1">Name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Return address"
          className="w-full mb-3 rounded border border-gray-300 px-3 py-2 text-sm"
          maxLength={120}
        />
        <label className="block text-sm text-gray-700 mb-1">Content</label>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={5}
          placeholder="Full text pasted into the draft reply box"
          className="w-full mb-3 rounded border border-gray-300 px-3 py-2 text-sm font-mono"
          maxLength={8000}
        />
        <button
          type="button"
          disabled={!name.trim() || !content.trim() || createMut.isPending}
          onClick={() => createMut.mutate()}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50"
        >
          {createMut.isPending ? 'Saving…' : 'Add'}
        </button>
      </section>

      <section className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <h2 className="text-sm font-semibold text-gray-900 px-4 py-3 border-b border-gray-200">
          Saved ({items.length})
        </h2>
        {isLoading ? (
          <p className="p-4 text-sm text-gray-500">Loading…</p>
        ) : items.length === 0 ? (
          <p className="p-4 text-sm text-gray-500">No premade messages yet.</p>
        ) : (
          <ul className="divide-y divide-gray-200">
            {items.map((row) => (
              <li
                key={row.id}
                draggable={editingId !== row.id}
                onDragStart={() => {
                  dragIdRef.current = row.id
                }}
                onDragOver={(e) => {
                  e.preventDefault()
                  setDragOverId(row.id)
                }}
                onDragLeave={() => {
                  if (dragOverId === row.id) setDragOverId(null)
                }}
                onDrop={(e) => {
                  e.preventDefault()
                  onDropReorder(row.id)
                }}
                className={`p-4 ${dragOverId === row.id ? 'bg-blue-50' : 'bg-white'}`}
              >
                {editingId === row.id ? (
                  <div>
                    <input
                      type="text"
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      className="w-full mb-2 rounded border border-gray-300 px-3 py-2 text-sm"
                      maxLength={120}
                    />
                    <textarea
                      value={editContent}
                      onChange={(e) => setEditContent(e.target.value)}
                      rows={5}
                      className="w-full mb-2 rounded border border-gray-300 px-3 py-2 text-sm font-mono"
                      maxLength={8000}
                    />
                    <div className="flex gap-2">
                      <button
                        type="button"
                        disabled={!editName.trim() || !editContent.trim() || updateMut.isPending}
                        onClick={() =>
                          updateMut.mutate({
                            id: row.id,
                            data: { name: editName.trim(), content: editContent.trim() },
                          })
                        }
                        className="px-3 py-1.5 bg-blue-600 text-white rounded text-sm disabled:opacity-50"
                      >
                        Save
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingId(null)}
                        className="px-3 py-1.5 border border-gray-300 rounded text-sm"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex gap-3 items-start">
                    <span
                      className="mt-0.5 cursor-grab text-gray-400 select-none"
                      title="Drag to reorder"
                      aria-hidden
                    >
                      ⋮⋮
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900">{row.name}</p>
                      <pre className="mt-1 text-xs text-gray-600 whitespace-pre-wrap font-sans line-clamp-3">
                        {row.content}
                      </pre>
                    </div>
                    <div className="flex gap-2 flex-shrink-0">
                      <button
                        type="button"
                        onClick={() => startEdit(row)}
                        className="text-sm text-blue-600 hover:underline"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          if (window.confirm(`Delete “${row.name}”?`)) deleteMut.mutate(row.id)
                        }}
                        className="text-sm text-red-600 hover:underline"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
