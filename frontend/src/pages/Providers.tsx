import React, { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui';
import {
  ProviderCard,
  ProviderData,
  ConnectProviderDrawer,
  ManageKeysDrawer,
} from '@/components/providers';
import { api } from '@/api/client';
import { useToast } from '@/context/ToastContext';

interface ProvidersProps {
  initialProviders?: ProviderData[];
}

const SUPPORTED_PROVIDERS: ProviderData[] = [
  {
    id: 'google',
    name: 'Google Gemini',
    providerKey: 'google',
    isHealthy: true,
    modelCount: 0,
    medianLatency: '0 ms',
    connectedKeys: '0 keys',
    quotaPercent: 0,
    latencyHistory: [0, 0, 0, 0, 0, 0, 0, 0],
    isCoolingDown: false,
    cooldownSeconds: 0,
    cooldownConfirmed: false,
  },
  {
    id: 'groq',
    name: 'Groq',
    providerKey: 'groq',
    isHealthy: true,
    modelCount: 0,
    medianLatency: '0 ms',
    connectedKeys: '0 keys',
    quotaPercent: 0,
    latencyHistory: [0, 0, 0, 0, 0, 0, 0, 0],
    isCoolingDown: false,
    cooldownSeconds: 0,
  },
  {
    id: 'openrouter',
    name: 'OpenRouter',
    providerKey: 'openrouter',
    isHealthy: true,
    modelCount: 0,
    medianLatency: '0 ms',
    connectedKeys: '0 keys',
    quotaPercent: 0,
    latencyHistory: [0, 0, 0, 0, 0, 0, 0, 0],
    isCoolingDown: false,
    cooldownSeconds: 0,
  },
];

export const Providers: React.FC<ProvidersProps> = ({ initialProviders }) => {
  const { showToast } = useToast();
  const [providers, setProviders] = useState<ProviderData[]>(initialProviders || SUPPORTED_PROVIDERS);
  const [isConnectDrawerOpen, setIsConnectDrawerOpen] = useState(false);
  const [selectedProviderForManage, setSelectedProviderForManage] = useState<ProviderData | null>(null);
  const [isManageDrawerOpen, setIsManageDrawerOpen] = useState(false);
  const [checkingId, setCheckingId] = useState<string | null>(null);

  // Load live data from API
  const loadProvidersData = useCallback(async () => {
    try {
      const [credsRes, healthRes, modelsRes] = await Promise.allSettled([
        api.providers.credentials(),
        api.reliability.credentialsHealth(),
        api.models.list(),
      ]);

      const creds = credsRes.status === 'fulfilled' && Array.isArray(credsRes.value) ? credsRes.value : [];
      const healthList = healthRes.status === 'fulfilled' && Array.isArray(healthRes.value) ? healthRes.value : [];
      const allModels = modelsRes.status === 'fulfilled' && Array.isArray(modelsRes.value?.models) ? modelsRes.value.models : [];

      setProviders((prev) =>
        prev.map((p) => {
          const pKey = p.providerKey.toLowerCase();
          const matchingCreds = creds.filter((c: any) => {
            const cp = (c.provider || '').toLowerCase();
            return (
              cp === pKey ||
              (pKey === 'google' && cp === 'gemini') ||
              (pKey === 'gemini' && cp === 'google')
            );
          });

          if (matchingCreds.length === 0) {
            return {
              ...p,
              credentialId: undefined,
              connectedKeys: '0 keys',
              modelCount: 0,
              isCoolingDown: false,
              isHealthy: true,
            };
          }

          const primaryCred = matchingCreds[0];
          const matchingHealth = healthList.find(
            (h: any) => h.credential_id === primaryCred.id
          );

          const isCooling =
            matchingHealth?.health_status === 'cooling_down' ||
            matchingHealth?.health_status === 'rate_limited';

          const provModels = allModels.filter((m: any) =>
            (m.offerings || m.routes || []).some((o: any) => {
              const op = (o.provider || '').toLowerCase();
              return (
                op === pKey ||
                (pKey === 'google' && op === 'gemini') ||
                (pKey === 'gemini' && op === 'google')
              );
            })
          );

          return {
            ...p,
            credentialId: primaryCred.id,
            connectedKeys: `${matchingCreds.length} key${matchingCreds.length > 1 ? 's' : ''}`,
            modelCount: provModels.length,
            isHealthy: !isCooling,
            isCoolingDown: isCooling,
            cooldownSeconds: matchingHealth?.cooldown_remaining_seconds || 0,
            medianLatency: matchingHealth?.latency_ms ? `${Math.round(matchingHealth.latency_ms)} ms` : p.medianLatency,
          };
        })
      );
    } catch {
      // Fallback cleanly
    }
  }, []);

  useEffect(() => {
    if (!initialProviders) {
      loadProvidersData();
    }
  }, [loadProvidersData, initialProviders]);

  // Live countdown timer for rate-limited providers
  useEffect(() => {
    const timer = setInterval(() => {
      setProviders((prev) =>
        prev.map((p) => {
          if (!p.isCoolingDown || !p.cooldownSeconds || p.cooldownSeconds <= 0) {
            return p;
          }
          const nextCd = p.cooldownSeconds - 1;
          if (nextCd <= 0) {
            showToast(`${p.name} is back in the routing pool`);
            return {
              ...p,
              isCoolingDown: false,
              isHealthy: true,
              cooldownSeconds: 0,
            };
          }
          return {
            ...p,
            cooldownSeconds: nextCd,
          };
        })
      );
    }, 1000);

    return () => clearInterval(timer);
  }, [showToast]);

  // Handle "Check now" action
  const handleCheckNow = async (provider: ProviderData) => {
    setCheckingId(provider.id);
    try {
      let targetCredId = provider.credentialId;
      if (!targetCredId) {
        // Look up credentials for this provider
        const creds = await api.providers.credentials();
        const pKey = provider.providerKey.toLowerCase();
        const found = (Array.isArray(creds) ? creds : []).find((c: any) => {
          const cp = (c.provider || '').toLowerCase();
          return (
            cp === pKey ||
            (pKey === 'google' && cp === 'gemini') ||
            (pKey === 'gemini' && cp === 'google')
          );
        });
        targetCredId = found?.id;
      }

      if (!targetCredId) {
        showToast(`No keys connected for ${provider.name}. Click "Connect provider" to add one.`);
        return;
      }

      await api.providers.validate(targetCredId);
      showToast(`${provider.name} connection checked`);
      await loadProvidersData();
    } catch {
      showToast(`${provider.name} connection checked`);
      await loadProvidersData();
    } finally {
      setCheckingId(null);
    }
  };

  const handleManageKeys = (provider: ProviderData) => {
    setSelectedProviderForManage(provider);
    setIsManageDrawerOpen(true);
  };

  return (
    <div>
      {/* Page Header */}
      <div className="flex justify-between items-end gap-5 mb-7 flex-wrap">
        <div>
          <h1 className="font-display font-light text-[42px] leading-appHeadline tracking-headline text-ink">
            Providers
          </h1>
          <p className="text-mute text-[15px] mt-2">
            Accounts Relay can route to. Each shows its quota use and recent latency.
          </p>
        </div>
        <Button variant="dark" onClick={() => setIsConnectDrawerOpen(true)}>
          Connect provider
        </Button>
      </div>

      {/* Provider Card Grid */}
      <div className="grid grid-cols-2 gap-4 max-app:grid-cols-1">
        {providers.map((p) => (
          <ProviderCard
            key={p.id}
            provider={p}
            onCheckNow={handleCheckNow}
            onManageKeys={handleManageKeys}
            isChecking={checkingId === p.id}
          />
        ))}
      </div>

      {/* Slide-in Connect Provider Drawer */}
      <ConnectProviderDrawer
        isOpen={isConnectDrawerOpen}
        onClose={() => setIsConnectDrawerOpen(false)}
        onConnected={loadProvidersData}
      />

      {/* Slide-in Manage Keys Drawer */}
      <ManageKeysDrawer
        isOpen={isManageDrawerOpen}
        onClose={() => {
          setIsManageDrawerOpen(false);
          setSelectedProviderForManage(null);
        }}
        provider={selectedProviderForManage}
        onKeysChanged={loadProvidersData}
        onAddKey={() => setIsConnectDrawerOpen(true)}
      />
    </div>
  );
};

export default Providers;
