import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { settingsAPI, stockAPI, type AIModelSetting, type APICredential, type Warehouse } from '../services/api'

export default function Settings() {
  const [activeTab, setActiveTab] = useState<'credentials' | 'ai-models' | 'ebay' | 'warehouses'>('credentials')

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
            onClick={() => setActiveTab('warehouses')}
            className={`${
              activeTab === 'warehouses'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            Warehouses
          </button>
        </nav>
      </div>

      {/* Tab content */}
      {activeTab === 'credentials' && <CredentialsTab />}
      {activeTab === 'ai-models' && <AIModelsTab />}
      {activeTab === 'ebay' && <EbayTab />}
      {activeTab === 'warehouses' && <WarehousesTab />}
    </div>
  )
}

function CredentialsTab() {
  const queryClient = useQueryClient()
  const [serviceName, setServiceName] = useState('')
  const [keyName, setKeyName] = useState('')
  const [keyValue, setKeyValue] = useState('')

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
      setKeyName('')
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
        Securely store API keys for AI providers. eBay credentials are configured in the .env file. All values are encrypted.
      </p>

      {/* Add credential form */}
      <form onSubmit={handleSubmit} className="mb-8 bg-gray-50 p-4 rounded-lg">
        <h3 className="font-medium mb-4">Add New Credential</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Service
            </label>
            <select
              value={serviceName}
              onChange={(e) => setServiceName(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2"
              required
            >
              <option value="">Select service...</option>
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Key Name
            </label>
            <input
              type="text"
              value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
              placeholder="e.g., api_key, app_id"
              className="w-full border border-gray-300 rounded-md px-3 py-2"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Value
            </label>
            <input
              type="password"
              value={keyValue}
              onChange={(e) => setKeyValue(e.target.value)}
              placeholder="API key value"
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
          {createMutation.isPending ? 'Adding...' : 'Add Credential'}
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
      'claude-3-5-sonnet-20241022',
      'claude-3-opus-20240229',
      'claude-3-haiku-20240307',
    ],
    openai: ['gpt-4-turbo-preview', 'gpt-4', 'gpt-3.5-turbo'],
  }

  return (
    <div className="bg-white shadow rounded-lg p-6">
      <h2 className="text-xl font-semibold mb-4">AI Model Configuration</h2>
      <p className="text-gray-600 mb-6">
        Configure which AI model to use for message drafting and translation.
      </p>

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
            Common causes: code expired (complete the flow quickly after ngrok &quot;Visit Site&quot;); redirect_uri must match exactly (RuName in .env and Auth Accepted URL in eBay portal).
          </p>
        </div>
      )}

      <div className="mb-8">
        <h3 className="font-medium mb-2">Status</h3>
        {statusLoading ? (
          <p className="text-gray-500">Checking...</p>
        ) : status?.connected ? (
          <p className="text-green-700 font-medium">Connected</p>
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
          {importMutation.data?.data && (
            <div className="mt-3 p-3 bg-gray-50 rounded-lg text-sm">
              <p>Orders added: {importMutation.data.data.orders_added}</p>
              <p>Orders updated: {importMutation.data.data.orders_updated}</p>
              <p>Line items added: {importMutation.data.data.line_items_added}</p>
              <p>Line items updated: {importMutation.data.data.line_items_updated}</p>
              {importMutation.data.data.error && (
                <p className="text-red-600">Error: {importMutation.data.data.error}</p>
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
