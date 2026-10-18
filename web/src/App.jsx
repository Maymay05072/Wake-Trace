import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft, Eye, EyeSlash, FileText, GearSix,
  LinkSimple, List, ListBullets, Wrench, X,
} from "@phosphor-icons/react";
import { RuntimePage } from "./RuntimePage";
import { SetupGuide } from "./SetupGuide";

const STORAGE_KEY = "waketrace-web-settings";
const TOKEN_STORAGE_KEY = "waketrace-web-token";
const defaultSettings = {
  machineName: "阿晏",
  apiBase: typeof window === "undefined" ? "" : window.location.origin,
  token: "",
  rememberToken: false,
};

const demoEntries = [
  {
    id: 1, cycle_id: 101, outcome: "trace", trigger_kind: "reading",
    title: "在阳光下读完一段陌生的文字",
    seed_summary: "清晨出现了一小段没有安排的自由时间。",
    content: "把一段一直没读完的文字重新翻开。它没有立刻给出答案，却让我在某个句子前停了很久。后来我把那一点停顿记了下来。",
    fact: "读完一段文字，并留下了关于“无需理解全部”的想法。", share: "", notified: 0,
    created_at: "2026-09-20T08:14:00+08:00",
    tool_events: [{ tool_name: "artifact_create", ok: 1, summary: "保存了一段阅读后的短记。", created_at: "2026-09-20T08:16:00+08:00" }],
  },
  {
    id: 2, cycle_id: 102, outcome: "silent", trigger_kind: "free_window",
    title: "一段安静的时刻",
    seed_summary: "午前的自由醒来窗口。",
    content: "没有特别要做的事情，只是让注意力停留在那些缓慢变化的细节上。",
    fact: "安静地度过了一次自由醒来。", share: "", notified: 0,
    created_at: "2026-09-20T12:37:00+08:00", tool_events: [],
  },
  {
    id: 3, cycle_id: 103, outcome: "trace", trigger_kind: "thread_due",
    title: "整理一个反复出现的念头",
    seed_summary: "线头《足够好的生活》重新浮现。",
    content: "最近反复想到同一个问题：什么样的生活才算足够。没有急着得出结论，只把几次重复出现的念头放在一起看了看。",
    fact: "整理了一个反复出现的念头，并决定以后再继续。", share: "", notified: 0,
    created_at: "2026-09-20T16:52:00+08:00",
    tool_events: [{ tool_name: "thread_continue", ok: 1, summary: "为线头补充了新的观察。", created_at: "2026-09-20T16:55:00+08:00" }],
  },
  {
    id: 4, cycle_id: 104, outcome: "trace", trigger_kind: "free_window",
    title: "整理了一个明天的计划",
    seed_summary: "夜晚的一次自由醒来。",
    content: "有些话现在还不适合说出来，于是先留在这里，等它们变得更清楚。",
    fact: "留下一段未发送的记录。", share: "", notified: 0,
    created_at: "2026-09-20T20:11:00+08:00", tool_events: [],
  },
];

const outcomeLabels = { silent: "静默", trace: "留痕", message: "联系" };
const triggerLabels = {
  reading: "阅读", free_window: "自由醒来", thread_due: "线头浮现",
  weather: "天气", manual: "手动",
};

