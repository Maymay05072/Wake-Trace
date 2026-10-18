import { useEffect, useState } from "react";

const errorLabels = {
  "WAKETRACE_API_KEY is not configured": "尚未配置模型密钥",
  "provider_request_timeout": "模型请求超时",
  "provider_connection_error": "无法连接模型服务",
  "provider returned an invalid response": "模型服务返回格式不兼容",
  "provider returned an invalid tool call": "模型返回的工具调用格式不正确",
  "incomplete tool-call response": "工具调用输出未完整结束",
  "missing final response": "模型没有返回完整的最终回复",
  "final_response_is_not_json": "模型最终回复不是要求的 JSON",
  "final_response_is_not_object": "模型最终回复不是 JSON 对象",
  "invalid_outcome": "模型返回了未知的醒来结局",
  "message_without_share": "模型选择联系，但没有提供消息正文",
  "silent_with_share": "模型同时返回静默与待发送消息，格式冲突",
  "invalid_next_wake": "模型返回的下次时间格式不正确",
  "invalid_min_minutes": "模型返回的最短间隔格式不正确",
  "invalid_max_minutes": "模型返回的最长间隔格式不正确",
  "tool_round_limit": "工具调用达到本次轮数上限",
  "missing_final_response": "工具调用后缺少最终回复",
  "external_wake_aborted": "外部客户端取消了这次醒来",
  "authentication_failed": "鉴权失败，请检查服务令牌",
  "timeout": "外部工具服务响应超时",
  "connection_error": "无法连接外部工具服务",
  "configuration_or_discovery_error": "外部工具配置或发现异常",
  "transport_error": "外部工具连接异常",
  "other_error": "其他错误，请结合服务日志排查",
};
const outcomeLabels = { silent: "静默", trace: "留痕", message: "联系" };
const mcpStates = { pending: "等待首次发现", ready: "最近连接成功", partial: "部分工具未找到", unavailable: "最近连接失败" };

function errorText(code) {
  if (!code) return "未记录具体错误";
  if (errorLabels[code]) return errorLabels[code];
  if (/^provider returned HTTP \d{3}$/.test(code)) return `模型服务返回 HTTP ${code.slice(-3)}`;
  if (/^http_\d{3}$/.test(code)) return `外部工具服务返回 HTTP ${code.slice(-3)}`;
  return "其他错误，请结合服务日志排查";
}

function timestamp(value, timezone) {
  if (!value) return "暂无记录";
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
      hour12: false, timeZone: timezone,
    }).format(new Date(value));
  } catch { return "时间不可用"; }
}

