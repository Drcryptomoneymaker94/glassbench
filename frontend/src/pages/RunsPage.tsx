import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Meta, type Run, type SearchResult, type VibeSession } from "../api";
import { RunDots } from "../components/CommitteeBoard";
import { DownloadIcon, PlusIcon } from "../components/Icons";
import { EMPTY_FILTERS, RATINGS, RunFilters, applyFilters, engineName, modelLabel, versionLabel, versionTitle, type Filters } from "../components/RunFilters";
import { fmtClock, fmtDate, fmtDuration, fmtPrice, fmtUsd, ratingColor } from "../format";

const ANALYST_NAMES: Record<string, string> = { market: "Market", social: "Sentiment", news: "News", fundamentals: "Fundamentals" };
const AGENT_NAMES: Record<string, string> = {
  market: "Market", sentiment: "Sentiment", news: "News", fundamentals: "Fundamentals", bull: "Bull", bear: "Bear",
  research_manager: "Research Mgr", trader: "Trader", aggressive: "Aggressive", conservative: "Conservative", neutral: "Neutral", portfolio_manager: "Portfolio Mgr",
  buffett: "Buffett", munger: "Munger", graham: "Graham", lynch: "Lynch", druckenmiller: "Druckenmiller", pead: "Earnings drift",
  blend: "Blend", risk: "Risk limits", execution: "Execution",
};

const KIND: Record<string, string> = { "report.updated": "report", "llm.reasoning": "reasoning", "tool.result": "tool result", "tool.called": "tool call", "data.flag": "flag", "decision.structured": "decision", "run.failed": "error" };

type SortKey = "created" | "ticker" | "trade_date" | "rating" | "duration" | "cost" | "flags";
type FrameworkView = "all" | "tradingagents" | "ai_hedge_fund" | "vibe_trading";
type Engine = Exclude<FrameworkView, "all">;
const FRAMEWORK_VIEWS: { id: FrameworkView; label: string }[] = [
  { id: "all", label: "All" },
  { id: "tradingagents", label: "TradingAgents" },
  { id: "ai_hedge_fund", label: "AI Hedge Fund" },
  { id: "vibe_trading", label: "Vibe-Trading" },
];
/** Entry, stop, target and horizon: the trader and portfolio manager on TradingAgents, the closing block on Vibe-Trading. */
const levelsOf = (r: Run): { entry?: number; stop?: number; target?: number; horizon?: string } => {
  const d: Record<string, any> | undefined = r.decision ?? undefined;
  if (r.engine === "vibe_trading") return { entry: d?.entry ?? undefined, stop: d?.stop ?? undefined, target: d?.target ?? undefined, horizon: d?.horizon ?? undefined };
  return { entry: d?.trader?.entry_price ?? undefined, stop: d?.trader?.stop_loss ?? undefined, target: d?.portfolio?.price_target ?? undefined, horizon: d?.portfolio?.time_horizon ?? undefined };
};
const engineOf = (r: Run): Engine => (r.engine === "ai_hedge_fund" || r.engine === "vibe_trading" ? r.engine : "tradingagents");
const duration = (r: Run) => (r.started_at ? (r.finished_at ?? Date.now() / 1000) - r.started_at : -1);
const SORTERS: Record<SortKey, (r: Run) => number | string> = {
  created: (r) => r.created_at,
  ticker: (r) => r.ticker,
  trade_date: (r) => r.trade_date,
  rating: (r) => (r.rating ? RATINGS.indexOf(r.rating) : 99),
  duration,
  cost: (r) => r.cost_usd,
  flags: (r) => r.flags,
};

function Snippet({ text }: { text: string }) {
  // Matches come marked as [[ ]] from the search index; render them as highlights.
  const parts = text.split(/\[\[|\]\]/);
  return (
    <span>
      {parts.map((part, i) => (i % 2 === 1 ? <mark key={i}>{part}</mark> : <span key={i}>{part}</span>))}
    </span>
  );
}