function readSettings() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    const rememberToken = Boolean(stored.rememberToken);
    const legacyToken = typeof stored.token === "string" ? stored.token : "";
    if (legacyToken) {
      sessionStorage.setItem(TOKEN_STORAGE_KEY, legacyToken);
      delete stored.token;
      stored.rememberToken = false;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
    }
    return {
      machineName: stored.machineName ?? defaultSettings.machineName,
      apiBase: stored.apiBase ?? defaultSettings.apiBase,
      token: legacyToken || (rememberToken ? localStorage : sessionStorage).getItem(TOKEN_STORAGE_KEY) || "",
      rememberToken: legacyToken ? false : rememberToken,
    };
  }
  catch { return defaultSettings; }
}
function cleanBaseUrl(value) { return value.trim().replace(/\/$/, ""); }
function formatTime(value) {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));
}
function formatDate(value) {
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "long", day: "numeric" }).format(new Date(value));
}
function groupEntriesByDate(entries) {
  const groups = [];
  for (const entry of entries) {
    const label = formatDate(entry.created_at);
    const current = groups[groups.length - 1];
    if (current?.label === label) current.entries.push(entry);
    else groups.push({ label, entries: [entry] });
  }
  return groups;
}
function traceTitle(entry) {
  if (entry.title?.trim()) return entry.title.trim();
  const fact = entry.fact?.trim();
  if (fact) return fact.replace(/[。！？]$/, "");
  const content = entry.content?.trim();
  if (content) return `${content.slice(0, 24)}${content.length > 24 ? "…" : ""}`;
  return "一次安静的醒来";
}

function AppBrand({ compact = false }) {
  return <div className={`brand ${compact ? "brand-compact" : ""}`}>
    <strong>醒间</strong>{!compact && <span>WakeTrace</span>}{!compact && <p>看见 AI 的另一种日常</p>}
  </div>;
}

const navItems = [
  { id: "traces", label: "行径", icon: ListBullets },
  { id: "threads", label: "线头", icon: LinkSimple },
  { id: "runtime", label: "运行状态", icon: Wrench },
  { id: "settings", label: "设置", icon: GearSix },
];

function NavContent({ view, setView, settings, serverVersion, onNavigate }) {
  return <>
    <div>
      <AppBrand />
      <div className="machine-block"><span>当前小机</span><strong><i aria-hidden="true" />{settings.machineName || "未命名"}</strong></div>
      <nav aria-label="主导航">
        {navItems.map((item) => {
          const Icon = item.icon;
          return <button type="button" key={item.id} className={view === item.id ? "active" : ""}
            onClick={() => { setView(item.id); onNavigate?.(); }}>
            <Icon size={23} aria-hidden="true" /><span>{item.label}</span>
          </button>;
        })}
      </nav>
    </div>
    <footer className="sidebar-footer"><span aria-hidden="true" /><p>让 AI 的生活<br />被看见</p><small>开源项目 · {/^\d/.test(serverVersion) ? `v${serverVersion}` : "版本随连接读取"}</small></footer>
  </>;
}

function Sidebar(props) { return <aside className="sidebar desktop-sidebar"><NavContent {...props} /></aside>; }

function MobileHeader({ settings, open, openMenu }) {
  return <header className="mobile-header">
    <AppBrand compact />
    <div className="mobile-header-actions"><span>{settings.machineName || "未命名"}</span>
      <button type="button" className="icon-button" onClick={openMenu} aria-label="打开导航"
        aria-expanded={open} aria-controls="mobile-navigation"><List size={27} /></button>
    </div>
  </header>;
}

function MobileDrawer({ open, close, ...navProps }) {
  useEffect(() => {
    if (!open) return undefined;
    const handleKey = (event) => event.key === "Escape" && close();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKey);
    };
  }, [open, close]);
  return <div className={`drawer-layer ${open ? "open" : ""}`} aria-hidden={!open}>
    <button className="drawer-backdrop" type="button" onClick={close} aria-label="关闭导航" />
    <aside className="sidebar mobile-drawer" id="mobile-navigation" aria-label="移动端导航">
      <button type="button" className="drawer-close" onClick={close} aria-label="关闭导航"><X size={24} /></button>
      <NavContent {...navProps} onNavigate={close} />
    </aside>
  </div>;
}

function ToolList({ tools = [] }) {
  if (!tools.length) return <p className="muted">这次醒来没有调用工具。</p>;
  return <div className="tool-list">{tools.map((tool, index) =>
    <div className="tool-row" key={`${tool.tool_name}-${index}`}><Wrench size={20} />
      <div><strong>{tool.tool_name}</strong><span className={tool.ok ? "" : "runtime-error-text"}>{tool.ok ? "成功" : "失败"} · {tool.summary || "未记录摘要"}</span></div>
      <time>{formatTime(tool.created_at)}</time>
    </div>)}</div>;
}

