import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/Button';

interface CandidateModel {
  name: string;
  provider: string;
  latency: string;
  isFree: boolean;
  rateLimitNote?: string;
}

const MODELS_DATA: Record<string, CandidateModel> = {
  gem: {
    name: 'Gemini Flash',
    provider: 'Google Gemini',
    latency: '620 ms',
    isFree: true,
    rateLimitNote: 'Paused by 429 · resets in about 38 s (confirmed)',
  },
  groq: {
    name: 'Groq Llama',
    provider: 'Groq',
    latency: '310 ms',
    isFree: true,
  },
  cer: {
    name: 'Cerebras Llama',
    provider: 'Cerebras',
    latency: '180 ms',
    isFree: true,
  },
  or: {
    name: 'OpenRouter Qwen',
    provider: 'OpenRouter',
    latency: '740 ms',
    isFree: false,
  },
};

const STRATEGIES = {
  balanced: {
    order: ['gem', 'groq', 'cer', 'or'],
    title: 'Balanced',
    explanation: (
      <>
        <strong className="text-ink font-semibold">Balanced.</strong> Gemini Flash ranked first
        but is rate limited, so Groq Llama is next on quality, speed and availability combined.
      </>
    ),
  },
  quality: {
    order: ['gem', 'or', 'groq', 'cer'],
    title: 'Quality',
    explanation: (
      <>
        <strong className="text-ink font-semibold">Quality first.</strong> Gemini Flash is
        paused, so the next preferred model, OpenRouter Qwen, takes the request.
      </>
    ),
  },
  speed: {
    order: ['cer', 'groq', 'gem', 'or'],
    title: 'Speed',
    explanation: (
      <>
        <strong className="text-ink font-semibold">Speed first.</strong> Cerebras Llama has the
        lowest observed latency and is available.
      </>
    ),
  },
};

type StrategyKey = keyof typeof STRATEGIES;

const HOURLY_BARS = [34, 38, 31, 40, 52, 61, 58, 66, 72, 64, 80, 74, 69, 77, 85, 70, 62, 56, 48, 44, 52, 58, 41, 36];
const PINK_HOURS = [10, 15, 21];

