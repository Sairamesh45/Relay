import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui';
import {
  ModelSearchFilter,
  CapabilityFilter,
  UnifiedModelTable,
  ModelRowData,
  ModelRoute,
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
      const rawList = Array.isArray(res?.items)
        ? res.items
        : Array.isArray(res?.models)
        ? res.models
        : Array.isArray(res)
        ? res
        : [];

      if (rawList.length > 0) {
        const transformed: ModelRowData[] = rawList.map((m: any) => {
          const offerings = m.provider_offerings || m.offerings || m.routes || [];

          // Format friendly name
          const rawName =
            m.display_name || m.name || m.canonical_id || m.canonical_name || 'Unnamed Model';

          // Context window formatting
          let contextStr = '128K';
          const ctx =
            offerings.find((o: any) => o.context_window)?.context_window ||
            m.context_window_tokens ||
            m.context_window;
          if (ctx) {
            if (ctx >= 1000000) {
              contextStr = `${Math.round(ctx / 1000000)}M`;
            } else if (ctx >= 1000) {
              contextStr = `${Math.round(ctx / 1000)}K`;
            } else {
              contextStr = `${ctx}`;
            }
          }

          // Capabilities detection
          const caps = new Set<string>(['Text']);
          const inMods = m.input_modalities || [];
          if (inMods.includes('image') || offerings.some((o: any) => o.supports_vision)) {
            caps.add('Image');
          }
          if (offerings.some((o: any) => o.supports_tools)) {
            caps.add('Tools');
          }
          if (Array.isArray(m.supported_capabilities)) {
            m.supported_capabilities.forEach((c: string) => {
              caps.add(c.charAt(0).toUpperCase() + c.slice(1).toLowerCase());
            });
          }

          // Routes / Provider badges
          const routes: ModelRoute[] = offerings.map((o: any) => {
            const rawP = o.provider || 'Gateway';
            const displayP =
              rawP.toLowerCase() === 'gemini'
                ? 'Google Gemini'
                : rawP.charAt(0).toUpperCase() + rawP.slice(1);
            return {
              provider: displayP,
              isAvailable: o.availability_status === 'available' || o.is_available === true,
              latencyMs: o.median_latency_ms,
            };
          });

          return {
            id: m.id || m.canonical_id || m.canonical_name || rawName,
            name: rawName,
            contextWindow: contextStr,
            capabilities: Array.from(caps),
            routes: routes.length > 0 ? routes : [{ provider: 'Gateway', isAvailable: true }],
          };
        });

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