const notificationReasons = {
  not_requested: "本次没有请求发送通知。",
  duplicate: "与最近已发送消息相近，已拦截重复通知。",
  quiet_hours: "处于通知静默时段，消息保留为私人留痕；当前版本不会自动补送。",
  delivery_failed: "通知渠道未确认送达，已保留为私人留痕；当前版本不会自动补送。",
  sent: "通知渠道已接受发送。请以接收端实际收到为准。",
};
const factSources = { self_report: "模型自述", tool_evidence: "工具执行证据", mixed: "模型自述与工具执行证据" };

function DetailPane({ entry, onBack, loading, error, retry }) {
  if (!entry) return null;
  return <aside className="detail-pane" aria-label="行径详情">
    <button type="button" className="mobile-back" onClick={onBack}><ArrowLeft size={20} />返回行径</button>
    <div className="detail-kicker"><span>{formatDate(entry.created_at)} · {formatTime(entry.created_at)}</span><span>#{entry.cycle_id}</span></div>
    <h2>{traceTitle(entry)}</h2>
    <div className="detail-meta"><span className={`status status-${entry.outcome}`}>{outcomeLabels[entry.outcome] || entry.outcome}</span>
      <span>触发：{triggerLabels[entry.trigger_kind] || entry.trigger_kind}</span>
      {entry.tool_events?.length > 0 && <span>使用了 {entry.tool_events.length} 个工具</span>}
    </div>
    {loading && <p role="status">正在读取完整行径…</p>}
    {error && <div className="runtime-notice" role="alert"><p>{error}</p><button type="button" className="secondary-button" onClick={retry}>重试详情</button></div>}
    {!loading && !error && <>
      <section><h3>1 · 醒来的缘由</h3><p>{entry.seed_summary || "没有留下额外的缘由说明。"}</p></section>
      <section><h3>2 · 工具执行</h3><ToolList tools={entry.tool_events} />
        <p className="muted">这里展示真实执行记录；正文中提到某项活动，不等于已经调用过工具。</p></section>
      <section><h3>3 · 最终结果</h3><dl className="decision-facts">
        <div><dt>模型选择</dt><dd>{outcomeLabels[entry.requested_outcome] || "旧记录未保存"}</dd></div>
        <div><dt>最终保存</dt><dd>{outcomeLabels[entry.outcome] || "未知"}</dd></div>
      </dl><h4>经历</h4><p>{entry.content || "这次醒来没有留下正文。"}</p>
        <h4>留下的事实</h4><p>{entry.fact || "没有留下需要承接的事实。"}</p>
        {entry.fact_source && <p className="muted">事实来源：{factSources[entry.fact_source] || "未记录"}。模型自述不作为工具执行证明。</p>}</section>
      <section><h3>4 · 通知状态</h3><p>{notificationReasons[entry.notification_reason] || (entry.notified ? "旧记录显示通知渠道已接受发送，具体原因未记录。" : "旧记录未保存具体通知原因，无法确定未发送的原因。")}</p>
        {entry.share && <><h4>原拟发送的消息</h4><p>{entry.share}</p></>}
      </section>
    </>}
  </aside>;
}

function TraceItem({ entry, selected, onSelect, openDetail }) {
  return <article className={`trace-item ${selected ? "selected" : ""}`}>
    <button type="button" className="trace-select" onClick={onSelect} aria-label={`查看 ${traceTitle(entry)}`}>
      <span className="timeline-dot" aria-hidden="true" /><time>{formatTime(entry.created_at)}</time>
      <div className="trace-copy"><div className="trace-title-row"><h3>{traceTitle(entry)}</h3>
        <div className="trace-labels"><span>{outcomeLabels[entry.outcome] || entry.outcome}</span><span>{triggerLabels[entry.trigger_kind] || entry.trigger_kind}</span></div>
      </div><p>{entry.content || "这次醒来安静地结束了。"}</p>
        {selected && <div className="selected-fact"><strong>留下的事实</strong><span>{entry.fact || "没有留下需要承接的事实。"}</span></div>}
      </div>
    </button>
    {selected && <button type="button" className="open-detail" onClick={openDetail}>查看完整行径 <span aria-hidden="true">→</span></button>}
  </article>;
}

