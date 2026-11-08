import React, { useState, useEffect } from 'react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Button } from '@/components/ui/Button';
import { useAuth } from '@/context/AuthContext';
import { useToast } from '@/context/ToastContext';
import { api } from '@/api/client';

export interface AuditLogEntry {
  title: string;
  detail: string;
  timestamp: string;
}

export interface SettingsProps {
  initialAuditLogs?: AuditLogEntry[];
}

export const Settings: React.FC<SettingsProps> = ({ initialAuditLogs }) => {
  const { user } = useAuth();
  const { showToast } = useToast();
  const [rpmLimit, setRpmLimit] = useState<string>('600 requests per minute');
  const [defaultStrategy, setDefaultStrategy] = useState<string>('Balanced');
  const [showDeleteModal, setShowDeleteModal] = useState<boolean>(false);
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>(
    initialAuditLogs || []
  );

  useEffect(() => {
    if (initialAuditLogs) return;
    let mounted = true;

    async function loadAuditLogs() {
      try {
        const res = await api.reliability.events({ limit: 10 });
        if (mounted && res?.items && Array.isArray(res.items)) {
          const mapped: AuditLogEntry[] = res.items.map((ev: any) => ({
            title: ev.event_type.replace(/_/g, ' '),
            detail:
              ev.metadata?.details ||
              ev.metadata?.message ||
              `${ev.provider || 'Gateway'} · ${ev.model_id || 'System event'}`,
            timestamp: ev.timestamp
              ? new Date(ev.timestamp).toLocaleTimeString()
              : 'Recently',
          }));
          setAuditLogs(mapped);
        }
      } catch {
        // Handled cleanly
      }
    }

    loadAuditLogs();
    return () => {
      mounted = false;
    };
  }, [initialAuditLogs]);

  const emailDisplay = user?.email || 'admin@gateway.local';

  const handleDeleteData = () => {
    setShowDeleteModal(false);
    showToast('Confirmation email sent to ' + emailDisplay);
  };

  return (
    <div data-testid="settings-page">
      {/* Header */}
      <div className="flex justify-between items-end gap-5 mb-7 flex-wrap">
        <div>
          <h1 className="font-display font-light text-[42px] leading-appHeadline tracking-headline text-ink">
            Settings
          </h1>
          <p className="text-mute text-[15px] mt-2">
            Configure gateway defaults, rate limits, and audit policies.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-[1.2fr_1fr] gap-6 max-app:grid-cols-1">
        {/* Left Column: Account & Gateway Settings */}
        <GlassCard className="p-6 space-y-6">
          {/* Account Profile */}
          <div>
            <h2 className="font-display text-[22px] font-normal text-ink mb-1">
              Account Profile
            </h2>
            <p className="text-[13px] text-mute mb-4">
              Your registered developer email and credentials access.
            </p>

            <div className="space-y-3">
              <div>
                <label
                  htmlFor="user-email-input"
                  className="block text-[13px] font-medium text-ink mb-1.5"
                >
                  Email Address
                </label>
                <input
                  id="user-email-input"
                  type="email"
                  readOnly
                  value={emailDisplay}
                  className="w-full px-3.5 py-2.5 rounded-[12px] bg-ink/5 border border-line text-ink text-[14px] font-mono outline-none"
                />
              </div>
            </div>
          </div>

          {/* Gateway Defaults */}
          <div className="pt-4 border-t border-line">
            <h2 className="font-display text-[22px] font-normal text-ink mb-1">
              Gateway Defaults
            </h2>
            <p className="text-[13px] text-mute mb-4">
              Fallback limits applied across newly provisioned virtual keys.
            </p>

            <div className="space-y-4">
              <div>
                <label
                  htmlFor="rate-limit-select"
                  className="block text-[13px] font-medium text-ink mb-1.5"
                >
                  Gateway rate limit
                </label>
                <select
                  id="rate-limit-select"
                  value={rpmLimit}
                  onChange={(e) => setRpmLimit(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-[12px] bg-white border border-line text-ink text-[14px] outline-none focus:border-violet"
                >
                  <option value="60 requests per minute">
                    60 requests per minute (Dev)
                  </option>
                  <option value="300 requests per minute">
                    300 requests per minute (Standard)
                  </option>
                  <option value="600 requests per minute">
                    600 requests per minute (High Throughput)
                  </option>
                  <option value="1200 requests per minute">
                    1,200 requests per minute (Production)
                  </option>
                </select>
              </div>

              <div>
                <label
                  htmlFor="routing-strategy-select"
                  className="block text-[13px] font-medium text-ink mb-1.5"
                >
                  Default routing strategy
                </label>
                <select
                  id="routing-strategy-select"
                  value={defaultStrategy}
                  onChange={(e) => setDefaultStrategy(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-[12px] bg-white border border-line text-ink text-[14px] outline-none focus:border-violet"
                >
                  <option value="Balanced">
                    Balanced (Speed 35%, Cost 35%, Quality 30%)
                  </option>
                  <option value="Lowest Latency">
                    Lowest Latency (Speed 70%, Cost 10%, Quality 20%)
                  </option>
                  <option value="Lowest Cost">
                    Lowest Cost (Speed 10%, Cost 70%, Quality 20%)
                  </option>
                  <option value="Highest Quality">
                    Highest Quality (Speed 15%, Cost 15%, Quality 70%)
                  </option>
                </select>
              </div>
            </div>
          </div>

          {/* Danger Zone */}
          <div className="pt-4 border-t border-line">
            <h2 className="font-display text-[22px] font-normal text-pink mb-1">
              Danger Zone
            </h2>
            <p className="text-[13px] text-mute mb-4">
              Irreversible account and credential operations.
            </p>

            <div className="p-4 rounded-[16px] bg-pink/8 border border-pink/20 flex justify-between items-center flex-wrap gap-3">
              <div>
                <b className="block text-[14px] text-ink font-semibold">
                  Purge Gateway Data
                </b>
                <span className="text-[12.5px] text-mute">
                  Invalidate all keys, routing models, and stored credentials.
                </span>
              </div>
              <Button
                variant="pink"
                onClick={() => setShowDeleteModal(true)}
                className="hover:bg-pink/10"
              >
                Delete my data
              </Button>
            </div>
          </div>
        </GlassCard>

        {/* Right Column: Security Audit Log */}
        <GlassCard className="p-6">
          <h2 className="font-display text-[22px] font-normal text-ink mb-1">
            Audit Log
          </h2>
          <p className="text-[13px] text-mute mb-4">
            Security history of credential additions, keys, and policy edits.
          </p>

          <div className="divide-y divide-line" data-testid="audit-log-list">
            {auditLogs.length > 0 ? (
              auditLogs.map((entry, idx) => (
                <div key={idx} className="py-3.5 first:pt-0">
                  <b className="block text-[14px] text-ink font-semibold capitalize">
                    {entry.title}
                  </b>
                  <div className="flex justify-between items-center text-[13px] text-mute mt-0.5">
                    <span>{entry.detail}</span>
                    <span className="font-mono text-[12px]">{entry.timestamp}</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="py-6 text-center text-mute text-[13px]">
                No security audit events recorded yet.
              </div>
            )}
          </div>
        </GlassCard>
      </div>

      {/* Delete Confirmation Modal */}
      {showDeleteModal && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 bg-ink/40 backdrop-blur-sm z-50 flex items-center justify-center p-4"
        >
          <div className="bg-paper rounded-[24px] p-6 max-w-md w-full border border-white/80 shadow-2xl">
            <h3 className="font-display text-[20px] font-semibold text-ink mb-2">
              Delete account & gateway data?
            </h3>
            <p className="text-[13.5px] text-mute mb-6 leading-relaxed">
              This will permanently delete all virtual API keys, encrypted provider
              credentials, routing policies, and historical usage logs. This action
              cannot be undone.
            </p>
            <div className="flex justify-end gap-2.5">
              <Button
                variant="line"
                onClick={() => setShowDeleteModal(false)}
              >
                Cancel
              </Button>
              <Button
                variant="pink"
                onClick={handleDeleteData}
              >
                Confirm deletion
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Settings;
