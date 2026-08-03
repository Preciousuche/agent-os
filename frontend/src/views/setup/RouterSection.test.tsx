import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
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
          profileId: 'openai',
          providerId: 'openai',
          label: 'OpenAI',
          tiers,
        },
        {
          profileId: 'anthropic',
          providerId: 'anthropic',
          label: 'Anthropic',
          tiers,
        },
      ],
      judge: {
        profiles: {
          openai: { autoModel: 'gpt-4o-mini', models: ['gpt-4o-mini', 'gpt-4o'] },
          anthropic: { autoModel: 'claude-3-opus', models: ['claude-3-opus'] },
        },
      },
    },
  }
}

const MOCK_MODELS = [
  {
    id: 'gpt-4o',
    name: 'GPT-4o',
    provider: 'openai',
    contextWindow: 128000,
    capabilities: ['chat', 'tools'],
  },
  {
    id: 'gpt-4o-mini',
    name: 'GPT-4o Mini',
    provider: 'openai',
    contextWindow: 128000,
    capabilities: ['chat', 'tools'],
  },
  {
    id: 'gpt-image-1',
    name: 'GPT Image 1',
    provider: 'openai',
    contextWindow: 128000,
    capabilities: ['chat', 'vision'],
  },
  {
    id: 'claude-3-opus',
    name: 'Claude 3 Opus',
    provider: 'anthropic',
    contextWindow: 200000,
    capabilities: ['chat'],
  },
  {
    id: 'claude-image-1',
    name: 'Claude Image 1',
    provider: 'anthropic',
    contextWindow: 200000,
    capabilities: ['chat', 'vision'],
  },
]

let mockModelsResponse: unknown = MOCK_MODELS

const mockRpc = {
  waitForConnection: vi.fn().mockResolvedValue(undefined),
  call: vi.fn((method) => {
    if (method === 'models.list') {
      return Promise.resolve(mockModelsResponse)
    }
    return Promise.resolve({})
  }),
}

vi.mock('@/app/providers', () => ({
  useRpc: () => mockRpc,
}))

function renderSection(catalog: Catalog, onSave = vi.fn(), config = CONFIG, draftProvider = '') {
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
    config,
    draftProvider,
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
    rerenderWithConfig: (nextConfig: typeof CONFIG) =>
      result.rerender(
        <QueryClientProvider client={queryClient}>
          <RouterSection {...props} config={nextConfig} />
        </QueryClientProvider>,
      ),
  }
}

describe('RouterSection', () => {
  afterEach(() => {
    mockModelsResponse = MOCK_MODELS
  })

  it('seeds tiers that appear in a later partial-catalog update without crashing', () => {
    const partialCatalog = catalogWithTiers({
      c0: { provider: 'openai', model: 'gpt-4o-mini' },
    })
    const view = renderSection(partialCatalog)

    expect(screen.getByLabelText('c0 model')).toHaveValue('gpt-4o-mini')
    expect(screen.queryByLabelText('c1 model')).not.toBeInTheDocument()

    view.rerenderCatalog(
      catalogWithTiers({
        c0: { provider: 'openai', model: 'gpt-4o-mini' },
        c1: { provider: 'openai', model: 'gpt-4o' },
        image_model: { provider: 'openai', model: 'gpt-image-1' },
      }),
    )

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

    const config = {
      llm: { provider: 'openai', model: 'gpt-4o' },
      agentos_router: { enabled: true, strategy: 'pilot-v1', default_tier: 'c1' },
    }

    const { rerenderWithConfig } = renderSection(catalog, vi.fn(), config)

    // Wait for the datalist options to be loaded from the RPC call
    await waitFor(() => {
      const c0Datalist = document.getElementById('datalist-c0') as HTMLDataListElement
      expect(c0Datalist).toBeInTheDocument()
      const c0Options = Array.from(c0Datalist.options).map((opt) => opt.value)
      expect(c0Options).toContain('gpt-image-1')
    })

    const c0Datalist = document.getElementById('datalist-c0') as HTMLDataListElement
    const c0Options = Array.from(c0Datalist.options).map((opt) => opt.value)
    expect(c0Options).toContain('gpt-4o')
    expect(c0Options).toContain('gpt-4o-mini')
    expect(c0Options).not.toContain('claude-3-opus')

    // Verify image model capability filtering for OpenAI initially
    const imageDatalist = document.getElementById('datalist-image_model') as HTMLDataListElement
    expect(imageDatalist).toBeInTheDocument()
    const imageOptions = Array.from(imageDatalist.options).map((opt) => opt.value)
    expect(imageOptions).toContain('gpt-image-1')
    expect(imageOptions).not.toContain('gpt-4o')
    expect(imageOptions).not.toContain('gpt-4o-mini')

    // Change configuration provider
    const nextConfig = {
      ...config,
      llm: { provider: 'anthropic', model: 'claude-3-opus' },
    }
    rerenderWithConfig(nextConfig)

    // Wait for options to update for the new provider, including the image model capability filter
    await waitFor(() => {
      const c0Options = Array.from(c0Datalist.options).map((opt) => opt.value)
      expect(c0Options).toContain('claude-3-opus')

      const imgDatalist = document.getElementById('datalist-image_model') as HTMLDataListElement
      const imgOptions = Array.from(imgDatalist.options).map((opt) => opt.value)
      expect(imgOptions).toContain('claude-image-1')
      expect(imgOptions).not.toContain('claude-3-opus')
    })
  })

  it('warns on unknown model ID on save', async () => {
    const onSave = vi.fn()
    const catalog = catalogWithTiers({
      c0: { provider: 'openai', model: 'unknown-model-id-123' },
    })
    catalog.providers = [{ providerId: 'openai', label: 'OpenAI', runtimeSupported: true }]

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

  it('falls back to offline catalog judge profiles models when models.list returns empty', async () => {
    // Override RPC mock to return empty array
    mockModelsResponse = []

    const catalog = catalogWithTiers({
      c0: { provider: 'openai', model: 'gpt-4o' },
    })
    catalog.routerProfiles!.judge = {
      profiles: {
        openai: { autoModel: 'gpt-4o-mini', models: ['gpt-4o-mini', 'gpt-4o-offline'] },
      },
    }

    renderSection(catalog)

    await waitFor(() => {
      const c0Datalist = document.getElementById('datalist-c0') as HTMLDataListElement
      expect(c0Datalist).toBeInTheDocument()
      const c0Options = Array.from(c0Datalist.options).map((opt) => opt.value)
      expect(c0Options).toContain('gpt-4o-offline')
    })
  })

  it('shows warning when both models.list and offline catalog are empty (cannot validate model)', async () => {
    // Override RPC mock to return empty array
    mockModelsResponse = []

    const onSave = vi.fn()
    const catalog = catalogWithTiers({
      c0: { provider: 'openai', model: 'any-model' },
    })
    catalog.routerProfiles!.judge = {
      profiles: {
        openai: { autoModel: null, models: [] },
      },
    }

    renderSection(catalog, onSave)

    fireEvent.click(screen.getByRole('button', { name: 'Save Router' }))

    await waitFor(() => {
      expect(toast.warning).toHaveBeenCalledWith(
        expect.stringContaining('Warning: Could not validate model ID'),
        expect.any(Object),
      )
    })
    expect(onSave).toHaveBeenCalled()
  })
})
