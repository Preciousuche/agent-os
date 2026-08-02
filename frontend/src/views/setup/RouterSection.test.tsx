import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'
import { RouterSection } from './RouterSection'
import type { Catalog } from './logic'

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

const STATUS = {
  hasConfig: true,
  llmConfigured: true,
}

const CONFIG = {
  llm: { provider: 'openai', model: 'gpt-4o' },
  agentos_router: { enabled: true, strategy: 'pilot-v1', default_tier: 'c1' },
}

function catalogWithTiers(tiers: Record<string, Record<string, unknown>>): Catalog {
  return {
    routerProfiles: {
      defaultTier: 'c1',
      profiles: [
        {
          // Keep the production gateway profile shape, including fields the
          // editor does not consume.
          profileId: 'openai',
          providerId: 'openai',
          label: 'OpenAI',
          tiers,
        },
      ],
      judge: {
        profiles: {
          openai: { autoModel: 'gpt-4o-mini', models: ['gpt-4o-mini', 'gpt-4o'] },
        },
      },
    },
  }
}

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const MOCK_MODELS = [
  { id: 'gpt-4o', name: 'GPT-4o', provider: 'openai', contextWindow: 128000, capabilities: ['chat', 'tools'] },
  { id: 'gpt-4o-mini', name: 'GPT-4o Mini', provider: 'openai', contextWindow: 128000, capabilities: ['chat', 'tools'] },
  { id: 'gpt-image-1', name: 'GPT Image 1', provider: 'openai', contextWindow: 128000, capabilities: ['chat', 'vision'] },
  { id: 'claude-3-opus', name: 'Claude 3 Opus', provider: 'anthropic', contextWindow: 200000, capabilities: ['chat'] },
]

const mockRpc = {
  waitForConnection: vi.fn().mockResolvedValue(undefined),
  call: vi.fn((method) => {
    if (method === 'models.list') {
      return Promise.resolve(MOCK_MODELS)
    }
    return Promise.resolve({})
  }),
}

vi.mock('@/app/providers', () => ({
  useRpc: () => mockRpc,
}))

function renderSection(catalog: Catalog, onSave = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })
  const props = {
    catalog,
    status: STATUS,
    config: CONFIG,
    onSave,
    onBack: vi.fn(),
    onNext: vi.fn(),
    saving: false,
  }
  const result = render(
    <QueryClientProvider client={queryClient}>
      <RouterSection {...props} />
    </QueryClientProvider>,
  )
  return {
    ...result,
    rerenderCatalog: (nextCatalog: Catalog) =>
      result.rerender(
        <QueryClientProvider client={queryClient}>
          <RouterSection {...props} catalog={nextCatalog} />
        </QueryClientProvider>,
      ),
  }
}