export default function RunsPage({ meta }: { meta: Meta }) {
  const [runs, setRuns] = useState<Run[]>();
  const [error, setError] = useState<string>();
  const [dialog, setDialog] = useState(false);
  const [importing, setImporting] = useState(false);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [search, setSearch] = useState<SearchResult>();
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "created", dir: -1 });
  // Opens on All every time; the switch only narrows the list while you are on the page.
  const [framework, setFramework] = useState<FrameworkView>("all");
  const navigate = useNavigate();

  const load = useCallback(() => api.runs().then(setRuns).catch((e) => setError(String(e.message || e))), []);
  useEffect(() => {
    load();
  }, [load]);
  const anyLive = runs?.some((r) => r.status === "running" || r.status === "queued");
  useEffect(() => {
    if (!anyLive) return;
    const t = window.setInterval(load, 3000);
    return () => window.clearInterval(t);
  }, [anyLive, load]);

  const searchIds = useMemo(() => (search ? new Set(search.runs.map((r) => r.run_id)) : undefined), [search]);
  const snippets = useMemo(() => new Map(search?.runs.map((r) => [r.run_id, r]) ?? []), [search]);

  const counts = useMemo(() => {
    const c = { all: runs?.length ?? 0, tradingagents: 0, ai_hedge_fund: 0, vibe_trading: 0 };
    for (const r of runs ?? []) c[engineOf(r)] += 1;
    return c;
  }, [runs]);
  const inFramework = useMemo(
    () => (runs ?? []).filter((r) => framework === "all" || engineOf(r) === framework),
    [runs, framework],
  );

  const shown = useMemo(() => {
    if (!runs) return [];
    const get = SORTERS[sort.key];
    return applyFilters(inFramework, filters, searchIds).sort((a, b) => {
      const va = get(a);
      const vb = get(b);
      return (va < vb ? -1 : va > vb ? 1 : 0) * sort.dir;
    });
  }, [runs, inFramework, filters, searchIds, sort]);

  const sortable = (label: string, key: SortKey, right = false) => (
    <th className={right ? "r" : undefined} aria-sort={sort.key === key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
      <button
        className="th-sort"
        onClick={() => setSort((s) => ({ key, dir: s.key === key ? ((-s.dir) as 1 | -1) : key === "ticker" ? 1 : -1 }))}
      >
        {label}
        <span className="sort-mark">{sort.key === key ? (sort.dir === 1 ? "↑" : "↓") : ""}</span>
      </button>
    </th>
  );

  return (
    <>
      <header className="page-head">
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <h1>Runs</h1>
          <span className="subtitle">The record of every analysis: framework, models, decision, cost and the full log. Open one to replay it step by step.</span>
        </div>
        <a className="btn" href="/api/runs.csv">
          <DownloadIcon /> Export CSV
        </a>
      </header>

      {runs && runs.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span className="label" style={{ margin: 0 }}>Framework</span>
          <div className="seg" role="group" aria-label="Show runs from">
            {FRAMEWORK_VIEWS.map((f) => (
              <button key={f.id} className={framework === f.id ? "on" : ""} aria-pressed={framework === f.id} onClick={() => setFramework(f.id)}>
                {f.label} <span className="muted" style={{ marginLeft: 4 }}>{counts[f.id]}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {runs && runs.length > 0 && <RunFilters runs={inFramework} filters={filters} onChange={setFilters} search={search} onSearch={setSearch} shown={shown} />}

      <div className="cta-bar">
        <div>
          <b>{framework === "ai_hedge_fund" ? "Run the fund on a ticker" : framework === "vibe_trading" ? "Run the research agent on a ticker" : "Run the agents on a ticker"}</b>
          <span className="muted">
            {framework === "ai_hedge_fund"
              ? "Pick a strategy and a date; each analyst scores the stock, the strategy blends, a simulated broker fills. Every call is logged."
              : framework === "vibe_trading"
              ? "Vibe-Trading's investment committee or one research agent, read-only tools, closing on a rating. Sessions from its own app can be imported."
              : "Pick stocks, a date and the analysts; watch the twelve agents work and keep the full log."}
          </span>
        </div>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, flexShrink: 0 }}>
          {framework === "vibe_trading" && meta.engines?.vibe_trading?.installed && (
            <button className="btn btn-lg" onClick={() => setImporting(true)}>Import from Vibe-Trading</button>
          )}
          <button className="btn btn-primary btn-lg" onClick={() => setDialog(true)}>
            <PlusIcon /> New run
          </button>
        </div>
      </div>

      <section className="panel">
        {error && <div className="panel-pad error">{error}</div>}
        {runs && runs.length === 0 && (
          <div className="panel-pad">
            <div className="empty">No runs yet. Start one to watch the twelve agents work through a ticker.</div>
          </div>
        )}
        {runs && runs.length > 0 && shown.length === 0 && (
          <div className="panel-pad">
            <div className="empty">{search ? "No run's log contains that text." : "No runs match these filters."}</div>
          </div>
        )}
        {shown.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Status</th>
                  {sortable("Ticker", "ticker")}
                  {sortable("Trade date", "trade_date")}
                  <th>Framework</th>
                  <th>Models</th>
                  {sortable("Rating", "rating")}
                  <th className="r">Entry</th>
                  <th className="r">Stop</th>
                  <th className="r">Target</th>
                  <th>Horizon</th>
                  {sortable("Cost est.", "cost", true)}
                  {sortable("Flags", "flags", true)}
                  {sortable("Started", "created")}
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => {
                  const lv = levelsOf(r);
                  const dash = <span className="muted">—</span>;
                  const hit = snippets.get(r.id);
                  const open = () => navigate(`/runs/${r.id}`);
                  return [
                    <tr key={r.id} onClick={open}>
                      <td>
                        <StatusCell status={r.status} />
                        {r.progress && r.progress.order.length > 0 && <RunDots progress={r.progress.state} order={r.progress.order} />}
                      </td>
                      <td style={{ fontWeight: 700 }}>
                        {r.ticker}
                        {r.purpose === "backtest" && <span className="tag-bt" title={`Backtest run · memory ${r.memory ?? "off"}`}>BT</span>}
                        {r.purpose === "imported" && <span className="tag-variant" title="Run in Vibe-Trading's own app and imported: its own prompt, tools and date, not a controlled Glassbench run">imported</span>}
                        {r.data_source === "yahoo" && <span className="tag-variant" title="Free Yahoo Finance and SEC EDGAR data through Glassbench's adapter, not native to AI Hedge Fund">free data</span>}
                      </td>
                      <td className="num">{r.trade_date}</td>
                      <td title={versionTitle(r.engine_version, r.engine)}>
                        {engineName(r)}
                        <span className="muted mono" style={{ fontSize: 10.5, marginLeft: 6 }}>{versionLabel(r.engine_version)}</span>
                      </td>
                      <td className="mono" style={{ fontSize: 11.5, color: "var(--ink-2)" }}>{r.quick_model === r.deep_model ? modelLabel(r.quick_model) : `${modelLabel(r.quick_model)} · ${modelLabel(r.deep_model)}`}</td>
                      <td className="rating" style={{ color: ratingColor(r.rating) }}>{r.rating ?? dash}</td>
                      <td className="r">{lv.entry != null ? fmtPrice(lv.entry) : dash}</td>
                      <td className="r">{lv.stop != null ? fmtPrice(lv.stop) : dash}</td>
                      <td className="r">{lv.target != null ? fmtPrice(lv.target) : dash}</td>
                      <td className="clip" title={lv.horizon ?? undefined} style={{ color: "var(--ink-2)" }}>{lv.horizon ?? dash}</td>
                      <td className="r">{fmtUsd(r.cost_usd)}</td>
                      <td className="r" style={{ color: r.flags ? "var(--warn)" : "var(--muted)" }}>{r.flags}</td>
                      <td className="muted" title={`${fmtDate(r.created_at)} ${fmtClock(r.created_at, false)} · ${r.started_at ? fmtDuration(duration(r)) : "not started"}`}>{fmtDate(r.created_at)}</td>
                    </tr>,
                    hit && (
                      <tr key={`${r.id}-hits`} className="snippet-row" onClick={open}>
                        <td colSpan={13}>
                          {hit.snippets.map((s) => (
                            <div className="snippet" key={s.seq}>
                              <span className="who">{s.agent ? AGENT_NAMES[s.agent] ?? s.agent : "Engine"} · {KIND[s.type] ?? s.type}</span>
                              <Snippet text={s.snippet} />
                            </div>
                          ))}
                          {hit.hits > hit.snippets.length && <div className="muted" style={{ fontSize: 11.5, paddingLeft: 170 }}>and {hit.hits - hit.snippets.length} more in this run</div>}
                        </td>
                      </tr>
                    ),
                  ];
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {importing && (
        <VibeImportDialog
          onClose={() => setImporting(false)}
          onImported={(id) => {
            setImporting(false);
            navigate(`/runs/${id}`);
          }}
        />
      )}

      {dialog && (
        <NewRunDialog
          meta={meta}
          initialEngine={framework !== "all" && framework !== "tradingagents" && meta.engines?.[framework]?.installed ? framework : "tradingagents"}
          onClose={() => setDialog(false)}
          onStarted={(ids) => {
            setDialog(false);
            if (ids.length === 1) navigate(`/runs/${ids[0]}`);
            else load();
          }}
        />
      )}
    </>
  );
}

/** Sessions found in Vibe-Trading's own home folder; importing one adds it to the database as an imported run. */
function VibeImportDialog({ onClose, onImported }: { onClose: () => void; onImported: (id: string) => void }) {
  const [list, setList] = useState<{ home: string; exists: boolean; sessions: VibeSession[] }>();
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    api.vibeSessions().then(setList).catch((e) => setError(String(e.message || e)));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const importOne = async (s: VibeSession) => {
    setBusy(s.key);
    setError(undefined);
    try {
      onImported((await api.vibeImport(s.kind, s.id)).run_id);
    } catch (e: any) {
      setError(String(e.message || e));
      setBusy(undefined);
    }
  };
  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="vt-import-title">
        <h2 id="vt-import-title">Import from Vibe-Trading</h2>
        <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
          Sessions and swarm runs you ran in Vibe-Trading's own app, read from {list?.home ?? "its home folder"}. Imported runs keep their own prompt, tools and date; they are tagged as imported and are not controlled Glassbench runs.
        </p>
        {!list && !error && <p className="muted">Reading…</p>}
        {list && !list.exists && <p className="muted">No Vibe-Trading home folder found. Set GLASSBENCH_VT_HOME if it is not in the default place.</p>}
        {list?.exists && list.sessions.length === 0 && <p className="muted">No sessions yet.</p>}
        {list && list.sessions.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 360, overflowY: "auto" }}>
            {list.sessions.map((s) => (
              <div key={s.key} style={{ display: "flex", gap: 10, alignItems: "center", justifyContent: "space-between", fontSize: 12.5 }}>
                <div style={{ minWidth: 0 }}>
                  <div className="clip">{s.prompt || s.id}</div>
                  <span className="muted mono" style={{ fontSize: 11 }}>
                    {s.kind === "swarm" ? "swarm" : "session"} · {fmtDate(s.started)} {fmtClock(s.started, false)}
                    {s.tool_calls != null ? ` · ${s.tool_calls} tools` : ""}{s.answered ? "" : " · no answer"}
                  </span>
                </div>
                {s.imported_run ? (
                  <button className="btn" onClick={() => onImported(s.imported_run!)}>Open</button>
                ) : (
                  <button className="btn" disabled={!!busy} onClick={() => importOne(s)}>{busy === s.key ? "Importing…" : "Import"}</button>
                )}
              </div>
            ))}
          </div>
        )}
        {error && <div className="error">{error}</div>}
        <div className="dialog-foot">
          <span />
          <button className="btn btn-ghost" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

export function StatusCell({ status }: { status: Run["status"] }) {
  const map = {
    running: ["var(--accent)", "Running", true],
    queued: ["var(--muted)", "Queued", false],
    finished: ["var(--good)", "Finished", false],
    failed: ["var(--bad)", "Failed", false],
    cancelled: ["var(--muted)", "Cancelled", false],
  } as const;
  const [color, label, pulse] = map[status];
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
      <span className={`dot${pulse ? " live" : ""}`} style={{ background: color }} />
      {label}
    </span>
  );
}

function NewRunDialog({ meta, onClose, onStarted, initialEngine = "tradingagents" }: { meta: Meta; onClose: () => void; onStarted: (ids: string[]) => void; initialEngine?: Engine }) {
  const [tickers, setTickers] = useState("NVDA");
  const [date, setDate] = useState(meta.default_trade_date);
  const [analysts, setAnalysts] = useState<string[]>(meta.analysts);
  const [depth, setDepth] = useState(1);
  const providers = meta.providers ?? [{ id: "deepseek", label: "DeepSeek", key: "DEEPSEEK_API_KEY", present: true, quick: meta.models.quick, deep: meta.models.deep }];
  const [provider, setProvider] = useState(providers[0].id);
  const prov = providers.find((p) => p.id === provider) ?? providers[0];
  const [quick, setQuick] = useState(prov.quick[0] ?? "");
  const [deep, setDeep] = useState(prov.deep[0] ?? "");
  const pickProvider = (id: string) => {
    const p = providers.find((x) => x.id === id) ?? providers[0];
    setProvider(p.id);
    setQuick(p.quick[0] ?? "");
    setDeep(p.deep[0] ?? "");
  };
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const aihf = meta.engines?.ai_hedge_fund;
  const [engine, setEngine] = useState<Engine>(initialEngine);
  const vt = meta.engines?.vibe_trading;
  const [vtProvider, setVtProvider] = useState<string>(vt?.providers?.[0] ?? "ollama");
  const [vtModel, setVtModel] = useState("");
  const [vtMode, setVtMode] = useState<"committee" | "single">("committee");
  const vtProv = providers.find((p) => p.id === vtProvider);
  const vtBlocked = !vt?.installed
    ? "Vibe-Trading is not installed: clone it next to Glassbench (./Vibe-Trading) with its own .venv"
    : vtProv?.key && !vtProv.present
    ? `${vtProv.key} is not loaded.`
    : !vtModel.trim()
    ? "Type the model id your server serves."
    : undefined;
  const isVt = engine === "vibe_trading";
  const [strategy, setStrategy] = useState<string>(aihf?.strategies?.[0]?.name ?? "custom");
  const [aihfAnalysts, setAihfAnalysts] = useState<string[]>(aihf?.analysts?.filter((a) => a.kind === "llm").map((a) => a.name) ?? []);
  const [aihfModel, setAihfModel] = useState<string>(aihf?.default_model ?? "deepseek-flash");
  const aihfModelMeta = aihf?.models?.find((m) => m.model_name === aihfModel);
  const aihfLabel = (name: string) => aihf?.analysts?.find((a) => a.name === name)?.label ?? name;
  const dataSources = aihf?.data_sources ?? [{ id: "financial-datasets", label: "Financial Datasets", native: true, note: "", key: "FINANCIAL_DATASETS_API_KEY", present: !!aihf?.data_key?.present }];
  // Native data when its key is loaded; without it, the free route is the one that can run.
  const [dataSource, setDataSource] = useState<string>(aihf?.data_key?.present || !aihf?.data_sources ? "financial-datasets" : "yahoo");
  const dataMeta = dataSources.find((s) => s.id === dataSource) ?? dataSources[0];
  const aihfBlocked = !aihf?.installed
    ? aihf?.error ?? "AI Hedge Fund is not installed"
    : dataMeta.key && !dataMeta.present
    ? "FINANCIAL_DATASETS_API_KEY is not loaded. AI Hedge Fund reads prices and fundamentals from financialdatasets.ai (the key is free, the data needs prepaid credits): put it in .env at the repository root and restart Glassbench, or pick the free Yahoo Finance data."
    : aihfModelMeta && !aihfModelMeta.present
    ? `${aihfModelMeta.key} is not loaded for ${aihfModelMeta.display_name}.`
    : strategy === "custom" && !aihfAnalysts.length
    ? "Pick at least one analyst."
    : undefined;
  const isAihf = engine === "ai_hedge_fund";

  const list = tickers.split(/[\s,;]+/).map((t) => t.trim().toUpperCase()).filter(Boolean);
  const pastDate = date < meta.default_trade_date;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submit = async () => {
    setBusy(true);
    setError(undefined);
    try {
      const res = isVt
        ? await api.start({ tickers: list, trade_date: date, analysts: meta.analysts, depth: 1, quick_model: vtModel.trim(), deep_model: vtModel.trim(), provider: vtProvider, engine, vt_mode: vtMode })
        : isAihf
        ? await api.start({
            tickers: list, trade_date: date, analysts: meta.analysts, depth: 1, quick_model: "deepseek-v4-flash", deep_model: "deepseek-v4-pro", provider: "deepseek",
            engine, strategy: strategy === "custom" ? null : strategy, aihf_analysts: strategy === "custom" ? aihfAnalysts : null, aihf_model: aihfModel, aihf_data: dataSource,
          })
        : await api.start({ tickers: list, trade_date: date, analysts, depth, quick_model: quick.trim(), deep_model: deep.trim(), provider });
      onStarted(res.run_ids);
    } catch (e: any) {
      setError(String(e.message || e));
      setBusy(false);
    }
  };

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="new-run-title">
        <h2 id="new-run-title">New run</h2>
        <div className="field">
          <span className="label">Framework</span>
          <div className="seg">
            <button className={engine === "tradingagents" ? "on" : ""} onClick={() => setEngine("tradingagents")}>TradingAgents</button>
            <button className={isAihf ? "on" : ""} disabled={!aihf?.installed} title={aihf?.installed ? `AI Hedge Fund ${aihf.version ?? ""}` : aihf?.error} onClick={() => setEngine("ai_hedge_fund")}>AI Hedge Fund</button>
            <button className={isVt ? "on" : ""} disabled={!vt?.installed} title={vt?.installed ? `Vibe-Trading ${vt.version ?? ""}` : "Vibe-Trading is not installed"} onClick={() => setEngine("vibe_trading")}>Vibe-Trading</button>
          </div>
        </div>
        <div className="row2">
          <div className="field">
            <label htmlFor="tickers">Tickers</label>
            <input id="tickers" className="input" value={tickers} onChange={(e) => setTickers(e.target.value)} autoFocus placeholder="NVDA, AAPL" />
            <span className="hint">{list.length > 1 ? `${list.length} runs, two at a time` : "Separate several with commas"}</span>
          </div>
          <div className="field">
            <label htmlFor="trade-date">Analysis date</label>
            <input id="trade-date" className="input" type="date" value={date} max={meta.default_trade_date} onChange={(e) => setDate(e.target.value)} />
            <span className="hint" style={{ color: pastDate && !isAihf ? "var(--warn)" : undefined }}>
              {isAihf ? "Filled at the next completed close; a recent date may come back pending" : isVt ? "Vibe-Trading has no date input: its news and web tools return today's items" : pastDate ? "Past dates get an empty news feed" : "Today gives the fullest news and profile data"}
            </span>
          </div>
        </div>
        {isAihf ? (
          <>
            <div className="row2">
              <div className="field" style={{ minWidth: 0 }}>
                <label htmlFor="aihf-strategy">Strategy</label>
                <select id="aihf-strategy" className="select" style={{ width: "100%", minWidth: 0 }} value={strategy} onChange={(e) => setStrategy(e.target.value)}>
                  {aihf?.strategies?.map((s) => (
                    <option key={s.name} value={s.name}>
                      {s.display_name} · {s.models.map((m) => `${aihfLabel(m.name)}${m.weight !== 1 ? ` x${m.weight}` : ""}`).join(", ")}
                    </option>
                  ))}
                  <option value="custom">Custom · pick the analysts</option>
                </select>
                <span className="hint">{strategy === "custom" ? "Equal blend weights; long and short when any analyst may short" : `Blend mode ${aihf?.strategies?.find((s) => s.name === strategy)?.mode.replace("_", " ") ?? ""}`}</span>
              </div>
              <div className="field" style={{ minWidth: 0 }}>
                <label htmlFor="aihf-model">Model</label>
                <select id="aihf-model" className="select" style={{ width: "100%", minWidth: 0 }} value={aihfModel} onChange={(e) => setAihfModel(e.target.value)}>
                  {aihf?.models?.map((m) => <option key={m.model_name} value={m.model_name}>{m.display_name}{m.present ? "" : " (no key)"}</option>)}
                </select>
                <span className="hint">Every LLM analyst runs on it; the earnings drift model uses no LLM</span>
              </div>
            </div>
            <div className="field">
              <span className="label">Data</span>
              <div className="seg" role="radiogroup" aria-label="Data source">
                {dataSources.map((s) => (
                  <button key={s.id} role="radio" aria-checked={dataSource === s.id} className={dataSource === s.id ? "on" : ""} title={s.note} onClick={() => setDataSource(s.id)}>
                    {s.label}
                    <small>{s.native ? "native" : "not native"}</small>
                  </button>
                ))}
              </div>
              {dataMeta.native ? (
                <span className="hint">AI Hedge Fund's own data client, as released: prepaid credits at financialdatasets.ai, cached so nothing is paid twice</span>
              ) : (
                <div className="bt-note" role="note">
                  <b>Not native to AI Hedge Fund.</b> Glassbench rebuilds the numbers itself: prices and earnings dates from Yahoo Finance, statements from SEC EDGAR filings, each dated by the day it was filed. Free, no key, but results might not be ideal and can differ from a Financial Datasets run.
                </div>
              )}
            </div>
            {strategy === "custom" && (
              <div className="field">
                <span className="label">Analysts</span>
                <div className="checks">
                  {aihf?.analysts?.map((a) => {
                    const on = aihfAnalysts.includes(a.name);
                    return (
                      <button key={a.name} className={`check${on ? " on" : ""}`} aria-pressed={on} title={a.what}
                        onClick={() => setAihfAnalysts((cur) => (on ? cur.filter((x) => x !== a.name) : (aihf?.analysts ?? []).map((x) => x.name).filter((x) => x === a.name || cur.includes(x))))}>
                        {a.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
            <p className="muted" style={{ fontSize: 11.5, margin: 0 }}>
              One cycle per stock: each analyst scores it, the strategy blends the convictions, risk limits apply and a simulated broker fills at the next close. Glassbench maps the blended conviction to a rating so both frameworks share one table.
            </p>
            {aihfBlocked && <div className="error">{aihfBlocked}</div>}
          </>
        ) : isVt ? (
          <>
            <div className="field">
              <span className="label">Mode</span>
              <div className="seg" role="radiogroup" aria-label="Vibe-Trading mode">
                <button role="radio" aria-checked={vtMode === "committee"} className={vtMode === "committee" ? "on" : ""} onClick={() => setVtMode("committee")}>
                  Investment committee<small>Vibe-Trading's own preset</small>
                </button>
                <button role="radio" aria-checked={vtMode === "single"} className={vtMode === "single" ? "on" : ""} onClick={() => setVtMode("single")}>
                  One research agent<small>Glassbench's prompt</small>
                </button>
              </div>
            </div>
            <div className="row2">
              <div className="field">
                <label htmlFor="vt-provider">Provider</label>
                <select id="vt-provider" className="select" value={vtProvider} onChange={(e) => setVtProvider(e.target.value)}>
                  {(vt?.providers ?? ["ollama"]).map((id) => {
                    const p = providers.find((x) => x.id === id);
                    return <option key={id} value={id}>{p?.label ?? id}{p?.key && !p.present ? " (no key)" : ""}</option>;
                  })}
                </select>
              </div>
              <div className="field">
                <label htmlFor="vt-model">Model</label>
                <input id="vt-model" className="input" value={vtModel} onChange={(e) => setVtModel(e.target.value)} placeholder={vtProvider === "ollama" ? "the id your local server serves" : "deepseek-v4-flash"} />
              </div>
            </div>
            <p className="muted" style={{ fontSize: 11.5, margin: 0 }}>
              {vtMode === "committee"
                ? "Vibe-Trading's investment committee with its own prompts: bull and bear researchers in parallel, then the chief risk officer, then the portfolio manager. "
                : "One Vibe-Trading research agent on Glassbench's prompt. "}
              Read-only data tools and its shell-free maths tool only: no shell, no file access, no backtests, no broker tools. The portfolio manager's answer ends in a JSON block that Glassbench maps to the shared rating table.
            </p>
            {vtBlocked && <div className="error">{vtBlocked}</div>}
          </>
        ) : (
          <>
        <div className="field">
          <span className="label">Analysts</span>
          <div className="checks">
            {meta.analysts.map((a) => {
              const on = analysts.includes(a);
              return (
                <button
                  key={a}
                  className={`check${on ? " on" : ""}`}
                  aria-pressed={on}
                  onClick={() => setAnalysts((cur) => (on ? cur.filter((x) => x !== a) : meta.analysts.filter((x) => x === a || cur.includes(x))))}
                >
                  {ANALYST_NAMES[a] ?? a}
                </button>
              );
            })}
          </div>
          <span className="hint">Bull, Bear, Research manager, Trader, the risk team and Portfolio manager always run.</span>
        </div>
        <div className="row2">
          <div className="field">
            <span className="label">Debate rounds</span>
            <div className="seg">
              {[1, 2, 3].map((d) => (
                <button key={d} className={depth === d ? "on" : ""} onClick={() => setDepth(d)}>{d}</button>
              ))}
            </div>
          </div>
          <div className="field">
            <label htmlFor="provider">Provider</label>
            <select id="provider" className="select" value={provider} onChange={(e) => pickProvider(e.target.value)}>
              {providers.map((p) => <option key={p.id} value={p.id}>{p.label}{p.key && !p.present ? " (no key)" : ""}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="quick-model">Models · quick / deep</label>
            <div style={{ display: "flex", gap: 8 }}>
              <input id="quick-model" className="input" list="quick-model-ids" value={quick} onChange={(e) => setQuick(e.target.value)} placeholder="quick model id" style={{ flex: 1, minWidth: 0 }} />
              <datalist id="quick-model-ids">{prov.quick.map((m) => <option key={m} value={m} />)}</datalist>
              <input id="deep-model" className="input" list="deep-model-ids" aria-label="Deep model" value={deep} onChange={(e) => setDeep(e.target.value)} placeholder="deep model id" style={{ flex: 1, minWidth: 0 }} />
              <datalist id="deep-model-ids">{prov.deep.map((m) => <option key={m} value={m} />)}</datalist>
            </div>
            <p className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>Any model id your provider serves. The quick model reads and debates, the deep model is called by the two managers.</p>
          </div>
        </div>
          </>
        )}
        {error && <div className="error">{error}</div>}
        <div className="dialog-foot">
          <span className="muted" style={{ fontSize: 12 }}>
            {isVt ? `Vibe-Trading ${vt?.version ?? ""} · ${vtMode === "committee" ? "investment committee" : "one agent"} · ${vtProv?.label ?? vtProvider} · research only · no orders are placed` : isAihf ? `AI Hedge Fund ${aihf?.version ?? ""} · ${dataMeta.native ? dataMeta.label : `${dataMeta.label}, not native`} · simulated broker · no orders are placed` : `${prov.label}${prov.key && !prov.present ? ` · ${prov.key} not loaded` : ""} · paper only · no orders are placed`}
          </span>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button className="btn btn-primary" disabled={busy || !list.length || (isVt ? !!vtBlocked : isAihf ? !!aihfBlocked : !analysts.length || !quick.trim() || !deep.trim() || (!!prov.key && !prov.present))} onClick={submit}>
              {busy ? "Starting…" : list.length > 1 ? `Start ${list.length} runs` : "Start run"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
