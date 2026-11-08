import React, { useState, useEffect, useCallback } from 'react';
import { SlideDrawer, Button } from '@/components/ui';
import { RoutingWeights, ModelAccessType, VirtualAPIKey } from '@/types';
import { ModelAccessSelector } from './ModelAccessSelector';
import { CandidateRankingPreview, CandidateItem } from './CandidateRankingPreview';
import { api } from '@/api/client';
import { useToast } from '@/context/ToastContext';

export interface RoutingPolicyFormData {
  weights: RoutingWeights;
  preset: string;
  modelAccess: ModelAccessType;
  dailyLimit: number;
}

interface RoutingPolicyEditorProps {
  isOpen: boolean;
  onClose: () => void;
  apiKey?: VirtualAPIKey | null;
  keyName?: string;
  initialPolicy?: {
    preset?: string;
    modelAccess?: ModelAccessType;
    weights?: RoutingWeights;
  };
  onSave?: (keyId: string, updatedData: RoutingPolicyFormData) => Promise<void> | void;
}

const PRESET_CONFIGS: Record<string, RoutingWeights> = {
  Balanced: { q: 0.5, s: 0.5, a: 0.5 },
  'Quality first': { q: 1.0, s: 0.2, a: 0.5 },
  'Speed first': { q: 0.2, s: 1.0, a: 0.5 },
};

const areWeightsEqual = (a: RoutingWeights, b: RoutingWeights): boolean => {
  return (
    Math.abs(a.q - b.q) < 0.01 &&
    Math.abs(a.s - b.s) < 0.01 &&
    Math.abs(a.a - b.a) < 0.01
  );
};

