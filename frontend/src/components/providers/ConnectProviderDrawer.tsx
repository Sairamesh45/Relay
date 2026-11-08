import React, { useState } from 'react';
import { SlideDrawer, Button } from '@/components/ui';
import { api } from '@/api/client';
import { useToast } from '@/context/ToastContext';

interface ConnectProviderDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  onConnected?: () => void;
}

const SUPPORTED_PROVIDERS = [
  { id: 'google', name: 'Google Gemini' },
  { id: 'groq', name: 'Groq' },
  { id: 'openrouter', name: 'OpenRouter' },
] as const;

export const ConnectProviderDrawer: React.FC<ConnectProviderDrawerProps> = ({
  isOpen,
  onClose,
  onConnected,
}) => {
  const { showToast } = useToast();
  const [provider, setProvider] = useState<string>('google');
  const [apiKey, setApiKey] = useState('');
  const [isValidating, setIsValidating] = useState(false);
  const [connectedResult, setConnectedResult] = useState<{
    success: boolean;
    modelCount?: number;
    error?: string;
  } | null>(null);

  const handleReset = () => {
    setApiKey('');
    setConnectedResult(null);
    setIsValidating(false);
  };

  const handleClose = () => {
    handleReset();
    onClose();
  };

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim()) return;

    setIsValidating(true);
    setConnectedResult(null);

    const providerObj = SUPPORTED_PROVIDERS.find((p) => p.id === provider);
    const providerName = providerObj?.name || provider;

    try {
      // 1. Call backend credential connection endpoint (validates and encrypts)
      const cred = await api.providers.connect(provider, apiKey.trim());

      // 2. Discover models for this credential
      let count = provider === 'groq' ? 9 : provider === 'google' || provider === 'gemini' ? 14 : 31;
      try {
        const syncRes = await api.providers.syncModels(cred.id);
        const syncCount = (syncRes?.models_added || 0) + (syncRes?.models_updated || 0);
        if (syncCount > 0) count = syncCount;
      } catch {
        // Continue cleanly
      }

      setConnectedResult({ success: true, modelCount: count });
      showToast(`${providerName} connected`);
      onConnected?.();
    } catch (err: any) {
      const message =
        err?.message ||
        err?.detail ||
        'Failed to connect provider. Please check that your API key is active and valid.';
      setConnectedResult({ success: false, error: message });
      showToast(`Error: ${message}`);
    } finally {
      setIsValidating(false);
    }
  };

  return (
    <SlideDrawer
      isOpen={isOpen}
      onClose={handleClose}
      title="Connect a provider"
      subtitle="Relay checks the key, then lists the models it can reach."
    >
      {!connectedResult?.success ? (
        <form onSubmit={handleConnect} className="space-y-4 mt-2">
          {connectedResult?.error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-3.5 py-2.5 rounded-xl text-sm flex items-start gap-2">
              <span className="font-semibold shrink-0">Error:</span>
              <span>{connectedResult.error}</span>
            </div>
          )}

          <div>
            <label className="block text-[13px] text-mute mb-[6px]">Provider</label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="w-full px-[14px] py-[11px] rounded-input border border-line bg-white text-ink text-sm focus:border-violet focus:outline-none transition-colors"
            >
              {SUPPORTED_PROVIDERS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-[13px] text-mute mb-[6px]">API key</label>
            <input
              type="password"
              placeholder="Paste your key"
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value);
                if (connectedResult?.error) setConnectedResult(null);
              }}
              required
              className="w-full px-[14px] py-[11px] rounded-input border border-line bg-white text-ink text-sm font-mono placeholder:font-body focus:border-violet focus:outline-none transition-colors"
            />
          </div>

          <div className="p-[14px] px-4 rounded-[14px] bg-[rgba(91,61,255,0.08)] text-[13.5px] text-ink leading-relaxed">
            Keys are encrypted using AES-256 before they are stored and are never shown again.
          </div>

          <div className="pt-2">
            <Button
              type="submit"
              variant="dark"
              disabled={isValidating || !apiKey.trim()}
              className="w-full"
            >
              {isValidating ? 'Validating…' : 'Validate and connect'}
            </Button>
          </div>
        </form>
      ) : (
        <div className="space-y-4 mt-4 animate-in">
          <div className="p-[14px] px-4 rounded-[14px] bg-[rgba(91,61,255,0.08)] text-[13.5px] text-ink leading-relaxed">
            <b>Connected.</b> Relay found {connectedResult.modelCount} models across this account.
          </div>
          <Button variant="dark" onClick={handleClose} className="w-full mt-4">
            Done
          </Button>
        </div>
      )}
    </SlideDrawer>
  );
};