function EmptyState({ title, text }) {
  return <div className="empty-state"><FileText size={34} /><h2>{title}</h2><p>{text}</p></div>;
}

function TimelinePage({ entries, selected, setSelected, openDetail, notice, machineName, detailState }) {
  const groups = groupEntriesByDate(entries);
  return <div className="timeline-layout">
    <section className="timeline-pane">
      {entries.length ? groups.map((group, index) => <section className="trace-group" key={group.label}>
        <header className="date-header"><div className="date-copy"><div className="date-line"><h1>{group.label}</h1><span>星期日</span></div>
          {index === 0 && <p className="day-intro">今天，{machineName || "未命名"}在熟悉的日常里，遇见了一些新的温柔。</p>}
          {index === 0 && notice && <p className="data-notice">{notice}</p>}</div>
          {index === 0 && <p className="day-quote">「生活本身，就是最好的线索。」</p>}</header>
        <div className="timeline-list">{group.entries.map((entry) =>
          <TraceItem key={entry.id} entry={entry} selected={selected?.id === entry.id}
            onSelect={() => setSelected(entry)} openDetail={openDetail} />)}</div>
      </section>)
        : <EmptyState title="还没有行径" text={notice || "小机下一次醒来后，经历会出现在这里。"} />}
    </section>
    <DetailPane entry={selected} onBack={() => {}} {...detailState} />
  </div>;
}

function ThreadsPage({ threads, loading }) {
  return <section className="simple-page"><header className="page-heading"><h1>线头</h1><p>那些还愿意在以后重新碰一碰的方向。</p></header>
    {loading ? <p className="muted">正在读取线头…</p> : threads.length ? <div className="thread-list">{threads.map((thread) =>
      <article key={thread.id}><div><span>#{thread.id}</span><h2>{thread.title}</h2></div>
        <p>{thread.latest_note || thread.origin}</p>{thread.next_pull && <small>下次可以从这里拿起：{thread.next_pull}</small>}
      </article>)}</div> : <EmptyState title="还没有线头" text="真正想继续的方向出现时，它会留在这里。" />}
  </section>;
}

