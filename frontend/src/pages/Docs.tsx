import React, { useState } from 'react';
import { GlassCard } from '@/components/ui/GlassCard';
import { Button } from '@/components/ui/Button';
import { Pill } from '@/components/ui/Pill';
import { useToast } from '@/context/ToastContext';

type CodeLanguage = 'python' | 'curl' | 'nodejs';

const PYTHON_SNIPPET = `from openai import OpenAI

# Point client to your Relay Gateway
client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-relay-4f9ac21e...",  # Your Relay Virtual Key
)

# Use "auto" to let Relay rank models by your key's strategy,
# or specify an explicit model like "gemini:gemini-2.5-flash"
response = client.chat.completions.create(
    model="auto",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Explain quantum entanglement in 2 sentences."}
    ],
    temperature=0.7,
)

print(response.choices[0].message.content)`;

const CURL_SNIPPET = `curl -X POST http://localhost:8000/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer sk-relay-4f9ac21e..." \\
  -d '{
    "model": "auto",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Explain quantum entanglement in 2 sentences."}
    ],
    "temperature": 0.7
  }'`;

const NODE_SNIPPET = `import OpenAI from "openai";

// Point client to your Relay Gateway
const client = new OpenAI({
  baseURL: "http://localhost:8000/v1",
  apiKey: "sk-relay-4f9ac21e...", // Your Relay Virtual Key
});

async function main() {
  const response = await client.chat.completions.create({
    model: "auto",
    messages: [
      { role: "system", content: "You are a helpful assistant." },
      { role: "user", content: "Explain quantum entanglement in 2 sentences." },
    ],
    temperature: 0.7,
  });

  console.log(response.choices[0].message.content);
}

main();`;

export const Docs: React.FC = () => {
  const [activeLang, setActiveLang] = useState<CodeLanguage>('python');
  const { showToast } = useToast();

  const getActiveCode = () => {
    switch (activeLang) {
      case 'python':
        return PYTHON_SNIPPET;
      case 'curl':
        return CURL_SNIPPET;
      case 'nodejs':
        return NODE_SNIPPET;
    }
  };

  const handleCopyCode = async () => {
    try {
      await navigator.clipboard.writeText(getActiveCode());
      showToast('Code snippet copied to clipboard');
    } catch {
      showToast('Snippet copied');
    }
  };

  return (
    <div data-testid="docs-page" className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-end gap-5 mb-7 flex-wrap">
        <div>
          <h1 className="font-display font-light text-[42px] leading-appHeadline tracking-headline text-ink">
            Developer Documentation
          </h1>
          <p className="text-mute text-[15px] mt-2">
            One API. Every model. Drop-in OpenAI SDK integration with automatic failover.
          </p>
        </div>
      </div>

      {/* Interactive Drop-in SDK Code Section */}
      <GlassCard className="p-6">
        <div className="flex justify-between items-center mb-4 flex-wrap gap-3">
          <div>
            <h2 className="font-display text-[22px] font-normal text-ink">
              Quickstart Integration
            </h2>
            <p className="text-[13px] text-mute mt-0.5">
              Change the URL. Keep your existing code.
            </p>
          </div>

          <div className="flex items-center gap-2">
            {/* Language tabs */}
            <div className="flex gap-1" role="tablist" aria-label="Code language">
              {(
                [
                  { id: 'python', label: 'Python (OpenAI SDK)' },
                  { id: 'curl', label: 'cURL' },
                  { id: 'nodejs', label: 'Node.js' },
                ] as const
              ).map((tab) => (
                <button
                  key={tab.id}
                  role="tab"
                  aria-selected={activeLang === tab.id}
                  onClick={() => setActiveLang(tab.id)}
                  className={`px-3 py-1.5 rounded-pill text-[13px] border transition-colors ${
                    activeLang === tab.id
                      ? 'bg-ink text-white border-ink'
                      : 'bg-white/50 text-mute border-line hover:text-ink'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <Button
              variant="line"
              onClick={handleCopyCode}
              data-testid="copy-code-btn"
            >
              Copy snippet
            </Button>
          </div>
        </div>

        {/* Syntax Highlighted Code Container */}
        <div className="p-4 rounded-[16px] bg-[#1A1530] text-[#E8E4FF] font-mono text-[13px] leading-relaxed overflow-x-auto shadow-inner">
          <pre className="whitespace-pre">
            <code>{getActiveCode()}</code>
          </pre>
        </div>
      </GlassCard>

      {/* Gateway API Reference Table */}
      <div className="grid grid-cols-2 gap-4 max-app:grid-cols-1">
        <GlassCard className="p-6">
          <h2 className="font-display text-[22px] font-normal text-ink mb-1">
            API Endpoints
          </h2>
          <p className="text-[13px] text-mute mb-4">
            Standard OpenAI-compatible REST endpoints.
          </p>

          <div className="space-y-3">
            <div className="p-3 rounded-[12px] bg-white/40 border border-line">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[11px] font-mono font-semibold px-2 py-0.5 rounded-pill bg-violet/10 text-violet">
                  POST
                </span>
                <code className="text-[13px] font-mono text-ink">
                  /v1/chat/completions
                </code>
              </div>
              <p className="text-[12.5px] text-mute">
                Chat completions with capability routing, streaming SSE, and automatic failover.
              </p>
            </div>

            <div className="p-3 rounded-[12px] bg-white/40 border border-line">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[11px] font-mono font-semibold px-2 py-0.5 rounded-pill bg-ink/10 text-ink">
                  GET
                </span>
                <code className="text-[13px] font-mono text-ink">/v1/models</code>
              </div>
              <p className="text-[12.5px] text-mute">
                List all unified and provider-specific models reachable with your virtual key.
              </p>
            </div>
          </div>
        </GlassCard>

        {/* Core Architecture Capabilities */}
        <GlassCard className="p-6">
          <h2 className="font-display text-[22px] font-normal text-ink mb-1">
            Key Routing Features
          </h2>
          <p className="text-[13px] text-mute mb-4">
            Built-in resilience and cost optimization features.
          </p>

          <div className="space-y-3">
            <div className="p-3 rounded-[12px] bg-white/40 border border-line">
              <b className="text-[13.5px] text-ink block font-semibold">
                Model: "auto"
              </b>
              <p className="text-[12.5px] text-mute mt-0.5">
                Automatically evaluates context window, tools, rate limits, and ranks candidates according to your key's policy.
              </p>
            </div>

            <div className="p-3 rounded-[12px] bg-white/40 border border-line">
              <b className="text-[13.5px] text-ink block font-semibold">
                3-Level Automatic Failover
              </b>
              <p className="text-[12.5px] text-mute mt-0.5">
                Fails over across keys (Level 1), compatible models (Level 2), or alternative providers (Level 3) on 429s and 5xxs.
              </p>
            </div>

            <div className="p-3 rounded-[12px] bg-white/40 border border-line">
              <b className="text-[13.5px] text-ink block font-semibold">
                Pre-Chunk Stream Retry
              </b>
              <p className="text-[12.5px] text-mute mt-0.5">
                Failovers are seamless before the first SSE chunk. Once streaming begins, normalized terminal error semantics are strictly enforced.
              </p>
            </div>
          </div>
        </GlassCard>
      </div>
    </div>
  );
};

export default Docs;
