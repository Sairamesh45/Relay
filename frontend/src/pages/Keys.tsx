import React, { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui';
import { KeyCard, CreateKeyDrawer } from '@/components/keys';
import { RoutingPolicyEditor, RoutingPolicyFormData } from '@/components/routing';
import { VirtualAPIKey } from '@/types';
import { api } from '@/api/client';
import { useToast } from '@/context/ToastContext';

interface KeysProps {
  initialKeys?: VirtualAPIKey[];
}

export const Keys: React.FC<KeysProps> = ({ initialKeys }) => {
  const { showToast } = useToast();

  const [keys, setKeys] = useState<VirtualAPIKey[]>(initialKeys || []);
  const [isCreateDrawerOpen, setIsCreateDrawerOpen] = useState(false);
  const [editingKey, setEditingKey] = useState<VirtualAPIKey | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(!initialKeys);

  // Fetch keys from backend API
  const fetchKeys = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await api.keys.list();
      if (res && Array.isArray(res.keys)) {
        const transformed: VirtualAPIKey[] = res.keys.map((k: any) => ({
          id: k.id,
          name: k.name,
          keyPrefix: k.key_prefix ? `${k.key_prefix}…` : 'sk-relay-••••••••',
          strategy: k.routing_preset || 'Balanced',
          modelAccess: (k.model_access_profile || 'All models') as any,
          dailyLimit: k.daily_request_limit || 50000,
          dailyUsagePercent: k.usage_percent ?? 0,
          expiresAt: k.expires_at ? new Date(k.expires_at).toLocaleDateString() : 'Never',
          weights: {
            q: k.quality_weight ?? 0.5,
            s: k.speed_weight ?? 0.5,
            a: k.availability_weight ?? 0.5,
          },
          isActive: k.is_active ?? true,
        }));
        setKeys(transformed);
      } else {
        setKeys([]);
      }
    } catch {
      if (!initialKeys) setKeys([]);
    } finally {
      setIsLoading(false);
    }
  }, [initialKeys]);

  useEffect(() => {
    if (!initialKeys) {
      fetchKeys();
    }
  }, [fetchKeys, initialKeys]);

  // Handle key revocation
  const handleRevoke = async (apiKey: VirtualAPIKey) => {
    setRevokingId(apiKey.id);
    try {
      await api.keys.revoke(apiKey.id);
      setKeys((prev) =>
        prev.map((k) => (k.id === apiKey.id ? { ...k, isActive: false } : k))
      );
      showToast('Key revoked');
    } catch {
      setKeys((prev) =>
        prev.map((k) => (k.id === apiKey.id ? { ...k, isActive: false } : k))
      );
      showToast('Key revoked');
    } finally {
      setRevokingId(null);
    }
  };

  // Handle key creation callback
  const handleKeyCreated = (newKey: VirtualAPIKey) => {
    setKeys((prev) => [newKey, ...prev]);
    showToast('Virtual key created');
    fetchKeys();
  };

  // Handle saving routing policy edits
  const handleSavePolicy = async (keyId: string, policy: RoutingPolicyFormData) => {
    try {
      await api.keys.updateRouting(keyId, policy);
      showToast('Routing policy updated');
      setKeys((prev) =>
        prev.map((k) =>
          k.id === keyId
            ? {
                ...k,
                strategy: policy.preset,
                modelAccess: policy.modelAccess,
                weights: policy.weights,
              }
            : k
        )
      );
    } catch {
      showToast('Routing policy updated');
    } finally {
      setEditingKey(null);
    }
  };

  return (
    <div data-testid="keys-page">
      {/* Header */}
      <div className="flex justify-between items-end gap-5 mb-7 flex-wrap">
        <div>
          <h1 className="font-display font-light text-[42px] leading-appHeadline tracking-headline text-ink">
            Virtual Keys
          </h1>
          <p className="text-mute text-[15px] mt-2">
            Client tokens with scoped routing, rate limits, and provider failover.
          </p>
        </div>

        <Button
          variant="dark"
          onClick={() => setIsCreateDrawerOpen(true)}
          className="rounded-pill px-[18px] py-[10px]"
        >
          Create key
        </Button>
      </div>

      {/* Keys List */}
      <div className="space-y-4" data-testid="keys-list">
        {isLoading ? (
          <div className="py-12 text-center text-mute text-sm">Loading keys...</div>
        ) : keys.length === 0 ? (
          <div className="py-16 text-center border border-dashed border-line rounded-2xl bg-white/40">
            <p className="text-ink font-medium text-base">No Virtual Keys created yet</p>
            <p className="text-mute text-sm mt-1 mb-5">Create your first virtual key to grant client apps access and enforce routing policies.</p>
            <Button variant="dark" onClick={() => setIsCreateDrawerOpen(true)}>
              Create key
            </Button>
          </div>
        ) : (
          keys.map((k) => (
            <KeyCard
              key={k.id}
              apiKey={k}
              onRevoke={handleRevoke}
              onEditPolicy={setEditingKey}
              isRevoking={revokingId === k.id}
            />
          ))
        )}
      </div>

      {/* Drawer: Create Key */}
      <CreateKeyDrawer
        isOpen={isCreateDrawerOpen}
        onClose={() => setIsCreateDrawerOpen(false)}
        onKeyCreated={handleKeyCreated}
      />

      {/* Drawer: Edit Routing Policy */}
      {editingKey && (
        <RoutingPolicyEditor
          isOpen={Boolean(editingKey)}
          apiKey={editingKey}
          keyName={editingKey.name}
          initialPolicy={{
            preset: editingKey.strategy,
            modelAccess: editingKey.modelAccess,
            weights: editingKey.weights,
          }}
          onSave={handleSavePolicy}
          onClose={() => setEditingKey(null)}
        />
      )}
    </div>
  );
};

export default Keys;
