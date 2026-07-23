import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  messagesAPI,
  type ReplyPolicy,
  type ReplyPlaybookEntry,
  type ReplyInsight,
} from '../services/api'

export default function AIInstructionsPage() {
  const queryClient = useQueryClient()
  const [policyDraft, setPolicyDraft] = useState('')
  const [editingPolicyId, setEditingPolicyId] = useState<number | null>(null)
  const [editPolicyBody, setEditPolicyBody] = useState('')

  const [pbForm, setPbForm] = useState({
    symptom: '',
    resolution: '',
    sku_scope: '*',
  })
  const [editingPbId, setEditingPbId] = useState<number | null>(null)
  const [editPb, setEditPb] = useState({
    symptom: '',
    resolution: '',
    sku_scope: '*',
  })

  const { data: insights, isLoading: insightsLoading } = useQuery({
    queryKey: ['reply-insights', 'pending'],
    queryFn: async () => (await messagesAPI.listReplyInsights('pending')).data,
  })

  const { data: policies, isLoading: policiesLoading } = useQuery({
    queryKey: ['reply-policies'],
    queryFn: async () => (await messagesAPI.listReplyPolicies()).data,
  })

  const { data: playbook, isLoading: playbookLoading } = useQuery({
    queryKey: ['reply-playbook'],
    queryFn: async () => (await messagesAPI.listReplyPlaybook()).data,
  })

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['reply-insights'] })
    queryClient.invalidateQueries({ queryKey: ['reply-insights-pending-count'] })
    queryClient.invalidateQueries({ queryKey: ['reply-policies'] })
    queryClient.invalidateQueries({ queryKey: ['reply-playbook'] })
  }

  const promoteInsight = useMutation({
    mutationFn: messagesAPI.promoteReplyInsight,
    onSuccess: invalidateAll,
  })

  const dismissInsight = useMutation({
    mutationFn: messagesAPI.dismissReplyInsight,
    onSuccess: invalidateAll,
  })

  const createPolicy = useMutation({
    mutationFn: messagesAPI.createReplyPolicy,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reply-policies'] })
      setPolicyDraft('')
    },
  })

  const updatePolicy = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<ReplyPolicy> }) =>
      messagesAPI.updateReplyPolicy(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reply-policies'] })
      setEditingPolicyId(null)
    },
  })

  const deletePolicy = useMutation({
    mutationFn: messagesAPI.deleteReplyPolicy,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['reply-policies'] }),
  })

  const createPlaybook = useMutation({
    mutationFn: messagesAPI.createReplyPlaybook,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reply-playbook'] })
      setPbForm({ symptom: '', resolution: '', sku_scope: '*' })
    },
  })

  const updatePlaybook = useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: number
      data: Parameters<typeof messagesAPI.updateReplyPlaybook>[1]
    }) => messagesAPI.updateReplyPlaybook(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reply-playbook'] })
      setEditingPbId(null)
    },
  })

  const deletePlaybook = useMutation({
    mutationFn: messagesAPI.deleteReplyPlaybook,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['reply-playbook'] }),
  })

  const startEditPolicy = (p: ReplyPolicy) => {
    setEditingPolicyId(p.id)
    setEditPolicyBody(p.body)
  }

  const startEditPb = (e: ReplyPlaybookEntry) => {
    setEditingPbId(e.id)
    setEditPb({
      symptom: e.symptom || '',
      resolution: e.resolution,
      sku_scope: e.sku_scope || '*',
    })
  }

  return (
    <div className="px-4 py-6 sm:px-0">
      <div className="mb-4">
        <Link to="/messages" className="text-sm text-blue-600 hover:underline">
          ← Messages
        </Link>
      </div>

      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900">AI Instructions</h1>
      </div>

      {/* Insights */}
      <section className="bg-white shadow rounded-lg border border-amber-200 p-6 mb-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Insights to review</h2>
        {insightsLoading ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : !insights?.length ? (
          <p className="text-sm text-gray-500">No pending insights.</p>
        ) : (
          <ul className="space-y-3">
            {insights.map((ins: ReplyInsight) => (
              <li key={ins.id} className="border border-amber-100 bg-amber-50/50 rounded-lg p-4">
                <div className="flex flex-wrap items-center gap-2 text-xs text-gray-600 mb-2">
                  <span className="uppercase tracking-wide font-medium text-amber-900">{ins.kind}</span>
                  <span>· seen {ins.occurrence_count}×</span>
                  <span>· {ins.source}</span>
                </div>
                {ins.title ? <p className="text-sm font-medium text-gray-900 mb-1">{ins.title}</p> : null}
                <p className="text-sm text-gray-800 whitespace-pre-wrap">{ins.body}</p>
                <div className="mt-3 flex flex-wrap gap-3">
                  <button
                    type="button"
                    disabled={promoteInsight.isPending}
                    onClick={() => promoteInsight.mutate(ins.id)}
                    className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                  >
                    Promote to {ins.kind}
                  </button>
                  <button
                    type="button"
                    disabled={dismissInsight.isPending}
                    onClick={() => dismissInsight.mutate(ins.id)}
                    className="text-xs text-gray-600 hover:underline"
                  >
                    Dismiss
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Policies */}
      <section className="bg-white shadow rounded-lg border border-gray-200 p-6 mb-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-1">Policies</h2>
        <p className="text-xs text-gray-500 mb-4">
          Style and liability rules. Enabled policies are injected into every draft.
        </p>

        <form
          className="mb-6 bg-gray-50 border border-gray-200 rounded-lg p-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (!policyDraft.trim()) return
            createPolicy.mutate({ body: policyDraft.trim(), enabled: true })
          }}
        >
          <label className="block text-sm font-medium text-gray-700 mb-1">Add policy</label>
          <textarea
            value={policyDraft}
            onChange={(e) => setPolicyDraft(e.target.value)}
            rows={3}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            placeholder="e.g. Prefer shortly over concrete dates…"
            required
          />
          <button
            type="submit"
            disabled={createPolicy.isPending}
            className="mt-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:opacity-50"
          >
            {createPolicy.isPending ? 'Adding…' : 'Add policy'}
          </button>
        </form>

        {policiesLoading ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : !policies?.length ? (
          <p className="text-sm text-gray-500">No policies yet.</p>
        ) : (
          <ul className="space-y-3">
            {policies.map((p) => (
              <li key={p.id} className="border border-gray-200 rounded-lg p-4">
                {editingPolicyId === p.id ? (
                  <form
                    onSubmit={(e) => {
                      e.preventDefault()
                      updatePolicy.mutate({ id: p.id, data: { body: editPolicyBody.trim() } })
                    }}
                  >
                    <textarea
                      value={editPolicyBody}
                      onChange={(e) => setEditPolicyBody(e.target.value)}
                      rows={3}
                      className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                      required
                    />
                    <div className="mt-2 flex gap-2">
                      <button type="submit" className="text-sm text-blue-600 hover:underline">
                        Save
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingPolicyId(null)}
                        className="text-sm text-gray-600 hover:underline"
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : (
                  <>
                    <p className="text-sm text-gray-800 whitespace-pre-wrap">{p.body}</p>
                    <div className="mt-3 flex flex-wrap items-center gap-3">
                      <label className="inline-flex items-center gap-2 text-xs text-gray-700">
                        <input
                          type="checkbox"
                          checked={p.enabled}
                          onChange={(e) =>
                            updatePolicy.mutate({ id: p.id, data: { enabled: e.target.checked } })
                          }
                          className="rounded border-gray-300"
                        />
                        Enabled
                      </label>
                      <button
                        type="button"
                        onClick={() => startEditPolicy(p)}
                        className="text-xs text-blue-600 hover:underline"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          if (confirm('Delete this policy?')) deletePolicy.mutate(p.id)
                        }}
                        className="text-xs text-red-600 hover:underline"
                      >
                        Delete
                      </button>
                    </div>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Playbook */}
      <section className="bg-white shadow rounded-lg border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-1">Playbook</h2>
        <p className="text-xs text-gray-500 mb-4">
          Symptom → resolution. SKU scope <span className="font-mono">*</span> = all SKUs;
          comma list <span className="font-mono">dee01, dee02, uke01</span>; or prefix{" "}
          <span className="font-mono">dee*</span>.
        </p>

        <form
          className="mb-6 bg-gray-50 border border-gray-200 rounded-lg p-4 space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (!pbForm.resolution.trim()) return
            createPlaybook.mutate({
              symptom: pbForm.symptom.trim(),
              resolution: pbForm.resolution.trim(),
              sku_scope: pbForm.sku_scope.trim() || '*',
              enabled: true,
            })
          }}
        >
          <h3 className="text-sm font-medium text-gray-800">Add entry</h3>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Symptom</label>
            <input
              value={pbForm.symptom}
              onChange={(e) => setPbForm((f) => ({ ...f, symptom: e.target.value }))}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              placeholder="e.g. cannot connect to WiFi"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">SKU scope</label>
            <input
              value={pbForm.sku_scope}
              onChange={(e) => setPbForm((f) => ({ ...f, sku_scope: e.target.value }))}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
              placeholder="* or dee01, dee02, uke01 or dee*"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Resolution</label>
            <textarea
              value={pbForm.resolution}
              onChange={(e) => setPbForm((f) => ({ ...f, resolution: e.target.value }))}
              rows={3}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              required
            />
          </div>
          <button
            type="submit"
            disabled={createPlaybook.isPending}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:opacity-50"
          >
            {createPlaybook.isPending ? 'Adding…' : 'Add playbook entry'}
          </button>
        </form>

        {playbookLoading ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : !playbook?.length ? (
          <p className="text-sm text-gray-500">No playbook entries yet.</p>
        ) : (
          <ul className="space-y-3">
            {playbook.map((e) => (
              <li key={e.id} className="border border-gray-200 rounded-lg p-4">
                {editingPbId === e.id ? (
                  <form
                    className="space-y-2"
                    onSubmit={(ev) => {
                      ev.preventDefault()
                      updatePlaybook.mutate({
                        id: e.id,
                        data: {
                          symptom: editPb.symptom.trim(),
                          resolution: editPb.resolution.trim(),
                          sku_scope: editPb.sku_scope.trim() || '*',
                        },
                      })
                    }}
                  >
                    <input
                      value={editPb.symptom}
                      onChange={(ev) => setEditPb((f) => ({ ...f, symptom: ev.target.value }))}
                      className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                      placeholder="Symptom"
                    />
                    <input
                      value={editPb.sku_scope}
                      onChange={(ev) => setEditPb((f) => ({ ...f, sku_scope: ev.target.value }))}
                      className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
                    />
                    <textarea
                      value={editPb.resolution}
                      onChange={(ev) => setEditPb((f) => ({ ...f, resolution: ev.target.value }))}
                      rows={3}
                      className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                      required
                    />
                    <div className="flex gap-2">
                      <button type="submit" className="text-sm text-blue-600 hover:underline">
                        Save
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingPbId(null)}
                        className="text-sm text-gray-600 hover:underline"
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : (
                  <>
                    <div className="text-xs text-gray-500 mb-1">
                      SKU <span className="font-mono text-gray-800">{e.sku_scope}</span>
                    </div>
                    {e.symptom ? (
                      <p className="text-sm font-medium text-gray-900 mb-1">{e.symptom}</p>
                    ) : null}
                    <p className="text-sm text-gray-800 whitespace-pre-wrap">{e.resolution}</p>
                    <div className="mt-3 flex flex-wrap items-center gap-3">
                      <label className="inline-flex items-center gap-2 text-xs text-gray-700">
                        <input
                          type="checkbox"
                          checked={e.enabled}
                          onChange={(ev) =>
                            updatePlaybook.mutate({
                              id: e.id,
                              data: { enabled: ev.target.checked },
                            })
                          }
                          className="rounded border-gray-300"
                        />
                        Enabled
                      </label>
                      <button
                        type="button"
                        onClick={() => startEditPb(e)}
                        className="text-xs text-blue-600 hover:underline"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          if (confirm('Delete this playbook entry?')) deletePlaybook.mutate(e.id)
                        }}
                        className="text-xs text-red-600 hover:underline"
                      >
                        Delete
                      </button>
                    </div>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
