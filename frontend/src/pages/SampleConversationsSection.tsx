import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  messagesAPI,
  type SampleConversation,
  type SampleMessage,
} from '../services/api'

export default function SampleConversationsSection() {
  const queryClient = useQueryClient()
  const [newTitle, setNewTitle] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [draftRole, setDraftRole] = useState<'seller' | 'buyer'>('seller')
  const [draftContent, setDraftContent] = useState('')
  const [editingMsgId, setEditingMsgId] = useState<number | null>(null)
  const [editMsgContent, setEditMsgContent] = useState('')
  const [editingTitleId, setEditingTitleId] = useState<number | null>(null)
  const [editTitle, setEditTitle] = useState('')

  const { data: conversations = [], isLoading } = useQuery({
    queryKey: ['sample-conversations'],
    queryFn: async () => (await messagesAPI.listSampleConversations()).data,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['sample-conversations'] })

  const createConv = useMutation({
    mutationFn: (title: string) => messagesAPI.createSampleConversation({ title, enabled: true }),
    onSuccess: (res) => {
      invalidate()
      setNewTitle('')
      setSelectedId(res.data.id)
    },
  })

  const updateConv = useMutation({
    mutationFn: ({ id, data }: { id: number; data: { title?: string; enabled?: boolean } }) =>
      messagesAPI.updateSampleConversation(id, data),
    onSuccess: () => {
      invalidate()
      setEditingTitleId(null)
    },
  })

  const deleteConv = useMutation({
    mutationFn: messagesAPI.deleteSampleConversation,
    onSuccess: (_, id) => {
      invalidate()
      if (selectedId === id) setSelectedId(null)
    },
  })

  const addMsg = useMutation({
    mutationFn: ({
      conversationId,
      role,
      content,
    }: {
      conversationId: number
      role: 'buyer' | 'seller'
      content: string
    }) => messagesAPI.addSampleMessage(conversationId, { role, content }),
    onSuccess: () => {
      invalidate()
      setDraftContent('')
    },
  })

  const updateMsg = useMutation({
    mutationFn: ({ id, content }: { id: number; content: string }) =>
      messagesAPI.updateSampleMessage(id, { content }),
    onSuccess: () => {
      invalidate()
      setEditingMsgId(null)
    },
  })

  const deleteMsg = useMutation({
    mutationFn: messagesAPI.deleteSampleMessage,
    onSuccess: invalidate,
  })

  const selected = conversations.find((c: SampleConversation) => c.id === selectedId) || null

  return (
    <section
      id="sample-conversations"
      className="bg-white shadow rounded-lg border border-gray-200 p-6 mb-6"
    >
      <h2 className="text-lg font-semibold text-gray-900 mb-1">Sample conversations</h2>
      <p className="text-xs text-gray-500 mb-4">
        Curated buyer/seller examples used by <strong>Messages-Test</strong> drafts (style and pacing).
        Enabled conversations are injected with policies and playbook.
      </p>

      <form
        className="mb-4 flex flex-wrap gap-2 items-end"
        onSubmit={(e) => {
          e.preventDefault()
          if (!newTitle.trim()) return
          createConv.mutate(newTitle.trim())
        }}
      >
        <div className="flex-1 min-w-[12rem]">
          <label className="block text-sm font-medium text-gray-700 mb-1">New conversation</label>
          <input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            placeholder="e.g. Defect → replace with tracking"
            required
          />
        </div>
        <button
          type="submit"
          disabled={createConv.isPending}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:opacity-50"
        >
          {createConv.isPending ? 'Creating…' : 'Create'}
        </button>
      </form>

      {isLoading ? (
        <p className="text-sm text-gray-500">Loading…</p>
      ) : !conversations.length ? (
        <p className="text-sm text-gray-500">No sample conversations yet.</p>
      ) : (
        <div className="grid md:grid-cols-2 gap-4">
          <ul className="space-y-2 border border-gray-200 rounded-lg p-2 max-h-[28rem] overflow-y-auto">
            {conversations.map((c: SampleConversation) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(c.id)}
                  className={`w-full text-left px-3 py-2 rounded text-sm ${
                    selectedId === c.id ? 'bg-blue-50 border border-blue-200' : 'hover:bg-gray-50'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-gray-900 truncate">{c.title}</span>
                    <span className="text-xs text-gray-500 shrink-0">
                      {c.messages.length} msg{c.messages.length === 1 ? '' : 's'}
                      {!c.enabled ? ' · off' : ''}
                    </span>
                  </div>
                </button>
              </li>
            ))}
          </ul>

          <div className="border border-gray-200 rounded-lg p-3 min-h-[12rem]">
            {!selected ? (
              <p className="text-sm text-gray-500">Select a conversation to edit.</p>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2 mb-3">
                  {editingTitleId === selected.id ? (
                    <form
                      className="flex flex-1 gap-2"
                      onSubmit={(e) => {
                        e.preventDefault()
                        if (!editTitle.trim()) return
                        updateConv.mutate({ id: selected.id, data: { title: editTitle.trim() } })
                      }}
                    >
                      <input
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        className="flex-1 border border-gray-300 rounded px-2 py-1 text-sm"
                        autoFocus
                      />
                      <button type="submit" className="text-xs text-blue-600 hover:underline">
                        Save
                      </button>
                      <button
                        type="button"
                        className="text-xs text-gray-500 hover:underline"
                        onClick={() => setEditingTitleId(null)}
                      >
                        Cancel
                      </button>
                    </form>
                  ) : (
                    <>
                      <h3 className="font-medium text-gray-900 flex-1">{selected.title}</h3>
                      <button
                        type="button"
                        className="text-xs text-blue-600 hover:underline"
                        onClick={() => {
                          setEditingTitleId(selected.id)
                          setEditTitle(selected.title)
                        }}
                      >
                        Rename
                      </button>
                    </>
                  )}
                  <label className="text-xs text-gray-600 flex items-center gap-1">
                    <input
                      type="checkbox"
                      checked={selected.enabled}
                      onChange={(e) =>
                        updateConv.mutate({ id: selected.id, data: { enabled: e.target.checked } })
                      }
                    />
                    Enabled
                  </label>
                  <button
                    type="button"
                    className="text-xs text-red-600 hover:underline"
                    onClick={() => {
                      if (confirm('Delete this sample conversation?')) deleteConv.mutate(selected.id)
                    }}
                  >
                    Delete
                  </button>
                </div>

                <div className="space-y-2 mb-3 max-h-[16rem] overflow-y-auto">
                  {selected.messages.map((m: SampleMessage) => (
                    <div
                      key={m.id}
                      className={`rounded-lg px-3 py-2 text-sm ${
                        m.role === 'seller'
                          ? 'bg-blue-600 text-white ml-6'
                          : 'bg-gray-100 text-gray-900 mr-6'
                      }`}
                    >
                      <div className="text-[10px] opacity-80 mb-0.5">
                        {m.role === 'seller' ? 'Seller' : 'Buyer'}
                      </div>
                      {editingMsgId === m.id ? (
                        <form
                          onSubmit={(e) => {
                            e.preventDefault()
                            if (!editMsgContent.trim()) return
                            updateMsg.mutate({ id: m.id, content: editMsgContent.trim() })
                          }}
                        >
                          <textarea
                            value={editMsgContent}
                            onChange={(e) => setEditMsgContent(e.target.value)}
                            rows={3}
                            className="w-full rounded border border-gray-300 px-2 py-1 text-sm text-gray-900"
                          />
                          <div className="flex gap-2 mt-1">
                            <button type="submit" className="text-xs underline">
                              Save
                            </button>
                            <button
                              type="button"
                              className="text-xs underline opacity-80"
                              onClick={() => setEditingMsgId(null)}
                            >
                              Cancel
                            </button>
                          </div>
                        </form>
                      ) : (
                        <>
                          <p className="whitespace-pre-wrap">{m.content}</p>
                          <div className="flex gap-2 mt-1">
                            <button
                              type="button"
                              className="text-[10px] underline opacity-90"
                              onClick={() => {
                                setEditingMsgId(m.id)
                                setEditMsgContent(m.content)
                              }}
                            >
                              Edit
                            </button>
                            <button
                              type="button"
                              className="text-[10px] underline opacity-90"
                              onClick={() => {
                                if (confirm('Delete this message?')) deleteMsg.mutate(m.id)
                              }}
                            >
                              Delete
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  ))}
                </div>

                <div className="border-t border-gray-200 pt-3">
                  <div className="flex gap-2 mb-2">
                    <button
                      type="button"
                      onClick={() => setDraftRole('seller')}
                      className={`px-3 py-1.5 text-sm rounded ${
                        draftRole === 'seller'
                          ? 'bg-blue-600 text-white'
                          : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                      }`}
                    >
                      Seller
                    </button>
                    <button
                      type="button"
                      onClick={() => setDraftRole('buyer')}
                      className={`px-3 py-1.5 text-sm rounded ${
                        draftRole === 'buyer'
                          ? 'bg-gray-800 text-white'
                          : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                      }`}
                    >
                      Buyer
                    </button>
                  </div>
                  <textarea
                    value={draftContent}
                    onChange={(e) => setDraftContent(e.target.value)}
                    rows={3}
                    className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                    placeholder={`Write a ${draftRole} message…`}
                  />
                  <button
                    type="button"
                    disabled={!draftContent.trim() || addMsg.isPending}
                    onClick={() =>
                      addMsg.mutate({
                        conversationId: selected.id,
                        role: draftRole,
                        content: draftContent.trim(),
                      })
                    }
                    className="mt-2 px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
                  >
                    {addMsg.isPending ? 'Adding…' : `Add ${draftRole} message`}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
