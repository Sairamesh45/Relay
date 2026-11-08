import React, { useState, useEffect, useCallback } from 'react';
import { SlideDrawer, Button, Pill } from '@/components/ui';
import { ProviderData } from './ProviderCard';
import { api } from '@/api/client';
import { useToast } from '@/context/ToastContext';

interface CredentialItem {
  id: string;
  provider: string;
  display_name?: string;
  masked_key: string;
  status: string;
  last_validated_at?: string;
  created_at: string;
}

interface ManageKeysDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  provider: ProviderData | null;
  onKeysChanged?: () => void;
  onAddKey?: () => void;
}

export const ManageKeysDrawer: React.FC<ManageKeysDrawerProps> = ({
  isOpen,
  onClose,
  provider,
  onKeysChanged,
  onAddKey,
}) => {
  const { showToast } = useToast();
  const [credentials, setCredentials] = useState<CredentialItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const loadCredentials = useCallback(async () => {
    if (!provider) return;
    setIsLoading(true);
    try {
      const allCreds = await api.providers.credentials();
      const pKey = provider.providerKey.toLowerCase();
      const filtered = (Array.isArray(allCreds) ? allCreds : []).filter((c: any) => {
        const cp = (c.provider || '').toLowerCase();
        return (
          cp === pKey ||
          (pKey === 'gemini' && cp === 'google') ||
          (pKey === 'google' && cp === 'gemini')
        );
      });
      setCredentials(filtered);
    } catch {
      setCredentials([]);
    } finally {
      setIsLoading(false);
    }
  }, [provider]);

  useEffect(() => {
    if (isOpen && provider) {
      loadCredentials();
    }
  }, [isOpen, provider, loadCredentials]);

  const handleTestKey = async (cred: CredentialItem) => {
    setTestingId(cred.id);
    try {
      const res = await api.providers.validate(cred.id);
      if (res?.status === 'active' || res?.is_valid) {
        showToast(`Key validated successfully! Latency: ${Math.round(res.latency_ms || 0)}ms`);
      } else {
        showToast(`Validation check completed: status is ${res?.status || 'active'}`);
      }
      await loadCredentials();
      onKeysChanged?.();
    } catch (err: any) {
      showToast(`Key validation failed: ${err?.message || 'Invalid key'}`);
      await loadCredentials();
      onKeysChanged?.();
    } finally {
      setTestingId(null);
    }
  };

  const handleDeleteKey = async (cred: CredentialItem) => {
    if (!window.confirm(`Disconnect and delete key ending in ${cred.masked_key.slice(-4)}?`)) {
      return;
    }
    setDeletingId(cred.id);
    try {
      await api.providers.deleteCredential(cred.id);
      showToast('Key disconnected and removed from gateway');
      await loadCredentials();
      onKeysChanged?.();
    } catch (err: any) {
      showToast(`Failed to remove key: ${err?.message || 'Error'}`);
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <SlideDrawer
      isOpen={isOpen}
      onClose={onClose}
      title={provider ? `Manage ${provider.name} Keys` : 'Manage Keys'}
      subtitle="View, test, or disconnect API keys connected to this provider account."
    >
      <div className="space-y-4 mt-2">
        {isLoading ? (
          <div className="py-8 text-center text-mute text-sm">
            <span className="inline-block w-5 h-5 border-2 border-violet border-t-transparent rounded-full animate-spin mr-2 align-middle" />
            Loading connected keys…
          </div>
        ) : credentials.length === 0 ? (
          <div className="text-center py-8 bg-black/[0.02] border border-dashed border-line rounded-card p-6">
            <div className="text-sm font-medium text-ink mb-1">No keys connected yet</div>
            <p className="text-xs text-mute mb-4">
              Add your API key to enable routing and discover available models.
            </p>
            <Button
              variant="dark"
              onClick={() => {
                onClose();
                onAddKey?.();
              }}
              className="text-xs px-4 py-2"
            >
              Add API key
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            {credentials.map((cred) => (
              <div
                key={cred.id}
                className="p-4 rounded-xl border border-line bg-white/70 shadow-sm space-y-3"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-semibold text-ink">
                      {cred.masked_key}
                    </span>
                    <Pill variant={cred.status === 'active' ? 'default' : 'warning'}>
                      {cred.status}
                    </Pill>
                  </div>
                  <span className="text-[11px] text-mute">
                    Added {new Date(cred.created_at).toLocaleDateString()}
                  </span>
                </div>

                {cred.last_validated_at && (
                  <div className="text-[12px] text-mute">
                    Last validated: {new Date(cred.last_validated_at).toLocaleTimeString()}
                  </div>
                )}

                <div className="flex items-center justify-end gap-2 pt-1 border-t border-line/60">
                  <Button
                    variant="line"
                    onClick={() => handleTestKey(cred)}
                    disabled={testingId === cred.id || deletingId === cred.id}
                    className="text-xs px-3 py-1.5"
                  >
                    {testingId === cred.id ? 'Testing…' : 'Test connection'}
                  </Button>
                  <Button
                    variant="line"
                    onClick={() => handleDeleteKey(cred)}
                    disabled={deletingId === cred.id || testingId === cred.id}
                    className="text-xs px-3 py-1.5 text-red-600 hover:text-red-700 hover:border-red-300"
                  >
                    {deletingId === cred.id ? 'Removing…' : 'Disconnect'}
                  </Button>
                </div>
              </div>
            ))}

            <div className="pt-2">
              <Button
                variant="line"
                onClick={() => {
                  onClose();
                  onAddKey?.();
                }}
                className="w-full text-xs py-2.5"
              >
                + Connect another key
              </Button>
            </div>
          </div>
        )}
      </div>
    </SlideDrawer>
  );
};
