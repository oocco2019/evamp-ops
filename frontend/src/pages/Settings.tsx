import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { settingsAPI, stockAPI, messagesAPI, inventoryStatusAPI, type AIModelSetting, type APICredential, type Warehouse, type EmailTemplate, type AIInstruction, type OCConnection } from '../services/api'

export default function Settings() {
  const [activeTab, setActiveTab] = useState<'credentials' | 'ai-models' | 'ai-instructions' | 'ebay' | 'oc' | 'warehouses' | 'email-templates'>('credentials')

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const connected = params.get('ebay_connected') === '1'
    const hasEbayParam = connected || params.get('ebay_error')
    if (hasEbayParam) {
      const next = new URLSearchParams(params)
      next.delete('ebay_connected')
      next.delete('ebay_error')
      next.delete('ebay_error_detail')
      const search = next.toString()
      window.history.replaceState({}, '', window.location.pathname + (search ? `?${search}` : ''))
    }
  }, [])

  return (
    <div className="px-4 py-6 sm:px-0">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900">Settings</h1>
        <p className="mt-2 text-gray-600">
          Manage API credentials, AI models, and warehouse addresses.
        </p>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200 mb-6">
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => setActiveTab('credentials')}
            className={`${
              activeTab === 'credentials'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            API Credentials
          </button>
          <button
            onClick={() => setActiveTab('ai-models')}
            className={`${
              activeTab === 'ai-models'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            AI Models
          </button>
          <button
            onClick={() => setActiveTab('ai-instructions')}
            className={`${
              activeTab === 'ai-instructions'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            AI Instructions
          </button>
          <button
            onClick={() => setActiveTab('ebay')}
            className={`${
              activeTab === 'ebay'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            eBay
          </button>
          <button
            onClick={() => setActiveTab('oc')}
            className={`${
              activeTab === 'oc'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            OC Integration
          </button>
          <button
            onClick={() => setActiveTab('warehouses')}
            className={`${
              activeTab === 'warehouses'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            Warehouses
          </button>
          <button
            onClick={() => setActiveTab('email-templates')}
            className={`${
              activeTab === 'email-templates'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            Email Templates
          </button>
        </nav>
      </div>

      {/* Tab content */}
      {activeTab === 'credentials' && <CredentialsTab />}
      {activeTab === 'ai-models' && <AIModelsTab />}
      {activeTab === 'ai-instructions' && <AIInstructionsTab />}
      {activeTab === 'ebay' && <EbayTab />}
      {activeTab === 'oc' && <OCTab />}
      {activeTab === 'email-templates' && <EmailTemplatesTab />}
      {activeTab === 'warehouses' && <WarehousesTab />}
    </div>
  )
}

function CredentialsTab() {
  const queryClient = useQueryClient()
  const [serviceName, setServiceName] = useState('')
  const [keyValue, setKeyValue] = useState('')

  // For AI providers (anthropic, openai), key_name is always "api_key"
  const isAIProvider = serviceName === 'anthropic' || serviceName === 'openai'
  const keyName = isAIProvider ? 'api_key' : ''

  const { data: credentials, isLoading } = useQuery({
    queryKey: ['credentials'],
    queryFn: async () => {
      const response = await settingsAPI.listCredentials()
      return response.data
    },
  })

  const createMutation = useMutation({
    mutationFn: settingsAPI.createCredential,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
      setServiceName('')
      setKeyValue('')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: settingsAPI.deleteCredential,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    createMutation.mutate({
      service_name: serviceName,
      key_name: keyName,
      value: keyValue,
    })
  }

  return (
    <div className="bg-white shadow rounded-lg p-6">
      <h2 className="text-xl font-semibold mb-4">API Credentials</h2>
      <p className="text-gray-600 mb-6">
        Store API keys for AI providers (Anthropic, OpenAI). eBay app keys (App ID, Cert, etc.) are in .env; the eBay OAuth token (refresh_token) is stored here after you use Connect with eBay and persists across <code className="bg-gray-200 px-1 rounded">make down</code> / <code className="bg-gray-200 px-1 rounded">make up</code> (database volume is kept). All values are encrypted.
      </p>

      {/* Add credential form */}
      <form onSubmit={handleSubmit} className="mb-8 bg-gray-50 p-4 rounded-lg">
        <h3 className="font-medium mb-4">Add AI Provider API Key</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Provider
            </label>
            <select
              value={serviceName}
              onChange={(e) => setServiceName(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2"
              required
            >
              <option value="">Select provider...</option>
              <option value="anthropic">Anthropic (Claude)</option>
              <option value="openai">OpenAI (GPT)</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              API Key
            </label>
            <input
              type="password"
              value={keyValue}
              onChange={(e) => setKeyValue(e.target.value)}
              placeholder={serviceName === 'anthropic' ? 'sk-ant-...' : serviceName === 'openai' ? 'sk-...' : 'Select a provider first'}
              className="w-full border border-gray-300 rounded-md px-3 py-2"
              required
              disabled={!serviceName}
            />
          </div>
        </div>
        <p className="mt-2 text-sm text-gray-500">
          {serviceName === 'anthropic' && 'Get your API key from console.anthropic.com'}
          {serviceName === 'openai' && 'Get your API key from platform.openai.com'}
          {!serviceName && 'Select a provider to add its API key'}
        </p>
        <button
          type="submit"
          disabled={createMutation.isPending || !serviceName}
          className="mt-4 bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50"
        >
          {createMutation.isPending ? 'Adding...' : 'Add API Key'}
        </button>
      </form>

      {/* Credentials list */}
      {isLoading ? (
        <p>Loading credentials...</p>
      ) : (
        <div className="space-y-2">
          {credentials && credentials.length > 0 ? (
            credentials.map((cred: APICredential) => (
              <div
                key={cred.id}
                className="flex items-center justify-between p-3 bg-gray-50 rounded-lg"
              >
                <div>
                  <span className="font-medium">{cred.service_name}</span>
                  <span className="text-gray-600 mx-2">/</span>
                  <span className="text-gray-700">{cred.key_name}</span>
                  {cred.is_active && (
                    <span className="ml-2 text-xs bg-green-100 text-green-800 px-2 py-1 rounded">
                      Active
                    </span>
                  )}
                </div>
                <button
                  onClick={() => deleteMutation.mutate(cred.id)}
                  className="text-red-600 hover:text-red-800 text-sm"
                >
                  Delete
                </button>
              </div>
            ))
          ) : (
            <p className="text-gray-500 text-center py-4">
              No credentials stored yet. Add one above to get started.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function OCTab() {
  const queryClient = useQueryClient()
  const [keyName, setKeyName] = useState<'client_id' | 'client_secret' | 'refresh_token'>('client_id')
  const [keyValue, setKeyValue] = useState('')
  const [connectionDraft, setConnectionDraft] = useState<OCConnection>({
    id: 0,
    name: 'OC',
    region: 'UK',
    environment: 'stage',
    oauth_base_url: 'https://openapi-stage-cn.orangeconnex.com',
    api_base_url: 'https://openapi-stage-cn.orangeconnex.com',
    signature_mode: 'path_and_body',
    is_active: true,
    updated_at: new Date().toISOString(),
  })
  const [redirectUri, setRedirectUri] = useState(window.location.origin + '/settings')
  const [oauthState, setOauthState] = useState('oocco')
  const [authCode, setAuthCode] = useState('')
  const [authorizeUrl, setAuthorizeUrl] = useState('')

  const { data: summary } = useQuery({
    queryKey: ['inventory-status', 'summary'],
    queryFn: async () => (await inventoryStatusAPI.getSummary()).data,
  })

  const { data: ocCreds, isLoading } = useQuery({
    queryKey: ['credentials', 'oc'],
    queryFn: async () => (await settingsAPI.listCredentials('oc')).data,
  })

  useEffect(() => {
    if (summary?.connection) {
      setConnectionDraft(summary.connection)
    }
  }, [summary?.connection])

  const createCredentialMutation = useMutation({
    mutationFn: settingsAPI.createCredential,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials', 'oc'] })
      queryClient.invalidateQueries({ queryKey: ['inventory-status'] })
      setKeyValue('')
    },
  })

  const deleteCredentialMutation = useMutation({
    mutationFn: settingsAPI.deleteCredential,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials', 'oc'] })
      queryClient.invalidateQueries({ queryKey: ['inventory-status'] })
    },
  })

  const upsertConnection = useMutation({
    mutationFn: inventoryStatusAPI.upsertConnection,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['inventory-status'] })
    },
  })

  const testConnection = useMutation({
    mutationFn: inventoryStatusAPI.testConnection,
  })
  const buildAuthorizeUrl = useMutation({
    mutationFn: inventoryStatusAPI.getAuthorizeUrl,
    onSuccess: (res) => {
      setAuthorizeUrl(res.data.authorize_url)
    },
  })
  const exchangeCode = useMutation({
    mutationFn: inventoryStatusAPI.exchangeCode,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials', 'oc'] })
      queryClient.invalidateQueries({ queryKey: ['inventory-status'] })
      setAuthCode('')
    },
  })

  const missingRequired = ['client_id', 'client_secret', 'refresh_token'].filter(
    (k) => !(summary?.credentials_present ?? []).includes(k)
  )

  return (
    <div className="space-y-6">
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-xl font-semibold mb-2">OrangeConnex credentials</h2>
        <p className="text-sm text-gray-600 mb-4">
          Add OC secrets here (`service_name=oc`). Inventory Status page stays read-only.
        </p>

        <form
          className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end mb-4"
          onSubmit={(e) => {
            e.preventDefault()
            createCredentialMutation.mutate({
              service_name: 'oc',
              key_name: keyName,
              value: keyValue,
            })
          }}
        >
          <label className="flex flex-col gap-1">
            <span className="text-sm text-gray-700">Key name</span>
            <select
              className="border border-gray-300 rounded-md px-3 py-2"
              value={keyName}
              onChange={(e) => setKeyName(e.target.value as 'client_id' | 'client_secret' | 'refresh_token')}
            >
              <option value="client_id">client_id</option>
              <option value="client_secret">client_secret</option>
              <option value="refresh_token">refresh_token</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 md:col-span-2">
            <span className="text-sm text-gray-700">Value</span>
            <input
              type="password"
              className="border border-gray-300 rounded-md px-3 py-2"
              value={keyValue}
              onChange={(e) => setKeyValue(e.target.value)}
              required
            />
          </label>
          <button
            type="submit"
            disabled={createCredentialMutation.isPending || !keyValue.trim()}
            className="bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50"
          >
            {createCredentialMutation.isPending ? 'Saving...' : 'Save OC key'}
          </button>
        </form>

        <p className={`text-sm mb-3 ${missingRequired.length === 0 ? 'text-green-700' : 'text-amber-700'}`}>
          {missingRequired.length === 0 ? 'All required OC credentials are present.' : `Missing: ${missingRequired.join(', ')}`}
        </p>

        {isLoading ? (
          <p className="text-sm text-gray-500">Loading OC credentials...</p>
        ) : (
          <div className="space-y-2">
            {(ocCreds ?? []).map((cred) => (
              <div key={cred.id} className="flex items-center justify-between p-2 bg-gray-50 rounded">
                <span className="text-sm">{cred.service_name} / {cred.key_name}</span>
                <button
                  onClick={() => deleteCredentialMutation.mutate(cred.id)}
                  className="text-red-600 hover:text-red-800 text-sm"
                >
                  Delete
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-xl font-semibold mb-2">OrangeConnex connection</h2>
        <p className="text-sm text-gray-600 mb-2">Non-secret connection details and connectivity test.</p>
        <p className="text-xs text-gray-500 mb-4">
          Use the exact host values provided by OC for your tenant and environment.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-gray-700">Name</span>
            <input className="rounded border border-gray-300 px-2 py-1.5" value={connectionDraft.name} onChange={(e) => setConnectionDraft((p) => ({ ...p, name: e.target.value }))} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-gray-700">Region</span>
            <input className="rounded border border-gray-300 px-2 py-1.5" value={connectionDraft.region} onChange={(e) => setConnectionDraft((p) => ({ ...p, region: e.target.value.toUpperCase() }))} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-gray-700">Environment</span>
            <select className="rounded border border-gray-300 px-2 py-1.5" value={connectionDraft.environment} onChange={(e) => setConnectionDraft((p) => ({ ...p, environment: e.target.value as 'stage' | 'prod' }))}>
              <option value="stage">stage</option>
              <option value="prod">prod</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm lg:col-span-2">
            <span className="text-gray-700">OAuth base URL</span>
            <input className="rounded border border-gray-300 px-2 py-1.5" value={connectionDraft.oauth_base_url} onChange={(e) => setConnectionDraft((p) => ({ ...p, oauth_base_url: e.target.value }))} />
          </label>
          <label className="flex flex-col gap-1 text-sm lg:col-span-2">
            <span className="text-gray-700">API base URL</span>
            <input className="rounded border border-gray-300 px-2 py-1.5" value={connectionDraft.api_base_url} onChange={(e) => setConnectionDraft((p) => ({ ...p, api_base_url: e.target.value }))} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-gray-700">Signature mode</span>
            <select className="rounded border border-gray-300 px-2 py-1.5" value={connectionDraft.signature_mode} onChange={(e) => setConnectionDraft((p) => ({ ...p, signature_mode: e.target.value as 'path_only' | 'path_and_body' }))}>
              <option value="path_and_body">path_and_body</option>
              <option value="path_only">path_only</option>
            </select>
          </label>
        </div>
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            onClick={() => upsertConnection.mutate(connectionDraft)}
            className="px-3 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            disabled={upsertConnection.isPending}
          >
            {upsertConnection.isPending ? 'Saving...' : 'Save connection'}
          </button>
          <button
            type="button"
            onClick={() => testConnection.mutate()}
            className="px-3 py-2 bg-gray-700 text-white rounded hover:bg-gray-800 disabled:opacity-50"
            disabled={testConnection.isPending}
          >
            {testConnection.isPending ? 'Testing...' : 'Test connection'}
          </button>
        </div>
        {testConnection.isSuccess && (
          <p className="text-sm text-green-700 mt-2">
            Connection OK: {testConnection.data?.data.environment?.toUpperCase()} {testConnection.data?.data.region}
            {' '}services={testConnection.data?.data.service_count ?? 0}
          </p>
        )}
        {testConnection.isError && (
          <p className="text-sm text-red-700 mt-2">
            {(() => {
              const ax = testConnection.error as { response?: { data?: { detail?: string } }; message?: string }
              return ax.response?.data?.detail || ax.message || 'Connection test failed'
            })()}
          </p>
        )}
      </div>

      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-xl font-semibold mb-2">OAuth: get refresh token</h2>
        <p className="text-sm text-gray-600 mb-4">
          Generate OC authorize URL, complete login/consent, then paste returned code to store refresh_token.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-gray-700">Redirect URI</span>
            <input className="rounded border border-gray-300 px-2 py-1.5" value={redirectUri} onChange={(e) => setRedirectUri(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-gray-700">State (optional)</span>
            <input className="rounded border border-gray-300 px-2 py-1.5" value={oauthState} onChange={(e) => setOauthState(e.target.value)} />
          </label>
        </div>
        <div className="flex flex-wrap gap-2 mb-3">
          <button
            type="button"
            onClick={() => buildAuthorizeUrl.mutate({ redirect_uri: redirectUri.trim(), state: oauthState.trim() || undefined })}
            className="px-3 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
            disabled={buildAuthorizeUrl.isPending || !redirectUri.trim()}
          >
            {buildAuthorizeUrl.isPending ? 'Generating...' : 'Generate authorize URL'}
          </button>
          {authorizeUrl && (
            <a
              href={authorizeUrl}
              target="_blank"
              rel="noreferrer"
              className="px-3 py-2 bg-indigo-100 text-indigo-800 rounded hover:bg-indigo-200"
            >
              Open authorize URL
            </a>
          )}
        </div>
        {buildAuthorizeUrl.isError && (
          <p className="text-sm text-red-700 mb-2">
            {(() => {
              const ax = buildAuthorizeUrl.error as { response?: { data?: { detail?: string } }; message?: string }
              return ax.response?.data?.detail || ax.message || 'Failed to build authorize URL'
            })()}
          </p>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 items-end">
          <label className="flex flex-col gap-1 text-sm md:col-span-2">
            <span className="text-gray-700">Authorization code (from redirect URL)</span>
            <input className="rounded border border-gray-300 px-2 py-1.5" value={authCode} onChange={(e) => setAuthCode(e.target.value)} placeholder="Paste code=... value here" />
          </label>
          <button
            type="button"
            onClick={() => exchangeCode.mutate({ code: authCode.trim(), redirect_uri: redirectUri.trim() })}
            className="px-3 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
            disabled={exchangeCode.isPending || !authCode.trim() || !redirectUri.trim()}
          >
            {exchangeCode.isPending ? 'Exchanging...' : 'Exchange code and save refresh token'}
          </button>
        </div>
        {exchangeCode.isSuccess && (
          <p className="text-sm text-green-700 mt-2">
            refresh_token stored. Access token received: {exchangeCode.data?.data.access_token_received ? 'yes' : 'no'}.
          </p>
        )}
        {exchangeCode.isError && (
          <p className="text-sm text-red-700 mt-2">
            {(() => {
              const ax = exchangeCode.error as { response?: { data?: { detail?: string } }; message?: string }
              return ax.response?.data?.detail || ax.message || 'Code exchange failed'
            })()}
          </p>
        )}
      </div>
    </div>
  )
}

function AIModelsTab() {
  const queryClient = useQueryClient()
  const [provider, setProvider] = useState('')
  const [modelName, setModelName] = useState('')
  const [isDefault, setIsDefault] = useState(false)

  const { data: models, isLoading } = useQuery({
    queryKey: ['ai-models'],
    queryFn: async () => {
      const response = await settingsAPI.listAIModels()
      return response.data
    },
  })

  const { data: credentials } = useQuery({
    queryKey: ['credentials'],
    queryFn: async () => {
      const response = await settingsAPI.listCredentials()
      return response.data
    },
  })

  const createMutation = useMutation({
    mutationFn: settingsAPI.createAIModel,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-models'] })
      setProvider('')
      setModelName('')
      setIsDefault(false)
    },
  })

  const setDefaultMutation = useMutation({
    mutationFn: settingsAPI.setDefaultAIModel,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-models'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: settingsAPI.deleteAIModel,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-models'] })
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    createMutation.mutate({
      provider,
      model_name: modelName,
      is_default: isDefault,
      temperature: 0.7,
      max_tokens: 2000,
    })
  }

  const modelOptions: Record<string, string[]> = {
    anthropic: [
      'claude-sonnet-4-5-20250929',
      'claude-haiku-4-5-20251001',
      'claude-opus-4-5-20251101',
      'claude-3-haiku-20240307',
    ],
    openai: ['gpt-4-turbo-preview', 'gpt-4', 'gpt-3.5-turbo'],
  }

  // Check if there's a default model and matching credentials
  const defaultModel = models?.find((m: AIModelSetting) => m.is_default)
  const hasMatchingCredential = defaultModel
    ? credentials?.some(
        (c: APICredential) => c.service_name === defaultModel.provider && c.key_name === 'api_key' && c.is_active
      )
    : false
  const isAIReady = defaultModel && hasMatchingCredential

  return (
    <div className="bg-white shadow rounded-lg p-6">
      <h2 className="text-xl font-semibold mb-4">AI Model Configuration</h2>
      <p className="text-gray-600 mb-6">
        Configure which AI model to use for message drafting and translation.
      </p>

      {/* Status indicator */}
      <div className={`mb-6 p-4 rounded-lg border ${isAIReady ? 'bg-green-50 border-green-200' : 'bg-amber-50 border-amber-200'}`}>
        <h3 className={`font-medium ${isAIReady ? 'text-green-800' : 'text-amber-800'}`}>
          AI Status: {isAIReady ? 'Ready' : 'Not configured'}
        </h3>
        {!isAIReady && (
          <ul className="mt-2 text-sm text-amber-700 list-disc list-inside">
            {!defaultModel && <li>Add an AI model and set it as default (below)</li>}
            {defaultModel && !hasMatchingCredential && (
              <li>
                Add {defaultModel.provider} API key in the <strong>API Credentials</strong> tab
              </li>
            )}
          </ul>
        )}
        {isAIReady && (
          <p className="mt-1 text-sm text-green-700">
            Using {defaultModel.provider} / {defaultModel.model_name}. AI drafting is enabled.
          </p>
        )}
      </div>

      {/* Add model form */}
      <form onSubmit={handleSubmit} className="mb-8 bg-gray-50 p-4 rounded-lg">
        <h3 className="font-medium mb-4">Add AI Model</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Provider
            </label>
            <select
              value={provider}
              onChange={(e) => {
                setProvider(e.target.value)
                setModelName('')
              }}
              className="w-full border border-gray-300 rounded-md px-3 py-2"
              required
            >
              <option value="">Select provider...</option>
              <option value="anthropic">Anthropic (Claude)</option>
              <option value="openai">OpenAI (GPT)</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Model
            </label>
            <select
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2"
              required
              disabled={!provider}
            >
              <option value="">Select model...</option>
              {provider &&
                modelOptions[provider]?.map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
            </select>
          </div>
        </div>
        <div className="mt-4">
          <label className="flex items-center">
            <input
              type="checkbox"
              checked={isDefault}
              onChange={(e) => setIsDefault(e.target.checked)}
              className="mr-2"
            />
            <span className="text-sm text-gray-700">Set as default model</span>
          </label>
        </div>
        <button
          type="submit"
          disabled={createMutation.isPending}
          className="mt-4 bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50"
        >
          {createMutation.isPending ? 'Adding...' : 'Add Model'}
        </button>
      </form>

      {/* Models list */}
      {isLoading ? (
        <p>Loading AI models...</p>
      ) : (
        <div className="space-y-2">
          {models && models.length > 0 ? (
            models.map((model: AIModelSetting) => (
              <div
                key={model.id}
                className="flex items-center justify-between p-3 bg-gray-50 rounded-lg"
              >
                <div>
                  <span className="font-medium">{model.provider}</span>
                  <span className="text-gray-600 mx-2">/</span>
                  <span className="text-gray-700">{model.model_name}</span>
                  {model.is_default && (
                    <span className="ml-2 text-xs bg-blue-100 text-blue-800 px-2 py-1 rounded">
                      Default
                    </span>
                  )}
                </div>
                <div className="flex gap-2">
                  {!model.is_default && (
                    <button
                      onClick={() => setDefaultMutation.mutate(model.id)}
                      className="text-blue-600 hover:text-blue-800 text-sm"
                    >
                      Set Default
                    </button>
                  )}
                  <button
                    onClick={() => deleteMutation.mutate(model.id)}
                    className="text-red-600 hover:text-red-800 text-sm"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))
          ) : (
            <p className="text-gray-500 text-center py-4">
              No AI models configured yet. Add one above to enable AI features.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function AIInstructionsTab() {
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
    <div className="bg-white shadow rounded-lg p-6">
      <h2 className="text-xl font-semibold mb-4">AI Instructions</h2>
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
  )
}

function EbayTab() {
  const queryClient = useQueryClient()
  const [connectError, setConnectError] = useState<string | null>(null)
  const [importResult, setImportResult] = useState<{
    orders_added: number
    orders_updated: number
    line_items_added: number
    line_items_updated: number
    error?: string
  } | null>(null)

  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ['ebay-status'],
    queryFn: async () => {
      const response = await stockAPI.getEbayStatus()
      return response.data
    },
  })

  const { data: callbackUrlData } = useQuery({
    queryKey: ['ebay-callback-url'],
    queryFn: async () => {
      const response = await stockAPI.getEbayCallbackUrl()
      return response.data
    },
  })

  const authUrlQuery = useQuery({
    queryKey: ['ebay-auth-url'],
    queryFn: async () => {
      const response = await stockAPI.getEbayAuthUrl()
      return response.data
    },
    enabled: false,
  })

  const connectMutation = useMutation({
    mutationFn: async () => {
      setConnectError(null)
      const { data } = await stockAPI.getEbayAuthUrl()
      window.location.href = data.url
    },
    onError: (err: unknown) => {
      const message =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      setConnectError(
        typeof message === 'string'
          ? message
          : Array.isArray(message)
            ? message.map((m: { msg?: string }) => m?.msg ?? JSON.stringify(m)).join(', ')
            : err instanceof Error
              ? err.message
              : 'Failed to get eBay auth URL. Check backend and .env (EBAY_APP_ID, EBAY_REDIRECT_URI RuName).'
      )
    },
  })

  const importMutation = useMutation({
    mutationFn: (mode: 'full' | 'incremental') => stockAPI.runImport(mode),
    onSuccess: (response) => {
      setImportResult({
        orders_added: response.data.orders_added,
        orders_updated: response.data.orders_updated,
        line_items_added: response.data.line_items_added,
        line_items_updated: response.data.line_items_updated,
        error: response.data.error,
      })
    },
    onError: (err: unknown) => {
      const msg =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null
      const errorStr =
        typeof msg === 'string'
          ? msg
          : err instanceof Error
            ? err.message
            : 'Import request failed'
      setImportResult({
        orders_added: 0,
        orders_updated: 0,
        line_items_added: 0,
        line_items_updated: 0,
        error: errorStr,
      })
    },
  })

  const [urlParams] = useState(() => new URLSearchParams(typeof window !== 'undefined' ? window.location.search : ''))
  const justConnected = urlParams.get('ebay_connected') === '1'
  const ebayError = urlParams.get('ebay_error')
  const ebayErrorDetail = urlParams.get('ebay_error_detail')

  return (
    <div className="bg-white shadow rounded-lg p-6">
      <h2 className="text-xl font-semibold mb-4">eBay Connection</h2>
      <p className="text-gray-600 mb-6">
        Connect your eBay account to import orders. Configure EBAY_APP_ID, EBAY_CERT_ID, EBAY_DEV_ID and EBAY_REDIRECT_URI in .env.
      </p>

      {callbackUrlData && (
        <div className="mb-6 p-3 bg-gray-50 border border-gray-200 rounded-lg text-sm">
          <h3 className="font-medium mb-1">Callback URL for eBay</h3>
          {callbackUrlData.callback_url ? (
            (() => {
              const baseUrl = new URL(callbackUrlData.callback_url).origin;
              const linkRow = (url: string) => (
                <div className="flex flex-wrap items-center gap-2 mb-2">
                  <code className="flex-1 min-w-0 break-all bg-white px-2 py-1 rounded border text-gray-800">
                    {url}
                  </code>
                  <button
                    type="button"
                    onClick={() => navigator.clipboard.writeText(url)}
                    className="shrink-0 px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700"
                  >
                    Copy
                  </button>
                </div>
              );
              return (
                <>
                  <p className="text-gray-600 mb-1 font-medium">Set once:</p>
                  <p className="text-gray-600 mb-1">Paste this in eBay Developer Portal → User Tokens → Auth Accepted URL.</p>
                  {linkRow(callbackUrlData.callback_url)}
                  <p className="text-gray-600 mb-1">Set once: Paste this in eBay Developer Portal → User Tokens → Auth Declined URL.</p>
                  {linkRow(baseUrl)}
                  <p className="text-gray-600 mb-1">Set once: Paste it in .env CALLBACK_BASE_URL=</p>
                  {linkRow(baseUrl)}
                </>
              );
            })()
          ) : (
            <p className="text-amber-700">
              Set CALLBACK_BASE_URL in .env to your tunnel URL (e.g. from localhost.run), restart the backend, then refresh.
            </p>
          )}
        </div>
      )}

      {justConnected && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-green-800">
          eBay account connected successfully.
        </div>
      )}

      {ebayError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          <p className="font-medium">eBay connection failed: {ebayError.replace(/_/g, ' ')}</p>
          {ebayErrorDetail && (
            <p className="mt-2 text-red-700 break-words">{decodeURIComponent(ebayErrorDetail)}</p>
          )}
          <p className="mt-2 text-red-600">
            Common causes: code expired (complete the flow quickly); redirect_uri must match exactly (RuName in .env and Auth Accepted URL in eBay portal).
          </p>
        </div>
      )}

      <div className="mb-8">
        <h3 className="font-medium mb-2">Status</h3>
        {statusLoading ? (
          <p className="text-gray-500">Checking...</p>
        ) : status?.connected ? (
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-green-700 font-medium">Connected</p>
            <button
              type="button"
              onClick={() => connectMutation.mutate()}
              disabled={connectMutation.isPending}
              className="text-blue-600 hover:text-blue-800 underline disabled:opacity-50"
            >
              {connectMutation.isPending ? 'Redirecting...' : 'Reconnect eBay'}
            </button>
            <span className="text-gray-500 text-sm">
              (Use to refresh permissions, e.g. after adding message scope)
            </span>
          </div>
        ) : (
          <p className="text-gray-600">Not connected</p>
        )}
        {!status?.connected && (
          <>
            <button
              type="button"
              onClick={() => connectMutation.mutate()}
              disabled={connectMutation.isPending}
              className="mt-2 bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50"
            >
              {connectMutation.isPending ? 'Redirecting...' : 'Connect with eBay'}
            </button>
            {connectError && (
              <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
                {connectError}
              </div>
            )}
          </>
        )}
      </div>

      {status?.connected && (
        <div className="mb-8">
          <h3 className="font-medium mb-2">Import orders</h3>
          <p className="text-gray-600 text-sm mb-2">
            Full: last 90 days (eBay API limit). Incremental: since last import.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => importMutation.mutate('full')}
              disabled={importMutation.isPending}
              className="bg-gray-700 text-white px-4 py-2 rounded-md hover:bg-gray-800 disabled:opacity-50"
            >
              Full import
            </button>
            <button
              type="button"
              onClick={() => importMutation.mutate('incremental')}
              disabled={importMutation.isPending}
              className="bg-gray-600 text-white px-4 py-2 rounded-md hover:bg-gray-700 disabled:opacity-50"
            >
              Incremental import
            </button>
          </div>
          {importResult && (
            <div className="mt-3 p-3 bg-gray-50 rounded-lg text-sm">
              <p>Orders added: {importResult.orders_added} (new orders from eBay)</p>
              <p>Orders updated: {importResult.orders_updated} (existing orders refreshed from eBay)</p>
              <p>Line items added: {importResult.line_items_added} (new line items)</p>
              <p>Line items updated: {importResult.line_items_updated} (existing line items refreshed)</p>
              {importResult.error && (
                <p className="text-red-600 mt-2">Error: {importResult.error}</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function WarehousesTab() {
  const queryClient = useQueryClient()
  const [shortname, setShortname] = useState('')
  const [address, setAddress] = useState('')
  const [countryCode, setCountryCode] = useState('')

  const { data: warehouses, isLoading } = useQuery({
    queryKey: ['warehouses'],
    queryFn: async () => {
      const response = await settingsAPI.listWarehouses()
      return response.data
    },
  })

  const createMutation = useMutation({
    mutationFn: settingsAPI.createWarehouse,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['warehouses'] })
      setShortname('')
      setAddress('')
      setCountryCode('')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: settingsAPI.deleteWarehouse,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['warehouses'] })
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    createMutation.mutate({
      shortname,
      address,
      country_code: countryCode,
    })
  }

  return (
    <div className="bg-white shadow rounded-lg p-6">
      <h2 className="text-xl font-semibold mb-4">Warehouse Addresses</h2>
      <p className="text-gray-600 mb-6">
        Manage warehouse addresses for supplier order messages.
      </p>

      {/* Add warehouse form */}
      <form onSubmit={handleSubmit} className="mb-8 bg-gray-50 p-4 rounded-lg">
        <h3 className="font-medium mb-4">Add Warehouse</h3>
        <div className="grid grid-cols-1 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Shortname
            </label>
            <input
              type="text"
              value={shortname}
              onChange={(e) => setShortname(e.target.value)}
              placeholder="e.g., UK-Main"
              className="w-full border border-gray-300 rounded-md px-3 py-2"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Address
            </label>
            <textarea
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="Full warehouse address"
              rows={3}
              className="w-full border border-gray-300 rounded-md px-3 py-2"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Country Code
            </label>
            <input
              type="text"
              value={countryCode}
              onChange={(e) => setCountryCode(e.target.value.toUpperCase())}
              placeholder="e.g., UK, US, DE"
              maxLength={2}
              className="w-full border border-gray-300 rounded-md px-3 py-2"
              required
            />
          </div>
        </div>
        <button
          type="submit"
          disabled={createMutation.isPending}
          className="mt-4 bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50"
        >
          {createMutation.isPending ? 'Adding...' : 'Add Warehouse'}
        </button>
      </form>

      {/* Warehouses list */}
      {isLoading ? (
        <p>Loading warehouses...</p>
      ) : (
        <div className="space-y-2">
          {warehouses && warehouses.length > 0 ? (
            warehouses.map((warehouse: Warehouse) => (
              <div
                key={warehouse.id}
                className="flex items-start justify-between p-3 bg-gray-50 rounded-lg"
              >
                <div>
                  <div className="font-medium">
                    {warehouse.shortname}{' '}
                    <span className="text-gray-500">({warehouse.country_code})</span>
                  </div>
                  <div className="text-sm text-gray-600 mt-1 whitespace-pre-wrap">
                    {warehouse.address}
                  </div>
                </div>
                <button
                  onClick={() => deleteMutation.mutate(warehouse.id)}
                  className="text-red-600 hover:text-red-800 text-sm"
                >
                  Delete
                </button>
              </div>
            ))
          ) : (
            <p className="text-gray-500 text-center py-4">
              No warehouses configured yet. Add one above to get started.
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function EmailTemplatesTab() {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [recipientEmail, setRecipientEmail] = useState('')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)

  const { data: templates, isLoading } = useQuery({
    queryKey: ['email-templates'],
    queryFn: async () => {
      const response = await settingsAPI.listEmailTemplates()
      return response.data
    },
  })

  const createMutation = useMutation({
    mutationFn: settingsAPI.createEmailTemplate,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['email-templates'] })
      resetForm()
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: { name: string; recipient_email: string; subject: string; body: string } }) =>
      settingsAPI.updateEmailTemplate(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['email-templates'] })
      resetForm()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: settingsAPI.deleteEmailTemplate,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['email-templates'] })
    },
  })

  const resetForm = () => {
    setName('')
    setRecipientEmail('')
    setSubject('')
    setBody('')
    setEditingId(null)
  }

  const handleEdit = (template: EmailTemplate) => {
    setName(template.name)
    setRecipientEmail(template.recipient_email)
    setSubject(template.subject)
    setBody(template.body)
    setEditingId(template.id)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const data = { name, recipient_email: recipientEmail, subject, body }
    if (editingId) {
      updateMutation.mutate({ id: editingId, data })
    } else {
      createMutation.mutate(data)
    }
  }

  return (
    <div className="bg-white shadow rounded-lg p-6">
      <h2 className="text-xl font-semibold mb-4">Email Templates</h2>
      <p className="text-gray-600 mb-6">
        Create email templates for warehouse inquiries. Use variables: {'{tracking_number}'}, {'{order_date}'}, {'{delivery_country}'}, {'{order_id}'}, {'{buyer_username}'}
      </p>

      {/* Add/Edit template form */}
      <form onSubmit={handleSubmit} className="mb-8 bg-gray-50 p-4 rounded-lg">
        <h3 className="font-medium mb-4">{editingId ? 'Edit Template' : 'Add Template'}</h3>
        <div className="grid grid-cols-1 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Template Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Warehouse Status Inquiry"
              className="w-full border border-gray-300 rounded-md px-3 py-2"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Recipient Email
            </label>
            <input
              type="email"
              value={recipientEmail}
              onChange={(e) => setRecipientEmail(e.target.value)}
              placeholder="warehouse@example.com"
              className="w-full border border-gray-300 rounded-md px-3 py-2"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Subject
            </label>
            <input
              type="text"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="Order Status Inquiry - {order_id}"
              className="w-full border border-gray-300 rounded-md px-3 py-2"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Body
            </label>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Hi,&#10;&#10;Could you please provide the status for order {order_id}?&#10;&#10;Tracking: {tracking_number}&#10;Country: {delivery_country}&#10;&#10;Thanks"
              rows={6}
              className="w-full border border-gray-300 rounded-md px-3 py-2"
              required
            />
          </div>
        </div>
        <div className="flex gap-2 mt-4">
          <button
            type="submit"
            disabled={createMutation.isPending || updateMutation.isPending}
            className="bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50"
          >
            {createMutation.isPending || updateMutation.isPending
              ? 'Saving...'
              : editingId
              ? 'Update Template'
              : 'Add Template'}
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
      </form>

      {/* Templates list */}
      {isLoading ? (
        <p>Loading templates...</p>
      ) : (
        <div className="space-y-3">
          {templates && templates.length > 0 ? (
            templates.map((template: EmailTemplate) => (
              <div
                key={template.id}
                className="p-4 bg-gray-50 rounded-lg"
              >
                <div className="flex justify-between items-start">
                  <div>
                    <div className="font-medium">{template.name}</div>
                    <div className="text-sm text-gray-600 mt-1">
                      To: {template.recipient_email}
                    </div>
                    <div className="text-sm text-gray-600">
                      Subject: {template.subject}
                    </div>
                    <div className="text-sm text-gray-500 mt-2 whitespace-pre-wrap max-h-20 overflow-hidden">
                      {template.body.slice(0, 200)}{template.body.length > 200 ? '...' : ''}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleEdit(template)}
                      className="text-blue-600 hover:text-blue-800 text-sm"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => deleteMutation.mutate(template.id)}
                      className="text-red-600 hover:text-red-800 text-sm"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            ))
          ) : (
            <p className="text-gray-500 text-center py-4">
              No email templates configured yet. Add one above to get started.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
