import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { messagesAPI, stockAPI, type AIInstruction } from '../services/api'
import { Link } from 'react-router-dom'

export default function AIInstructionsPage() {
  const queryClient = useQueryClient()
  const [instructionType, setInstructionType] = useState<'global' | 'sku'>('global')
  const [skuCode, setSkuCode] = useState('')
  const [itemDetails, setItemDetails] = useState('')
  const [instructions, setInstructions] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)

  const { data: allInstructions, isLoading } = useQuery({
    queryKey: ['ai-instructions'],
    queryFn: async () => {
      const response = await messagesAPI.listAIInstructions()
      return response.data
    },
  })

  const { data: skus } = useQuery({
    queryKey: ['skus'],
    queryFn: async () => {
      const response = await stockAPI.listSKUs()
      return response.data
    },
  })

  const createMutation = useMutation({
    mutationFn: messagesAPI.createAIInstruction,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-instructions'] })
      resetForm()
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: { item_details?: string; instructions?: string } }) =>
      messagesAPI.updateAIInstruction(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-instructions'] })
      resetForm()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: messagesAPI.deleteAIInstruction,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-instructions'] })
    },
  })

  const resetForm = () => {
    setInstructionType('global')
    setSkuCode('')
    setItemDetails('')
    setInstructions('')
    setEditingId(null)
  }

  const handleEdit = (instr: AIInstruction) => {
    setInstructionType(instr.type)
    setSkuCode(instr.sku_code || '')
    setItemDetails(instr.item_details || '')
    setInstructions(instr.instructions)
    setEditingId(instr.id)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (editingId) {
      updateMutation.mutate({
        id: editingId,
        data: { item_details: itemDetails || undefined, instructions },
      })
    } else {
      createMutation.mutate({
        type: instructionType,
        sku_code: instructionType === 'sku' ? skuCode : undefined,
        item_details: itemDetails || undefined,
        instructions,
      })
    }
  }

  const globalInstruction = allInstructions?.find((i) => i.type === 'global')
  const skuInstructions = allInstructions?.filter((i) => i.type === 'sku') || []

  const [generating, setGenerating] = useState(false)
  const [generateError, setGenerateError] = useState<string | null>(null)
  const generateMutation = useMutation({
    mutationFn: () => messagesAPI.generateGlobalInstruction(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-instructions'] })
      setGenerateError(null)
    },
    onError: (e: unknown) => {
      const ax = e as { response?: { data?: { detail?: string } } }
      setGenerateError(ax.response?.data?.detail || (e instanceof Error ? e.message : 'Generation failed'))
    },
    onSettled: () => setGenerating(false),
  })

  const handleGenerateFromHistory = () => {
    setGenerateError(null)
    setGenerating(true)
    generateMutation.mutate()
  }

  return (
    <div className="px-4 py-6 sm:px-0">
      <div className="mb-4">
        <Link to="/messages" className="text-sm text-blue-600 hover:underline">
          ← Messages
        </Link>
      </div>
      <div className="bg-white shadow rounded-lg p-6">
        <h1 className="text-2xl font-bold text-gray-900 mb-4">AI Instructions</h1>
        <p className="text-gray-600 mb-6">
          Customize how AI drafts message replies. Global instructions apply to all messages.
          SKU-specific instructions override or supplement global ones for specific products.
        </p>

      {/* Add/Edit instruction form */}
      <form onSubmit={handleSubmit} className="mb-8 bg-gray-50 p-4 rounded-lg">
        <h3 className="font-medium mb-4">{editingId ? 'Edit Instruction' : 'Add Instruction'}</h3>
        <div className="grid grid-cols-1 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Type
            </label>
            <select
              value={instructionType}
              onChange={(e) => setInstructionType(e.target.value as 'global' | 'sku')}
              className="w-full border border-gray-300 rounded-md px-3 py-2"
              disabled={!!editingId}
            >
              <option value="global">Global (applies to all messages)</option>
              <option value="sku">SKU-specific</option>
            </select>
          </div>

          {instructionType === 'sku' && !editingId && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                SKU
              </label>
              <select
                value={skuCode}
                onChange={(e) => setSkuCode(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2"
                required
              >
                <option value="">Select a SKU...</option>
                {skus?.map((sku) => (
                  <option key={sku.sku_code} value={sku.sku_code}>
                    {sku.sku_code} - {sku.title}
                  </option>
                ))}
              </select>
            </div>
          )}

          {instructionType === 'sku' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Item Details (optional)
              </label>
              <textarea
                value={itemDetails}
                onChange={(e) => setItemDetails(e.target.value)}
                placeholder="Product specifications, common issues, shipping info..."
                rows={3}
                className="w-full border border-gray-300 rounded-md px-3 py-2"
              />
              <p className="text-xs text-gray-500 mt-1">
                Background info about this product that helps AI understand context
              </p>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Instructions
            </label>
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder={instructionType === 'global'
                ? "e.g., Be friendly and professional. Always offer solutions. Sign off with 'Best regards, [Your Team]'..."
                : "e.g., This product has a 30-day return policy. Common size issue: recommend one size up..."
              }
              rows={5}
              className="w-full border border-gray-300 rounded-md px-3 py-2"
              required
            />
            <p className="text-xs text-gray-500 mt-1">
              These instructions guide AI when drafting replies
            </p>
          </div>
        </div>
        <div className="flex gap-2 mt-4">
          <button
            type="submit"
            disabled={createMutation.isPending || updateMutation.isPending || (instructionType === 'global' && !editingId && !!globalInstruction)}
            className="bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50"
          >
            {createMutation.isPending || updateMutation.isPending
              ? 'Saving...'
              : editingId
              ? 'Update'
              : 'Add Instruction'}
          </button>
          {editingId && (
            <button
              type="button"
              onClick={resetForm}
              className="bg-gray-200 text-gray-700 px-4 py-2 rounded-md hover:bg-gray-300"
            >
              Cancel
            </button>
          )}
        </div>
        {instructionType === 'global' && !editingId && globalInstruction && (
          <p className="text-amber-600 text-sm mt-2">
            Global instruction already exists. Edit or delete it below.
          </p>
        )}
      </form>

      {/* Instructions list */}
      {isLoading ? (
        <p>Loading instructions...</p>
      ) : (
        <div className="space-y-6">
          {/* Global instruction */}
          <div>
            <div className="flex items-center gap-3 mb-2 flex-wrap">
              <h3 className="font-medium text-gray-800">Global Instruction</h3>
              <button
                type="button"
                onClick={handleGenerateFromHistory}
                disabled={generating}
                className="px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 text-sm"
              >
                {generating ? 'Generating...' : 'Generate from history'}
              </button>
              {generateError && (
                <span className="text-red-600 text-sm">{generateError}</span>
              )}
            </div>
            {globalInstruction ? (
              <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <pre className="whitespace-pre-wrap text-sm text-gray-700 font-sans">
                      {globalInstruction.instructions}
                    </pre>
                  </div>
                  <div className="flex gap-2 ml-4">
                    <button
                      onClick={() => handleEdit(globalInstruction)}
                      className="text-blue-600 hover:text-blue-800 text-sm"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => deleteMutation.mutate(globalInstruction.id)}
                      className="text-red-600 hover:text-red-800 text-sm"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-gray-500 text-center py-4 bg-gray-50 rounded-lg">
                No global instruction set. Add one above.
              </p>
            )}
          </div>

          {/* SKU-specific instructions */}
          <div>
            <h3 className="font-medium text-gray-800 mb-2">SKU-Specific Instructions ({skuInstructions.length})</h3>
            {skuInstructions.length > 0 ? (
              <div className="space-y-3">
                {skuInstructions.map((instr) => (
                  <div
                    key={instr.id}
                    className="p-4 bg-gray-50 rounded-lg"
                  >
                    <div className="flex justify-between items-start">
                      <div className="flex-1">
                        <div className="font-medium text-gray-800">{instr.sku_code}</div>
                        {instr.item_details && (
                          <div className="text-sm text-gray-600 mt-1 italic">
                            {instr.item_details}
                          </div>
                        )}
                        <pre className="whitespace-pre-wrap text-sm text-gray-700 mt-2 font-sans">
                          {instr.instructions}
                        </pre>
                      </div>
                      <div className="flex gap-2 ml-4">
                        <button
                          onClick={() => handleEdit(instr)}
                          className="text-blue-600 hover:text-blue-800 text-sm"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => deleteMutation.mutate(instr.id)}
                          className="text-red-600 hover:text-red-800 text-sm"
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-gray-500 text-center py-4 bg-gray-50 rounded-lg">
                No SKU-specific instructions. Add one above when needed.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
    </div>
  )
}