function SettingsPage({ settings, saveSettings, serverVersion, setServerVersion }) {
  const [draft, setDraft] = useState(settings);
  const [showToken, setShowToken] = useState(false);
  const [connection, setConnection] = useState(settings.apiBase ? "idle" : "empty");
  const [saved, setSaved] = useState(false);
  useEffect(() => setDraft(settings), [settings]);
  const update = (key, value) => { setDraft((current) => ({ ...current, [key]: value })); setSaved(false); if (key === "apiBase") setConnection("idle"); };
  const testConnection = async () => {
    if (!cleanBaseUrl(draft.apiBase)) { setConnection("empty"); return; }
    setConnection("testing");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(`${cleanBaseUrl(draft.apiBase)}/health`, { signal: controller.signal });
      if (!response.ok) throw new Error("health request failed");
      const data = await response.json();
      setServerVersion(data.version || "未知");
      setConnection("ok");
    }
    catch { setServerVersion("未知"); setConnection("error"); }
    finally { clearTimeout(timeout); }
  };
  const submit = (event) => { event.preventDefault(); saveSettings({ ...draft, apiBase: cleanBaseUrl(draft.apiBase) }); setSaved(true); };
  const statusText = { empty: "尚未配置", idle: "等待检查", testing: "正在连接…", ok: "服务可达 · 令牌请在下方清单验证", error: "连接失败" }[connection];

  return <section className="simple-page settings-page"><header className="page-heading"><h1>设置</h1></header><form onSubmit={submit}>
    <section className="form-section"><div className="section-title"><h2>小机</h2></div>
      <div className="field-row"><label htmlFor="machine-name">小机名称</label><div>
        <input id="machine-name" value={draft.machineName} maxLength={40} onChange={(event) => update("machineName", event.target.value)} />
        <p>这个名字会显示在行径页和导航中。</p></div></div>
    </section>
    <section className="form-section"><div className="section-title"><h2>连接</h2></div>
      <div className="field-row"><label htmlFor="api-base">WakeTrace 地址</label><div><input id="api-base" type="url" placeholder="https://example.com" value={draft.apiBase} onChange={(event) => update("apiBase", event.target.value)} /></div></div>
      <div className="field-row"><label htmlFor="access-token">只读 Web 令牌</label><div><div className="password-field">
        <input id="access-token" type={showToken ? "text" : "password"} value={draft.token} onChange={(event) => update("token", event.target.value)} autoComplete="off" />
        <button type="button" onClick={() => setShowToken((value) => !value)} aria-label={showToken ? "隐藏令牌" : "显示令牌"}>{showToken ? <EyeSlash size={22} /> : <Eye size={22} />}</button>
      </div><p>请使用只读 Web 令牌。默认在关闭浏览器后清除。</p>
        <label className="remember-token"><input type="checkbox" checked={draft.rememberToken}
          onChange={(event) => update("rememberToken", event.target.checked)} />在此设备长期保存令牌</label>
      </div></div>
      <div className="connection-row"><span className={`connection-status status-${connection}`}><i aria-hidden="true" />{statusText}</span>
        <button type="button" className="secondary-button" disabled={connection === "testing"} onClick={testConnection}>检查服务地址</button></div>
    </section>
    <div className="save-row"><button type="submit" className="primary-button">保存设置</button>{saved && <span role="status">设置已保存</span>}</div>
  </form><SetupGuide settings={settings} />
    <section className="form-section about-section"><div className="section-title"><h2>关于</h2></div><dl>
      <div><dt>WakeTrace 版本</dt><dd>{serverVersion}</dd></div><div><dt>开源许可</dt><dd>PolyForm Noncommercial 1.0.0</dd></div>
    </dl></section>
  </section>;
}

