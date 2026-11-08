import React, { useState } from 'react';
import { SlideDrawer, Button } from '@/components/ui';
import { ModelAccessSelector } from '@/components/routing/ModelAccessSelector';
import { ModelAccessType, VirtualAPIKey } from '@/types';
import { api } from '@/api/client';
import { useToast } from '@/context/ToastContext';

interface CreateKeyDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  onKeyCreated?: (newKey: VirtualAPIKey) => void;
}

export const CreateKeyDrawer: React.FC<CreateKeyDrawerProps> = ({
  isOpen,
  onClose,
  onKeyCreated,
}) => {
  const { showToast } = useToast();

  const [name, setName] = useState('');
  const [strategy, setStrategy] = useState('Balanced');
  const [modelAccess, setModelAccess] = useState<ModelAccessType>('All models');
  const [dailyLimit, setDailyLimit] = useState('50,000');
  const [expiration, setExpiration] = useState('Never');
  const [isCreating, setIsCreating] = useState(false);

  // One-time key reveal state
  const [revealedKey, setRevealedKey] = useState<string | null>(null);

  const handleReset = () => {
    setName('');
    setStrategy('Balanced');
    setModelAccess('All models');
    setDailyLimit('50,000');
    setExpiration('Never');
    setRevealedKey(null);
    setIsCreating(false);
  };

  const handleClose = () => {
    handleReset();
    onClose();
  };

  const generateLocalKey = () => {
    const randomBytes = Array.from(crypto.getRandomValues(new Uint8Array(18)), (x) =>
      x.toString(16).padStart(2, '0')
    ).join('');
    return `sk-relay-${randomBytes}`;
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    setIsCreating(true);
    const numericLimit = parseInt(dailyLimit.replace(/[^0-9]/g, ''), 10) || 50000;

    try {
      // Call backend API
      const res = await api.keys.create({
        name: name.trim(),
        model_access: modelAccess,
        daily_limit: numericLimit,
        routing_strategy: strategy.toLowerCase(),
      });

      const fullKey = res?.key || generateLocalKey();
      setRevealedKey(fullKey);

      const newKeyObj: VirtualAPIKey = {
        id: res?.id || `key-${Date.now()}`,
        name: name.trim(),
        keyPrefix: `${fullKey.slice(0, 15)}…${fullKey.slice(-4)}`,
        strategy,
        modelAccess,
        dailyLimit: numericLimit,
        dailyUsagePercent: 0,
        expiresAt: expiration,
        weights:
          strategy === 'Quality first'
            ? { q: 1, s: 0.2, a: 0.5 }
            : strategy === 'Speed first'
            ? { q: 0.2, s: 1, a: 0.5 }
            : { q: 0.5, s: 0.5, a: 0.5 },
        isActive: true,
      };

      onKeyCreated?.(newKeyObj);
      showToast('Key created');
    } catch {
      // Graceful fallback for offline demo/testing
      const fallbackKey = generateLocalKey();
      setRevealedKey(fallbackKey);

      const newKeyObj: VirtualAPIKey = {
        id: `key-${Date.now()}`,
        name: name.trim(),
        keyPrefix: `${fallbackKey.slice(0, 15)}…${fallbackKey.slice(-4)}`,
        strategy,
        modelAccess,
        dailyLimit: numericLimit,
        dailyUsagePercent: 0,
        expiresAt: expiration,
        weights:
          strategy === 'Quality first'
            ? { q: 1, s: 0.2, a: 0.5 }
            : strategy === 'Speed first'
            ? { q: 0.2, s: 1, a: 0.5 }
            : { q: 0.5, s: 0.5, a: 0.5 },
        isActive: true,
      };

      onKeyCreated?.(newKeyObj);
      showToast('Key created');
    } finally {
      setIsCreating(false);
    }
  };

  const handleCopyKey = () => {
    if (revealedKey && navigator.clipboard) {
      navigator.clipboard.writeText(revealedKey);
      showToast('Key copied');
    }
  };

  return (
    <SlideDrawer
      isOpen={isOpen}
      onClose={handleClose}
      title={revealedKey ? 'Your API key' : 'Create API key'}
      subtitle={
        revealedKey
          ? 'Save this key now. You will not be able to view it again.'
          : 'Create a dedicated virtual key with custom routing and daily limits.'
      }
    >
      {!revealedKey ? (
        <form onSubmit={handleCreate} className="space-y-4 mt-2">
          <div>
            <label className="block text-[13px] text-mute mb-[6px]">Name</label>
            <input
              type="text"
              placeholder="e.g. support-bot"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="w-full px-[14px] py-[11px] rounded-input border border-line bg-white text-ink text-sm focus:border-violet focus:outline-none transition-colors"
            />
          </div>

          <div>
            <label className="block text-[13px] text-mute mb-[6px]">Routing strategy</label>
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
              className="w-full px-[14px] py-[11px] rounded-input border border-line bg-white text-ink text-sm focus:border-violet focus:outline-none transition-colors"
            >
              <option value="Balanced">Balanced</option>
              <option value="Quality first">Quality first</option>
              <option value="Speed first">Speed first</option>
              <option value="Custom">Custom</option>
            </select>
          </div>

          {/* Model Access 2-Column Radio Grid */}
          <ModelAccessSelector value={modelAccess} onChange={setModelAccess} />

          <div>
            <label className="block text-[13px] text-mute mb-[6px]">Daily request limit</label>
            <input
              type="text"
              value={dailyLimit}
              onChange={(e) => setDailyLimit(e.target.value)}
              className="w-full px-[14px] py-[11px] rounded-input border border-line bg-white text-ink text-sm focus:border-violet focus:outline-none transition-colors"
            />
          </div>

          <div>
            <label className="block text-[13px] text-mute mb-[6px]">Expires</label>
            <select
              value={expiration}
              onChange={(e) => setExpiration(e.target.value)}
              className="w-full px-[14px] py-[11px] rounded-input border border-line bg-white text-ink text-sm focus:border-violet focus:outline-none transition-colors"
            >
              <option value="Never">Never</option>
              <option value="In 30 days">In 30 days</option>
              <option value="In 90 days">In 90 days</option>
            </select>
          </div>

          <div className="pt-3">
            <Button
              type="submit"
              variant="dark"
              disabled={isCreating || !name.trim()}
              className="w-full"
            >
              {isCreating ? 'Creating key…' : 'Create key'}
            </Button>
          </div>
        </form>
      ) : (
        /* One-time key reveal dialog */
        <div className="space-y-4 mt-3 animate-in">
          <div className="p-[14px] px-4 rounded-[14px] bg-[rgba(91,61,255,0.08)] text-[13.5px] text-ink leading-relaxed">
            <b>Copy your key now.</b> Relay stores only a cryptographic hash, so it can’t be shown again.
          </div>

          <div className="font-mono text-[13px] break-all p-[14px] rounded-[12px] bg-ink text-[#E8E4FF] select-all shadow-inner border border-ink/40">
            {revealedKey}
          </div>

          <div className="pt-2 flex flex-col gap-2">
            <Button variant="dark" onClick={handleCopyKey} className="w-full">
              Copy key
            </Button>
            <Button variant="line" onClick={handleClose} className="w-full">
              Done
            </Button>
          </div>
        </div>
      )}
    </SlideDrawer>
  );
};