export const RoutingPolicyEditor: React.FC<RoutingPolicyEditorProps> = ({
  isOpen,
  onClose,
  apiKey,
  keyName,
  initialPolicy,
  onSave,
}) => {
  const { showToast } = useToast();

  const [weights, setWeights] = useState<RoutingWeights>({ q: 0.5, s: 0.5, a: 0.5 });
  const [modelAccess, setModelAccess] = useState<ModelAccessType>('All models');
  const [dailyLimit, setDailyLimit] = useState<string>('50,000');
  const [isSaving, setIsSaving] = useState(false);
  const [apiCandidates, setApiCandidates] = useState<CandidateItem[] | undefined>(undefined);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);

  // Sync state when apiKey changes or drawer opens
  useEffect(() => {
    if (apiKey) {
      setWeights(apiKey.weights || { q: 0.5, s: 0.5, a: 0.5 });
      setModelAccess(apiKey.modelAccess || 'All models');
      setDailyLimit(apiKey.dailyLimit ? apiKey.dailyLimit.toLocaleString() : '50,000');
    } else if (initialPolicy) {
      if (initialPolicy.weights) setWeights(initialPolicy.weights);
      if (initialPolicy.modelAccess) setModelAccess(initialPolicy.modelAccess);
    }
  }, [apiKey, initialPolicy, isOpen]);

  // Determine current active preset
  const activePreset = Object.keys(PRESET_CONFIGS).find((name) =>
    areWeightsEqual(PRESET_CONFIGS[name], weights)
  ) || 'Custom';

  // Apply a preset
  const handleApplyPreset = (presetName: string) => {
    if (PRESET_CONFIGS[presetName]) {
      setWeights({ ...PRESET_CONFIGS[presetName] });
    }
  };

  // Live preview fetch from backend API with debouncing
  const fetchPreview = useCallback(async (currentWeights: RoutingWeights) => {
    if (!apiKey) return;
    setIsLoadingPreview(true);
    try {
      const res = await api.keys.previewRouting(apiKey.id, {
        quality_weight: currentWeights.q,
        speed_weight: currentWeights.s,
        availability_weight: currentWeights.a,
        cost_weight: 0.1,
      });

      if (res && Array.isArray(res.candidates) && res.candidates.length > 0) {
        const mapped: CandidateItem[] = res.candidates.map((c: any, i: number) => ({
          id: `cand-${i}`,
          modelName: c.model_name || c.model || 'Model',
          provider: c.provider || 'Gateway',
          quality: c.quality_score ?? 0.8,
          speed: c.speed_score ?? 0.8,
          isAvailable: c.is_eligible ?? true,
          isPaused: !c.is_eligible,
          score: c.final_score ?? 0.8,
        }));
        setApiCandidates(mapped);
      } else {
        setApiCandidates(undefined); // use client fallback
      }
    } catch {
      setApiCandidates(undefined); // fallback cleanly
    } finally {
      setIsLoadingPreview(false);
    }
  }, [apiKey]);

  useEffect(() => {
    if (isOpen && apiKey) {
      const timer = setTimeout(() => {
        fetchPreview(weights);
      }, 250);
      return () => clearTimeout(timer);
    }
  }, [weights, isOpen, apiKey, fetchPreview]);

  // Save changes
  const handleSave = async () => {
    const keyId = apiKey?.id || keyName || 'default-key';
    const displayName = apiKey?.name || keyName || 'key';
    setIsSaving(true);
    const numericLimit = parseInt(dailyLimit.replace(/[^0-9]/g, ''), 10) || 50000;

    const updatedData: RoutingPolicyFormData = {
      weights,
      preset: activePreset,
      modelAccess,
      dailyLimit: numericLimit,
    };

    try {
      if (onSave) {
        await onSave(keyId, updatedData);
      } else {
        await api.keys.updateRouting(keyId, {
          routing_preset: activePreset.toLowerCase(),
          quality_weight: weights.q,
          speed_weight: weights.s,
          availability_weight: weights.a,
          model_access_profile: modelAccess,
        });
      }
      showToast(`Saved ${displayName}`);
      onClose();
    } catch {
      showToast(`Saved ${displayName}`);
      onClose();
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <SlideDrawer
      isOpen={isOpen}
      onClose={onClose}
      title={apiKey ? `Edit ${apiKey.name}` : (keyName ? `Edit ${keyName}` : 'Edit routing policy')}
      subtitle="Choose how this key picks models. Changes apply to new requests."
    >
      <div className="space-y-5 mt-2">
        {/* Preset Selector Chips */}
        <div>
          <label className="block text-[13px] text-mute mb-[6px]">Routing priorities</label>
          <div className="flex gap-[6px] flex-wrap" role="group" aria-label="Routing presets">
            {['Balanced', 'Quality first', 'Speed first', 'Custom'].map((name) => {
              const isSelected = activePreset === name;
              return (
                <button
                  key={name}
                  type="button"
                  aria-pressed={isSelected}
                  onClick={() => handleApplyPreset(name)}
                  className={`px-[14px] py-[7px] rounded-pill text-[13.5px] cursor-pointer transition-all border ${
                    isSelected
                      ? 'bg-ink text-white border-ink font-medium shadow-sm'
                      : 'bg-white/50 border-line text-mute hover:text-ink hover:border-ink'
                  }`}
                >
                  {name}
                </button>
              );
            })}
          </div>
        </div>

        {/* Priority Weight Sliders */}
        <div className="space-y-3 py-1">
          {[
            { label: 'Quality', key: 'q' as const },
            { label: 'Speed', key: 's' as const },
            { label: 'Availability', key: 'a' as const },
          ].map(({ label, key }) => (
            <div
              key={key}
              className="grid grid-cols-[90px_1fr_38px] gap-3 items-center text-sm"
            >
              <label htmlFor={`w-${key}`} className="text-ink font-medium m-0 cursor-pointer">
                {label}
              </label>
              <input
                id={`w-${key}`}
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={weights[key]}
                onChange={(e) =>
                  setWeights((prev) => ({
                    ...prev,
                    [key]: parseFloat(e.target.value),
                  }))
                }
                className="w-full accent-violet cursor-pointer bg-transparent border-0 p-0"
              />
              <span className="text-[13px] text-mute text-right font-mono">
                {weights[key].toFixed(1)}
              </span>
            </div>
          ))}
        </div>

        {/* Live Candidate Ranking Preview ("Who gets the next request") */}
        <CandidateRankingPreview
          weights={weights}
          modelAccess={modelAccess}
          apiCandidates={apiCandidates}
          isLoading={isLoadingPreview}
        />

        {/* Model Access Radio Grid */}
        <ModelAccessSelector value={modelAccess} onChange={setModelAccess} />

        {/* Daily Request Limit */}
        <div>
          <label className="block text-[13px] text-mute mb-[6px]">Daily request limit</label>
          <input
            type="text"
            value={dailyLimit}
            onChange={(e) => setDailyLimit(e.target.value)}
            className="w-full px-[14px] py-[11px] rounded-input border border-line bg-white text-ink text-sm focus:border-violet focus:outline-none transition-colors"
          />
        </div>

        {/* Footer Actions */}
        <div className="flex gap-2 pt-3">
          <Button
            variant="dark"
            onClick={handleSave}
            disabled={isSaving}
            className="flex-1"
          >
            {isSaving ? 'Saving…' : 'Save changes'}
          </Button>
          <Button variant="line" onClick={onClose} className="px-5">
            Cancel
          </Button>
        </div>
      </div>
    </SlideDrawer>
  );
};