describe('RouterSection', () => {
  it('seeds tiers that appear in a later partial-catalog update without crashing', () => {
    const partialCatalog = catalogWithTiers({
      c0: { provider: 'openai', model: 'gpt-4o-mini' },
    })
    const view = renderSection(partialCatalog)

    expect(screen.getByLabelText('c0 model')).toHaveValue('gpt-4o-mini')
    expect(screen.queryByLabelText('c1 provider')).not.toBeInTheDocument()

    view.rerenderCatalog(
      catalogWithTiers({
        c0: { provider: 'openai', model: 'gpt-4o-mini' },
        c1: { provider: 'openai', model: 'gpt-4o' },
        image_model: { provider: 'openai', model: 'gpt-image-1' },
      }),
    )

    expect(screen.getByLabelText('c1 provider')).toHaveValue('openai')
    expect(screen.getByLabelText('c1 model')).toHaveValue('gpt-4o')
    expect(screen.getByLabelText('image_model model')).toHaveValue('gpt-image-1')
  })

  it('uses newly visible tier defaults when saving and keeps existing edits', () => {
    const onSave = vi.fn()
    const view = renderSection(
      catalogWithTiers({
        c0: { provider: 'openai', model: 'gpt-4o-mini' },
      }),
      onSave,
    )
    fireEvent.change(screen.getByLabelText('c0 model'), { target: { value: 'edited-c0' } })

    view.rerenderCatalog(
      catalogWithTiers({
        c0: { provider: 'openai', model: 'gpt-4o-mini' },
        c1: { provider: 'openai', model: 'gpt-4o' },
      }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Save Router' }))

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        tiers: expect.objectContaining({
          c0: expect.objectContaining({ model: 'edited-c0' }),
          c1: expect.objectContaining({ provider: 'openai', model: 'gpt-4o' }),
        }),
      }),
    )
  })

  it('renders unified selects and accessible image capability controls', () => {
    renderSection(
      catalogWithTiers({
        c0: { provider: 'openai', model: 'gpt-4o-mini' },
        image_model: { provider: 'openai', model: 'gpt-image-1' },
      }),
    )

    expect(screen.getByLabelText('Router mode').parentElement).toHaveClass('setup-select')
    expect(screen.getAllByRole('columnheader')).toHaveLength(5)

    const capability = screen.getByLabelText('c0 supports image')
    expect(capability).not.toBeChecked()
    expect(capability).toHaveClass('setup-check__input')
    fireEvent.click(capability)
    expect(capability).toBeChecked()

    expect(screen.getByLabelText('image_model supports image')).toBeChecked()
    expect(screen.getByLabelText('image_model supports image')).toBeDisabled()
  })

  it('updates datalist options when provider changes and filters image_model for vision capability', async () => {
    const catalog = catalogWithTiers({
      c0: { provider: 'openai', model: 'gpt-4o-mini' },
      image_model: { provider: 'openai', model: 'gpt-image-1' },
    })
    catalog.providers = [
      { providerId: 'openai', label: 'OpenAI', runtimeSupported: true },
      { providerId: 'anthropic', label: 'Anthropic', runtimeSupported: true },
    ]

    renderSection(catalog)

    const c0ProviderSelect = screen.getByLabelText('c0 provider')
    expect(c0ProviderSelect).toHaveValue('openai')

    // Wait for the datalist options to be loaded from the RPC call
    await waitFor(() => {
      const c0Datalist = document.getElementById('datalist-c0') as HTMLDataListElement
      expect(c0Datalist).toBeInTheDocument()
      const c0Options = Array.from(c0Datalist.options).map((opt) => opt.value)
      expect(c0Options).toContain('gpt-4o')
    })

    const c0Datalist = document.getElementById('datalist-c0') as HTMLDataListElement
    let c0Options = Array.from(c0Datalist.options).map((opt) => opt.value)
    expect(c0Options).toContain('gpt-4o-mini')
    expect(c0Options).toContain('gpt-image-1')
    expect(c0Options).not.toContain('claude-3-opus')

    fireEvent.change(c0ProviderSelect, { target: { value: 'anthropic' } })
    expect(c0ProviderSelect).toHaveValue('anthropic')

    // Wait for options to update for the new provider
    await waitFor(() => {
      const c0Options = Array.from(c0Datalist.options).map((opt) => opt.value)
      expect(c0Options).toContain('claude-3-opus')
    })

    c0Options = Array.from(c0Datalist.options).map((opt) => opt.value)
    expect(c0Options).not.toContain('gpt-4o')

    const imageDatalist = document.getElementById('datalist-image_model') as HTMLDataListElement
    expect(imageDatalist).toBeInTheDocument()
    const imageOptions = Array.from(imageDatalist.options).map((opt) => opt.value)
    expect(imageOptions).toContain('gpt-image-1')
    expect(imageOptions).not.toContain('gpt-4o')
    expect(imageOptions).not.toContain('gpt-4o-mini')
  })

  it('warns on unknown model ID on save', async () => {
    const onSave = vi.fn()
    const catalog = catalogWithTiers({
      c0: { provider: 'openai', model: 'unknown-model-id-123' },
    })
    catalog.providers = [
      { providerId: 'openai', label: 'OpenAI', runtimeSupported: true },
    ]

    renderSection(catalog, onSave)

    // Wait for the query to populate allModels so that validation runs on a loaded list
    await waitFor(() => {
      const c0Datalist = document.getElementById('datalist-c0') as HTMLDataListElement
      expect(c0Datalist).toBeInTheDocument()
      expect(c0Datalist.options.length).toBeGreaterThan(0)
    })

    fireEvent.click(screen.getByRole('button', { name: 'Save Router' }))

    expect(toast.warning).toHaveBeenCalledWith(
      expect.stringContaining('Warning: Model ID not in catalog: unknown-model-id-123'),
      expect.any(Object),
    )
    expect(onSave).toHaveBeenCalled()
  })
})