export const Landing: React.FC = () => {
  const [strategy, setStrategy] = useState<StrategyKey>('balanced');

  const currentStrategy = STRATEGIES[strategy];

  // In each strategy, the first eligible (non-gem) candidate is selected
  let picked = false;

  return (
    <div id="landing" className="bg-marshmallow text-ink font-body min-h-screen">
      <div className="max-w-landing mx-auto px-7 max-app:px-4">
        {/* Navigation */}
        <nav className="flex items-center justify-between py-[22px]" aria-label="Main Navigation">
          <Link to="/" className="flex items-center gap-[10px] font-display font-semibold text-[19px] tracking-[-0.02em]">
            <span className="w-[26px] h-[26px] rounded-[8px] bg-ink grid place-items-center">
              <i className="w-[10px] h-[10px] rounded-full bg-gradient-to-br from-violet to-pink block" />
            </span>
            Relay
          </Link>
          <div className="flex gap-[34px] text-[14.5px] text-mute max-app:hidden">
            <a href="#how" className="hover:text-ink transition-colors">How it works</a>
            <a href="#routing" className="hover:text-ink transition-colors">Routing</a>
            <a href="#dashboard" className="hover:text-ink transition-colors">Dashboard</a>
            <a href="#security" className="hover:text-ink transition-colors">Security</a>
          </div>
          <Link
            to="/login"
            className="inline-flex items-center gap-[10px] px-5 py-[11px] rounded-pill font-medium text-[14.5px] bg-ink text-white hover:bg-violet transition-colors cursor-pointer"
          >
            Sign in with Google
          </Link>
        </nav>

        {/* Hero Section */}
        <header className="pt-[70px] pb-10">
          <div className="flex justify-between items-end gap-10 flex-wrap">
            <h1 className="font-display font-light text-[clamp(52px,9vw,128px)] leading-headline tracking-headline max-w-[11ch] animate-rise">
              One API.<br />Every model.
            </h1>
            <div className="animate-rise [animation-delay:0.12s]">
              <p className="text-mute max-w-[46ch] mt-0 text-[16px] leading-[1.6]">
                Connect the AI accounts you already have. Relay picks the right model for each
                request and switches automatically when one runs out.
              </p>
              <div className="flex gap-3 mt-[34px] flex-wrap">
                <Link
                  to="/login"
                  className="inline-flex items-center gap-[10px] px-5 py-[11px] rounded-pill font-medium text-[14.5px] bg-ink text-white hover:bg-violet transition-colors"
                >
                  Connect your providers
                </Link>
                <a
                  href="#how"
                  className="inline-flex items-center gap-[10px] px-5 py-[11px] rounded-pill font-medium text-[14.5px] border border-line-landing hover:border-ink transition-colors"
                >
                  See how it works
                </a>
              </div>
            </div>
          </div>

          {/* Live Interactive Routing Stage */}
          <div
            className="relative mt-16 rounded-[28px] overflow-hidden min-h-[560px] p-11 max-app:p-5 max-app:min-h-0 max-app:grid max-app:gap-4 shadow-xl"
            style={{
              background: `radial-gradient(60% 80% at 8% 100%, #FF66E0 0, transparent 62%),
                           radial-gradient(70% 90% at 95% 0%, #5B3DFF 0, transparent 60%),
                           linear-gradient(160deg, #EDEAFF, #F7E8F6)`,
            }}
            aria-label="Live routing preview"
          >
            {/* Incoming request glass card */}
            <div className="w-[min(340px,100%)] p-5 relative z-10 bg-white/60 backdrop-blur-[22px] backdrop-saturate-[1.3] border border-white/70 rounded-[20px] shadow-sm">
              <small className="text-mute text-[12.5px] block font-medium">Incoming request</small>
              <pre className="font-mono font-medium text-[13px] leading-[1.7] mt-[10px] whitespace-pre-wrap text-ink">
                model: <b className="text-violet font-semibold">"auto"</b>{'\n'}
                messages: 1{'\n'}
                needs: text, streaming{'\n'}
                context: 3,420 tokens
              </pre>
            </div>

            {/* Live routing decision router card */}
            <div className="absolute right-11 top-11 w-[min(470px,calc(100%-88px))] p-[22px] z-10 bg-white/60 backdrop-blur-[22px] backdrop-saturate-[1.3] border border-white/70 rounded-[20px] shadow-md max-app:static max-app:w-full">
              <small className="text-mute text-[12.5px] block font-medium">Routing decision</small>
              
              {/* Strategy segmented control */}
              <div
                className="flex gap-1 p-1 rounded-pill bg-ink/5 my-[14px] flex-wrap"
                role="group"
                aria-label="Routing strategy"
              >
                {(['balanced', 'quality', 'speed'] as StrategyKey[]).map((key) => {
                  const isSelected = strategy === key;
                  return (
                    <button
                      key={key}
                      type="button"
                      aria-pressed={isSelected}
                      onClick={() => setStrategy(key)}
                      className={`flex-1 border-0 rounded-pill py-[7px] px-[10px] font-body font-medium text-[12.5px] cursor-pointer transition-colors ${
                        isSelected
                          ? 'bg-ink text-white shadow-sm'
                          : 'bg-transparent text-mute hover:text-ink'
                      }`}
                    >
                      {STRATEGIES[key].title}
                    </button>
                  );
                })}
              </div>

              {/* Candidates list */}
              <ul className="list-none p-0 grid gap-2">
                {currentStrategy.order.map((id) => {
                  const model = MODELS_DATA[id];
                  let isPick = false;
                  let tagContent = 'Eligible';
                  let tagClass = 'bg-[rgba(91,61,255,0.1)] text-violet';
                  let subtext = `${model.provider} · ${model.latency}`;

                  if (id === 'gem') {
                    tagContent = 'Paused';
                    tagClass = 'bg-[rgba(26,21,48,0.07)] text-mute';
                    subtext = model.rateLimitNote || '';
                  } else if (!picked) {
                    picked = true;
                    isPick = true;
                    tagContent = 'Selected';
                    tagClass = 'bg-violet text-white shadow-sm';
                  }

                  return (
                    <li
                      key={id}
                      className={`grid grid-cols-[1fr_auto] gap-[2px_12px] p-[11px_14px] rounded-[14px] transition-all duration-300 border ${
                        isPick
                          ? 'border-violet bg-white shadow-sm'
                          : 'border-transparent bg-white/70'
                      }`}
                    >
                      <span className="font-semibold text-[14.5px] text-ink">{model.name}</span>
                      <span
                        className={`self-center row-span-2 text-[12px] font-medium py-1 px-[10px] rounded-pill ${tagClass}`}
                      >
                        {tagContent}
                      </span>
                      <span className="text-[12.5px] text-mute">{subtext}</span>
                    </li>
                  );
                })}
              </ul>

              {/* Reasoning paragraph */}
              <p className="mt-[14px] text-[13px] text-mute min-h-[40px] leading-relaxed">
                {currentStrategy.explanation}
              </p>
            </div>

            {/* Reliability ring glass badge */}
            <div className="absolute right-14 bottom-10 w-[150px] p-4 z-10 text-center bg-white/60 backdrop-blur-[22px] backdrop-saturate-[1.3] border border-white/70 rounded-[20px] shadow-sm max-app:static max-app:w-full">
              <small className="text-mute text-[12.5px] block font-medium">Served without error</small>
              <div className="font-display font-light text-[40px] tracking-kpi text-ink leading-tight my-1">
                99.8%
              </div>
              <small className="text-mute text-[12.5px] block">last 24 hours</small>
            </div>

            <h3 className="font-display font-light text-[clamp(28px,3.4vw,44px)] text-white max-w-[13ch] absolute left-11 bottom-10 leading-headline max-app:static max-app:mt-5 max-app:text-ink">
              See every routing decision.
            </h3>
          </div>
        </header>

        {/* How It Works Section */}
        <section id="how" className="pt-[120px] max-app:pt-16">
          <div className="grid grid-cols-2 gap-[72px] items-start max-app:grid-cols-1 max-app:gap-10">
            <div>
              <h2 className="font-display font-light text-[clamp(34px,4.6vw,56px)] leading-headline tracking-headline max-w-[15ch]">
                Change the URL. Keep your code.
              </h2>
              <p className="text-mute text-[16px] leading-[1.6] max-w-[46ch] mt-[22px]">
                Relay speaks the OpenAI API. Point your existing client at one endpoint with one
                key, and every connected provider is available behind it.
              </p>
              <p className="text-mute text-[16px] leading-[1.6] max-w-[46ch] mt-[14px]">
                Ask for a specific model, or send{' '}
                <span className="font-semibold text-ink">auto</span> and let Relay choose.
              </p>
            </div>

            {/* OpenAI SDK Code Block */}
            <pre className="bg-ink text-[#E8E4FF] rounded-card p-7 font-mono text-[13.5px] leading-[1.8] overflow-x-auto shadow-2xl">
              <code>
                <span className="text-[#B7A8FF]">from</span> openai{' '}
                <span className="text-[#B7A8FF]">import</span> OpenAI{'\n\n'}
                client = OpenAI({'\n'}
                {'    '}api_key=<span className="text-[#FF9BEB]">"sk-relay-your-key"</span>,{'\n'}
                {'    '}base_url=<span className="text-[#FF9BEB]">"https://api.relay.dev/v1"</span>{'\n'}
                ){'\n\n'}
                reply = client.chat.completions.create({'\n'}
                {'    '}model=<span className="text-[#FF9BEB]">"auto"</span>,{'\n'}
                {'    '}messages=[{'{'}{'\n'}
                {'        '}<span className="text-[#FF9BEB]">"role"</span>:{' '}
                <span className="text-[#FF9BEB]">"user"</span>,{'\n'}
                {'        '}<span className="text-[#FF9BEB]">"content"</span>:{' '}
                <span className="text-[#FF9BEB]">"Explain how RAG works."</span>{'\n'}
                {'    '}{'}'}]{'\n'}
                ){'\n'}
                <span className="text-[#8A84A8]"># Served by Groq. Gemini was rate limited.</span>
              </code>
            </pre>
          </div>
        </section>

        {/* Routing Architecture Breakdown */}
        <section id="routing" className="pt-[120px] max-app:pt-16">
          <h2 className="font-display font-light text-[clamp(34px,4.6vw,56px)] leading-headline tracking-headline max-w-[15ch]">
            Built to keep requests flowing.
          </h2>
          <div className="border-t border-line-landing mt-14">
            <article className="grid grid-cols-[200px_1fr] gap-7 py-[34px] border-b border-line-landing max-app:grid-cols-1 max-app:gap-[10px]">
              <h3 className="font-display font-normal text-[26px]">Model registry</h3>
              <div>
                <p className="text-mute max-w-[52ch] text-[15px] leading-relaxed">
                  Every model your accounts can reach, in one list. When the same model is
                  available from two providers, Relay keeps both routes.
                </p>
                <div className="mt-3 flex gap-2 flex-wrap">
                  <span className="text-[12.5px] px-[11px] py-1 rounded-pill border border-line-landing text-mute">
                    Context window
                  </span>
                  <span className="text-[12.5px] px-[11px] py-1 rounded-pill border border-line-landing text-mute">
                    Tool calling
                  </span>
                  <span className="text-[12.5px] px-[11px] py-1 rounded-pill border border-line-landing text-mute">
                    Streaming
                  </span>
                </div>
              </div>
            </article>

            <article className="grid grid-cols-[200px_1fr] gap-7 py-[34px] border-b border-line-landing max-app:grid-cols-1 max-app:gap-[10px]">
              <h3 className="font-display font-normal text-[26px]">Routing</h3>
              <div>
                <p className="text-mute max-w-[52ch] text-[15px] leading-relaxed">
                  Each request goes to a model that can actually handle it. Relay checks
                  capabilities, context size, current limits and recent speed, then ranks what is
                  left by the strategy you choose.
                </p>
                <div className="mt-3 flex gap-2 flex-wrap">
                  <span className="text-[12.5px] px-[11px] py-1 rounded-pill border border-line-landing text-mute">
                    Quality first
                  </span>
                  <span className="text-[12.5px] px-[11px] py-1 rounded-pill border border-line-landing text-mute">
                    Speed first
                  </span>
                  <span className="text-[12.5px] px-[11px] py-1 rounded-pill border border-line-landing text-mute">
                    Balanced
                  </span>
                  <span className="text-[12.5px] px-[11px] py-1 rounded-pill border border-line-landing text-mute">
                    Custom
                  </span>
                </div>
              </div>
            </article>

            <article className="grid grid-cols-[200px_1fr] gap-7 py-[34px] border-b border-line-landing max-app:grid-cols-1 max-app:gap-[10px]">
              <h3 className="font-display font-normal text-[26px]">Quotas</h3>
              <div>
                <p className="text-mute max-w-[52ch] text-[15px] leading-relaxed">
                  Relay watches rate limits and pauses a model the moment it returns a 429. It
                  shows whether a recovery time is confirmed by the provider or only estimated.
                </p>
              </div>
            </article>

            <article className="grid grid-cols-[200px_1fr] gap-7 py-[34px] border-b border-line-landing max-app:grid-cols-1 max-app:gap-[10px]">
              <h3 className="font-display font-normal text-[26px]">Failover</h3>
              <div>
                <p className="text-mute max-w-[52ch] text-[15px] leading-relaxed">
                  Timeouts, server errors and rate limits move the request to the next compatible
                  model. Bad credentials and unsupported features are reported instead of
                  retried. Paused models rejoin the pool when they recover.
                </p>
              </div>
            </article>
          </div>
        </section>

        {/* Dashboard Preview Section */}
        <section id="dashboard" className="pt-[120px] max-app:pt-16">
          <h2 className="font-display font-light text-[clamp(34px,4.6vw,56px)] leading-headline tracking-headline max-w-[15ch]">
            Know what happened and why.
          </h2>
          <p className="text-mute text-[16px] leading-[1.6] max-w-[46ch] mt-[22px]">
            Open any request to see which model answered and why the others were skipped.
          </p>

          <div className="mt-14 rounded-[26px] bg-paper border border-line-landing grid grid-cols-[200px_1fr] overflow-hidden shadow-[0_40px_80px_-40px_rgba(91,61,255,0.35)] max-app:grid-cols-1">
            {/* Embedded sidebar */}
            <aside className="p-[24px_18px] border-r border-line-landing flex flex-col gap-1 text-[14px] text-mute max-app:hidden">
              <span className="flex items-center gap-[10px] font-display font-semibold text-[19px] tracking-[-0.02em] text-ink m-[0_6px_22px]">
                <span className="w-[26px] h-[26px] rounded-[8px] bg-ink grid place-items-center">
                  <i className="w-[10px] h-[10px] rounded-full bg-gradient-to-br from-violet to-pink block" />
                </span>
                Relay
              </span>
              <span className="px-3 py-[9px] rounded-[10px] bg-ink text-white font-medium">Overview</span>
              <span className="px-3 py-[9px] rounded-[10px]">Providers</span>
              <span className="px-3 py-[9px] rounded-[10px]">Models</span>
              <span className="px-3 py-[9px] rounded-[10px]">API keys</span>
              <span className="px-3 py-[9px] rounded-[10px]">Requests</span>
              <span className="px-3 py-[9px] rounded-[10px]">Settings</span>
            </aside>

            {/* Embedded main dashboard */}
            <div className="p-7">
              {/* KPIs */}
              <div className="grid grid-cols-4 gap-7 pb-[26px] border-b border-line-landing max-app:grid-cols-2">
                <div>
                  <span className="block text-[12.5px] text-mute">Requests</span>
                  <b className="font-display font-light text-[34px] tracking-kpi text-ink">48,210</b>
                  <br />
                  <em className="not-italic text-[12.5px] text-violet">+12% this week</em>
                </div>
                <div>
                  <span className="block text-[12.5px] text-mute">Success rate</span>
                  <b className="font-display font-light text-[34px] tracking-kpi text-ink">99.8%</b>
                  <br />
                  <em className="not-italic text-[12.5px] text-violet">93 failovers</em>
                </div>
                <div>
                  <span className="block text-[12.5px] text-mute">Median latency</span>
                  <b className="font-display font-light text-[34px] tracking-kpi text-ink">412 ms</b>
                  <br />
                  <em className="not-italic text-[12.5px] text-violet">−38 ms</em>
                </div>
                <div>
                  <span className="block text-[12.5px] text-mute">Tokens</span>
                  <b className="font-display font-light text-[34px] tracking-kpi text-ink">21.4M</b>
                  <br />
                  <em className="not-italic text-[12.5px] text-violet">All free tier</em>
                </div>
              </div>

              {/* Grid 2: Requests per hour & Share by provider */}
              <div className="grid grid-cols-[1.2fr_1fr] gap-7 mt-[26px] max-app:grid-cols-1">
                <div>
                  <h4 className="font-medium text-[15px] mb-[2px]">Requests per hour</h4>
                  <small className="text-mute text-[12.5px]">Pink marks hours with rate-limit events</small>
                  <div className="flex items-end gap-[7px] h-[140px] mt-[18px]">
                    {HOURLY_BARS.map((height, i) => {
                      const isPink = PINK_HOURS.includes(i);
                      return (
                        <i
                          key={i}
                          className="flex-1 rounded-[6px_6px_2px_2px]"
                          style={{
                            height: `${height}%`,
                            background: isPink
                              ? 'linear-gradient(to top, #FF66E0, #FFB3EE)'
                              : 'linear-gradient(to top, #5B3DFF, #9A86FF)',
                          }}
                        />
                      );
                    })}
                  </div>
                </div>

                <div>
                  <h4 className="font-medium text-[15px] mb-[2px]">Share by provider</h4>
                  <small className="text-mute text-[12.5px]">Last 7 days</small>
                  <div className="grid gap-[14px] mt-4">
                    {[
                      { name: 'Groq', pct: 38 },
                      { name: 'Gemini', pct: 29 },
                      { name: 'Cerebras', pct: 21 },
                      { name: 'OpenRouter', pct: 12 },
                    ].map((p) => (
                      <div key={p.name} className="grid grid-cols-[90px_1fr_46px] gap-3 items-center text-[13.5px]">
                        <span>{p.name}</span>
                        <span className="h-[6px] rounded-[9px] bg-ink/[0.08] overflow-hidden block">
                          <i
                            className="block h-full rounded-[9px] bg-violet"
                            style={{ width: `${p.pct}%` }}
                          />
                        </span>
                        <span>{p.pct}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Recent Requests Table */}
              <div className="overflow-x-auto mt-[26px]">
                <table className="w-full border-collapse text-[13.5px]">
                  <thead>
                    <tr>
                      <th className="text-left font-medium text-mute py-[10px] border-b border-line-landing">Time</th>
                      <th className="text-left font-medium text-mute py-[10px] border-b border-line-landing">Key</th>
                      <th className="text-left font-medium text-mute py-[10px] border-b border-line-landing">Served by</th>
                      <th className="text-left font-medium text-mute py-[10px] border-b border-line-landing">Status</th>
                      <th className="text-left font-medium text-mute py-[10px] border-b border-line-landing">Why</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td className="py-[13px] border-b border-line-landing">14:02:11</td>
                      <td className="py-[13px] border-b border-line-landing">support-bot</td>
                      <td className="py-[13px] border-b border-line-landing">Groq Llama</td>
                      <td className="py-[13px] border-b border-line-landing text-violet font-medium">Success</td>
                      <td className="py-[13px] border-b border-line-landing text-mute">Gemini Flash paused by 429, resets in 38 s</td>
                    </tr>
                    <tr>
                      <td className="py-[13px] border-b border-line-landing">14:02:04</td>
                      <td className="py-[13px] border-b border-line-landing">research-agent</td>
                      <td className="py-[13px] border-b border-line-landing">Gemini Flash</td>
                      <td className="py-[13px] border-b border-line-landing text-violet font-medium">Success</td>
                      <td className="py-[13px] border-b border-line-landing text-mute">Largest context window available</td>
                    </tr>
                    <tr>
                      <td className="py-[13px] border-b border-line-landing">14:01:58</td>
                      <td className="py-[13px] border-b border-line-landing">support-bot</td>
                      <td className="py-[13px] border-b border-line-landing">Cerebras Llama</td>
                      <td className="py-[13px] border-b border-line-landing text-violet font-medium">Success</td>
                      <td className="py-[13px] border-b border-line-landing text-mute">Lowest latency in the last 10 minutes</td>
                    </tr>
                    <tr>
                      <td className="py-[13px] border-b border-line-landing">14:01:40</td>
                      <td className="py-[13px] border-b border-line-landing">notebook</td>
                      <td className="py-[13px] border-b border-line-landing">—</td>
                      <td className="py-[13px] border-b border-line-landing text-[#C2269C] font-medium">Rejected</td>
                      <td className="py-[13px] border-b border-line-landing text-mute">Model needs image input, key allows text only</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </section>

        {/* Security Section */}
        <section id="security" className="pt-[120px] max-app:pt-16">
          <div className="grid grid-cols-2 gap-[72px] max-app:grid-cols-1 max-app:gap-10">
            <div>
              <h2 className="font-display font-light text-[clamp(34px,4.6vw,56px)] leading-headline tracking-headline max-w-[15ch]">
                Your keys stay yours.
              </h2>
              <p className="text-mute text-[16px] leading-[1.6] max-w-[46ch] mt-[22px]">
                Provider credentials are encrypted and isolated per user. Relay respects each
                provider’s terms and never rotates accounts to get around limits.
              </p>
            </div>
            <ul className="list-none p-0 grid border-t border-line-landing">
              {[
                ['Provider keys', 'Encrypted at rest'],
                ['Relay API keys', 'Stored as hashes'],
                ['Credentials in logs', 'Never written'],
                ['Sensitive actions', 'Recorded in an audit log'],
                ['Each API key', 'Own limits, models and expiry'],
              ].map(([k, v]) => (
                <li
                  key={k}
                  className="py-[18px] border-b border-line-landing flex justify-between gap-5"
                >
                  <span className="font-medium text-ink">{k}</span>
                  <span className="text-mute text-right text-[14.5px]">{v}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* CTA Banner */}
        <div
          className="mt-[120px] rounded-[28px] p-[80px_56px] text-white max-app:p-[48px_28px] shadow-2xl"
          style={{
            background: 'radial-gradient(70% 120% at 100% 100%, #FF66E0, transparent 60%), #5B3DFF',
          }}
        >
          <h2 className="font-display font-light text-[clamp(34px,4.6vw,56px)] leading-headline max-w-[12ch]">
            Connect once. Build on everything.
          </h2>
          <div className="mt-9">
            <Link
              to="/login"
              className="inline-flex items-center gap-[10px] px-5 py-[11px] rounded-pill font-medium text-[14.5px] bg-pink text-ink hover:opacity-90 transition-opacity"
            >
              Sign in with Google
            </Link>
          </div>
        </div>

        {/* Footer */}
        <footer className="flex justify-between py-10 text-mute text-[14px] flex-wrap gap-4">
          <span>&copy; 2026 Relay</span>
          <span>Docs &middot; Status &middot; Privacy</span>
        </footer>
      </div>
    </div>
  );
};
