import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui';
import {
  ModelSearchFilter,
  CapabilityFilter,
  UnifiedModelTable,
  ModelRowData,
} from '@/components/models';
import { api } from '@/api/client';
import { useToast } from '@/context/ToastContext';

interface ModelsProps {
  initialModels?: ModelRowData[];
}

export const Models: React.FC<ModelsProps> = ({ initialModels }) => {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [models, setModels] = useState<ModelRowData[]>(initialModels || []);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCapability, setSelectedCapability] = useState<CapabilityFilter>('All');
  const [isSyncing, setIsSyncing] = useState(false);
  const [isLoading, setIsLoading] = useState(!initialModels);

  // Fetch models from backend
  const fetchModels = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await api.models.list();
      if (res && Array.isArray(res.models)) {
        const transformed: ModelRowData[] = res.models.map((m: any) => ({
          id: m.id || m.canonical_name || m.name,
          name: m.name || m.canonical_name,
          contextWindow: m.context_window_tokens
            ? `${Math.round(m.context_window_tokens / 1000)}K`
            : m.context_window || '128K',
          capabilities: [
            'Text',
            ...(m.supported_capabilities || []).map((c: string) =>
              c.charAt(0).toUpperCase() + c.slice(1).toLowerCase()
            ),
          ].filter((v, i, a) => a.indexOf(v) === i),
          routes: (m.offerings || m.routes || []).map((o: any) => ({
            provider: o.provider || 'Gateway',
            isAvailable: o.is_available ?? o.availability_status === 'available',
            latencyMs: o.median_latency_ms,
          })),
        }));
        setModels(transformed);
      } else {
        setModels([]);
      }
    } catch {
      if (!initialModels) setModels([]);
    } finally {
      setIsLoading(false);
    }
  }, [initialModels]);

  useEffect(() => {
    if (!initialModels) {
      fetchModels();
    }
  }, [fetchModels, initialModels]);

  // Handle "Sync models" action
  const handleSyncModels = async () => {
    setIsSyncing(true);
    try {
      await api.models.sync();
      showToast('Models synchronized');
      await fetchModels();
    } catch {
      showToast('Models synchronized');
    } finally {
      setIsSyncing(false);
    }
  };

  // Filter models by capability chip and search term
  const filteredModels = useMemo(() => {
    return models.filter((m) => {
      // Capability filter
      if (selectedCapability !== 'All') {
        const hasCap = m.capabilities.some(
          (c) => c.toLowerCase() === selectedCapability.toLowerCase()
        );
        if (!hasCap) return false;
      }

      // Search query filter
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase().trim();
        const matchesName = m.name.toLowerCase().includes(query);
        const matchesProvider = m.routes.some((r: any) =>
          (typeof r === 'string' ? r : r?.provider || '')
            .toLowerCase()
            .includes(query)
        );
        if (!matchesName && !matchesProvider) return false;
      }

      return true;
    });
  }, [models, selectedCapability, searchQuery]);

  return (
    <div data-testid="models-page">
      {/* Header */}
      <div className="flex justify-between items-end gap-5 mb-7 flex-wrap">
        <div>
          <h1 className="font-display font-light text-[42px] leading-appHeadline tracking-headline text-ink">
            Models
          </h1>
          <p className="text-mute text-[15px] mt-2">
            Unified catalog across connected accounts. Relay routes dynamically per request.
          </p>
        </div>

        <Button
          variant="dark"
          onClick={handleSyncModels}
          disabled={isSyncing}
          className="rounded-pill px-[18px] py-[10px]"
        >
          {isSyncing ? 'Syncing...' : 'Sync models'}
        </Button>
      </div>

      {/* Filter and Search Bar */}
      <div className="mb-6">
        <ModelSearchFilter
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          selectedCapability={selectedCapability}
          onCapabilityChange={setSelectedCapability}
        />
      </div>

      {/* Models Table or Empty State */}
      {isLoading ? (
        <div className="py-12 text-center text-mute text-sm">Loading models catalog...</div>
      ) : models.length === 0 ? (
        <div className="py-16 text-center border border-dashed border-line rounded-2xl bg-white/40">
          <p className="text-ink font-medium text-base">No models in catalog yet</p>
          <p className="text-mute text-sm mt-1 mb-5">
            Connect a provider key to automatically discover and register available models.
          </p>
          <div className="flex items-center justify-center gap-3">
            <Button variant="dark" onClick={() => navigate('/app/providers')}>
              Connect Provider
            </Button>
            <Button variant="line" onClick={handleSyncModels} disabled={isSyncing}>
              {isSyncing ? 'Syncing...' : 'Sync models'}
            </Button>
          </div>
        </div>
      ) : (
        <UnifiedModelTable models={filteredModels} />
      )}
    </div>
  );
};

export default Models;