export function RuntimePage({ settings }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [copied, setCopied] = useState(false);
  const configured = Boolean(settings.apiBase && settings.token);

  useEffect(() => {
    setData(null); setCopied(false); setError("");
    if (!configured) { setLoading(false); return undefined; }
    let cancelled = false;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    setLoading(true);
    fetch(`${settings.apiBase.trim().replace(/\/$/, "")}/world/diagnostics`, {
      headers: { Authorization: `Bearer ${settings.token}` }, signal: controller.signal,
    }).then(async (response) => {
      if (!response.ok) {
        const messages = {
          401: "令牌无效，请到设置检查只读 Web 令牌。",
          403: "当前令牌没有查看权限。",
          404: "该后端尚不支持运行状态，请更新后端。",
          503: "后端未配置访问令牌，请检查服务配置。",
        };
        const failure = new Error("diagnostics request failed");
        failure.safeMessage = messages[response.status] || "暂时无法读取运行状态，请稍后刷新。";
        throw failure;
      }
      const result = await response.json();
      if (!result.scheduler || !result.model || !result.intervals || !result.notifications || !Array.isArray(result.cycles) || !Array.isArray(result.external_mcp)) {
        const failure = new Error("invalid diagnostics response");
        failure.safeMessage = "后端返回的诊断格式不兼容，请确认前后端版本。";
        throw failure;
      }
      if (!cancelled) setData(result);
    }).catch((cause) => {
      if (!cancelled) setError(cause.name === "AbortError" ? "读取超时，请检查连接后刷新。" : (
        cause.safeMessage || "无法读取后端状态，请检查网络、WakeTrace 地址与后端版本。"
      ));
    }).finally(() => {
      clearTimeout(timeout);
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; clearTimeout(timeout); controller.abort(); };
  }, [configured, settings.apiBase, settings.token, refresh]);

  const copyDiagnostics = async () => {
    try { await navigator.clipboard.writeText(JSON.stringify(data, null, 2)); setCopied(true); }
    catch { setCopied(false); document.getElementById("diagnostic-export")?.focus(); }
  };

  return <section className="simple-page runtime-page">
    <header className="page-heading runtime-heading"><div><h1>运行状态</h1><p>查看醒来节律、失败记录与接入情况。</p></div>
      <button type="button" className="secondary-button" disabled={!configured || loading}
        onClick={() => setRefresh((value) => value + 1)}>{loading ? "读取中…" : "刷新状态"}</button>
    </header>
    {!configured && <p className="runtime-notice">请先在设置中填写 WakeTrace 地址和只读 Web 令牌。</p>}
    {error && <p className="runtime-notice runtime-error" role="alert">{error}</p>}
    {loading && <p role="status" className="muted">正在读取后端状态…</p>}
    {data && <>
      <p className="runtime-updated">更新于 {timestamp(data.checked_at, data.timezone)} · 后端时区 {data.timezone} · 手动刷新</p>
      <div className="runtime-cards">
        <article><span>最近一次成功醒来</span><strong>{timestamp(data.last_success_at, data.timezone)}</strong><small>静默、留痕和联系均计为成功</small></article>
        <article><span>下次计划时间</span><strong>{data.next_wake_at ? timestamp(data.next_wake_at, data.timezone) : "尚未排定"}</strong><small>实际执行仍受间隔、每日上限与服务运行影响</small></article>
      </div>
      <section className="runtime-section"><h2>调度与节律</h2>
        <p className="runtime-status-line"><i className={data.scheduler.running_in_this_process ? "runtime-ok" : "runtime-neutral"} aria-hidden="true" />
          {data.scheduler.running_in_this_process ? "本进程调度器运行中" : data.scheduler.enabled ? "本进程未运行调度器" : "内置调度已关闭"}</p>
        {!data.scheduler.running_in_this_process && <p className="muted">若使用独立调度进程或外部客户端，请确认对应入口正在运行。</p>}
        {data.scheduler.last_poll_at && <p className="muted">最近一次调度检查：{timestamp(data.scheduler.last_poll_at, data.timezone)}。执行醒来期间此时间可能暂不更新。</p>}
        <dl className="runtime-facts">
          <div><dt>日间间隔</dt><dd>{data.intervals.minimum_minutes}–{data.intervals.maximum_minutes} 分钟</dd></div>
          <div><dt>夜间最短间隔</dt><dd>{data.intervals.night_minimum_minutes} 分钟</dd></div>
          <div><dt>每日成功醒来上限</dt><dd>{data.intervals.daily_limit} 次</dd></div>
          <div><dt>通知静默时段</dt><dd>{data.intervals.quiet_start === data.intervals.quiet_end ? "未启用" : `${data.intervals.quiet_start}:00 至 ${data.intervals.quiet_end}:00`}</dd></div>
        </dl>
      </section>
      <section className="runtime-section"><h2>配置检查</h2>
        <div className="runtime-check"><strong>唤醒模型</strong><span className={data.model.configuration_complete ? "runtime-ok-text" : "runtime-error-text"}>
          {data.model.configuration_complete ? "基础配置已填写" : "基础配置不完整"}</span>
          <p>密钥{data.model.key_configured ? "已填写" : "未填写"} · 模型名{data.model.name_configured ? "已填写" : "未填写"} · 接口地址{data.model.endpoint_configured ? "已填写" : "未正确填写"}。此项不会调用模型，连通性请结合醒来记录判断。</p></div>
        <div className="runtime-check"><strong>通知渠道</strong><span>{data.notifications.kind === "webpush" ? "Web Push" : data.notifications.kind === "console" ? "终端输出" : "自定义通知器"}</span>
          <p>{data.notifications.kind === "webpush" ? `推送私钥${data.notifications.key_configured ? "已配置" : "未配置"}，当前有 ${data.notifications.subscriptions} 个订阅；不代表已验证送达。` : "送达情况请查看对应渠道和服务日志。"}</p></div>
        <h3 className="runtime-subheading">外部 MCP</h3>
        {!data.external_mcp?.length ? <p className="muted">未配置外部 MCP；内置线头与作品工具仍可使用。</p> : data.external_mcp.map((server) =>
          <div className="runtime-check" key={server.name}><strong>{server.name}</strong><span>{mcpStates[server.state] || "状态未知"}</span>
            <p>{server.transport === "sse" ? "SSE" : "Streamable HTTP"} · 允许 {server.allowed_count} 个工具 · 已发现 {server.tool_count} 个
              {server.missing_count > 0 && ` · 未找到 ${server.missing_count} 个`}</p>
            {server.error_code && <p className="runtime-error-text">{errorText(server.error_code)}</p>}
            {server.checked_at && <small>最近检查：{timestamp(server.checked_at, data.timezone)}</small>}
          </div>)}
        <p className="muted">工具在唤醒时连接和发现。本页只读取最近状态，不触发工具、模型或推送。</p>
      </section>
      <section className="runtime-section"><h2>最近执行记录</h2><p className="muted">包含失败记录。失败不属于主动静默；尚未结束的记录也可能来自服务中断。</p>
        {!data.cycles.length ? <p className="runtime-notice">还没有唤醒执行记录。</p> : <ol className="runtime-cycles">{data.cycles.map((cycle) =>
          <li key={cycle.id}><div className="runtime-cycle-heading"><strong>#{cycle.id} · {cycle.status === "completed" ? outcomeLabels[cycle.outcome] || "已完成" : cycle.status === "failed" ? "执行失败" : cycle.status === "running" ? "尚未结束" : "状态未知"}</strong>
            <time>{timestamp(cycle.started_at, data.timezone)}</time></div>
            {cycle.status === "failed" && <p className="runtime-error-text">{errorText(cycle.error_code)}</p>}
            {cycle.status === "running" && <p className="muted">可能正在执行，也可能被重启或断线中断，请结合调度状态与日志检查。</p>}
          </li>)}</ol>}
      </section>
      <section className="runtime-section"><h2>遇到问题时</h2>
        <details><summary>一直静默</summary><p>先确认记录是“静默”还是“执行失败”。静默表示成功返回了 silent；再查看完整行径中的醒来缘由、真实工具记录，以及聊天是否通过“交回生活”显式交接。连接 MCP 不会强制活动或发消息。</p></details>
        <details><summary>没有收到消息</summary><p>静默和私人留痕本来就不发送消息。选择联系后，还会检查通知静默时段、重复内容及真实渠道能否送达；未送达会保留为留痕。新记录的具体原因可在行径详情的“通知状态”中查看；旧记录可能没有保存原因。</p></details>
        <details><summary>醒来次数少</summary><p>先核对日间、夜间间隔、后端时区与每日上限，再看服务是否连续运行以及是否有失败。页面的行径数量不等于所有尝试次数。</p></details>
        <details><summary>没有调用外部工具</summary><p>确认后端已配置工具服务，且允许列表中的原始工具名称确实存在。Kelivo 中的工具不会自动同步；工具已连接也不代表模型每次都必须使用。</p></details>
      </section>
      <section className="runtime-section"><h2>提供诊断信息</h2><p className="muted">以下信息不含密钥、接口地址、聊天、醒来正文或工具结果。</p>
        <button type="button" className="secondary-button" onClick={copyDiagnostics}>{copied ? "已复制" : "复制诊断信息"}</button>
        <details><summary>展开并手动复制</summary><textarea id="diagnostic-export" aria-label="诊断信息" readOnly value={JSON.stringify(data, null, 2)} onFocus={(event) => event.target.select()} /></details>
      </section>
    </>}
  </section>;
}