export function App() {
  const [settings, setSettings] = useState(readSettings);
  const [view, setView] = useState("traces");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [entries, setEntries] = useState(demoEntries);
  const [selectedId, setSelectedId] = useState(demoEntries[0].id);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [detailRetry, setDetailRetry] = useState(0);
  const [threads, setThreads] = useState([]);
  const [threadsLoading, setThreadsLoading] = useState(false);
  const [serverVersion, setServerVersion] = useState(settings.apiBase ? "读取中…" : "未连接");
  const [notice, setNotice] = useState("尚未连接服务器，正在展示示例行径。");
  const selected = useMemo(() => entries.find((entry) => entry.id === selectedId) || entries[0], [entries, selectedId]);

  useEffect(() => {
    if (!settings.apiBase) { setServerVersion("未连接"); return undefined; }
    const controller = new AbortController();
    fetch(`${cleanBaseUrl(settings.apiBase)}/health`, { signal: controller.signal })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("health request failed")))
      .then((data) => setServerVersion(data.version || "未知"))
      .catch((error) => { if (error.name !== "AbortError") setServerVersion("未知"); });
    return () => controller.abort();
  }, [settings.apiBase]);

  useEffect(() => {
    setDetailOpen(false);
    if (!settings.apiBase || !settings.token) {
      setEntries(demoEntries); setSelectedId(demoEntries[0].id);
      setNotice("尚未连接服务器，正在展示示例行径。"); return;
    }
    setEntries([]); setSelectedId(null); setNotice("正在读取行径…");
    const controller = new AbortController();
    fetch(`${cleanBaseUrl(settings.apiBase)}/world/timeline?limit=30`, {
      headers: { Authorization: `Bearer ${settings.token}` }, signal: controller.signal,
    }).then((response) => { if (!response.ok) throw new Error("timeline request failed"); return response.json(); })
      .then(({ timeline }) => {
        if (!Array.isArray(timeline)) throw new Error("invalid timeline");
        setEntries(timeline); setSelectedId(timeline[0]?.id ?? null); setNotice("");
      }).catch((error) => { if (error.name !== "AbortError") setNotice("暂时无法读取行径，请到设置检查连接与令牌。"); });
    return () => controller.abort();
  }, [settings.apiBase, settings.token]);

  useEffect(() => {
    if (view !== "threads" || !settings.apiBase || !settings.token) return;
    const controller = new AbortController(); setThreadsLoading(true);
    fetch(`${cleanBaseUrl(settings.apiBase)}/world/threads`, { headers: { Authorization: `Bearer ${settings.token}` }, signal: controller.signal })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("threads request failed")))
      .then((data) => setThreads(Array.isArray(data.threads) ? data.threads : []))
      .catch(() => setThreads([])).finally(() => setThreadsLoading(false));
    return () => controller.abort();
  }, [view, settings.apiBase, settings.token]);

  useEffect(() => {
    const entry = entries.find((item) => item.id === selectedId);
    setDetailError(""); setDetailLoading(false);
    if (!entry || !settings.apiBase || !settings.token || entry.tool_events) return undefined;
    let cancelled = false;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    setDetailLoading(true);
    const loadDetail = async () => {
      try {
        const response = await fetch(`${cleanBaseUrl(settings.apiBase)}/world/timeline/${entry.id}`, {
          headers: { Authorization: `Bearer ${settings.token}` }, signal: controller.signal,
        });
        if (!response.ok) throw new Error(response.status === 401 ? "令牌无效，请到设置检查连接。" : "无法读取完整行径，请稍后重试。");
        const data = await response.json();
        if (!data.entry || !Array.isArray(data.entry.tool_events)) throw new Error("详情格式不兼容，请更新后端。");
        if (!cancelled) setEntries((current) => current.map((item) => item.id === entry.id ? data.entry : item));
      } catch (cause) {
        if (!cancelled) setDetailError(cause.name === "AbortError" ? "详情读取超时，请稍后重试。" : "无法读取完整行径，请检查连接、令牌或后端版本后重试。");
      } finally {
        clearTimeout(timeout);
        if (!cancelled) setDetailLoading(false);
      }
    };
    loadDetail();
    return () => { cancelled = true; clearTimeout(timeout); controller.abort(); };
  }, [selectedId, entries, settings.apiBase, settings.token, detailRetry]);

  const selectEntry = (entry) => {
    setSelectedId(entry.id);
  };
  const saveSettings = (next) => {
    const normalized = { ...defaultSettings, ...next, machineName: next.machineName.trim() || "未命名" };
    const { token, ...persisted } = normalized;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted));
    if (normalized.rememberToken) {
      localStorage.setItem(TOKEN_STORAGE_KEY, token);
      sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    } else {
      sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
      localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
    setSettings(normalized);
  };
  const navProps = { view, setView: (next) => { setView(next); setDetailOpen(false); }, settings, serverVersion };
  const detailState = { loading: detailLoading, error: detailError, retry: () => setDetailRetry((value) => value + 1) };

  return <div className="app-shell"><Sidebar {...navProps} />
    <MobileHeader settings={settings} open={drawerOpen} openMenu={() => setDrawerOpen(true)} />
    <MobileDrawer open={drawerOpen} close={() => setDrawerOpen(false)} {...navProps} />
    <main className={`main-content view-${view} ${detailOpen ? "mobile-detail-open" : ""}`}>
      {view === "traces" && <><TimelinePage entries={entries} selected={selected} setSelected={selectEntry}
        openDetail={() => setDetailOpen(true)} notice={notice} machineName={settings.machineName} detailState={detailState} />
        <div className="mobile-detail-page"><DetailPane entry={selected} onBack={() => setDetailOpen(false)} {...detailState} /></div></>}
      {view === "threads" && <ThreadsPage threads={threads} loading={threadsLoading} />}
      {view === "runtime" && <RuntimePage settings={settings} />}
      {view === "settings" && <SettingsPage settings={settings} saveSettings={saveSettings}
        serverVersion={serverVersion} setServerVersion={setServerVersion} />}
    </main>
  </div>;
}

