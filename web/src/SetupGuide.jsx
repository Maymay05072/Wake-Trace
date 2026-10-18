import { useEffect, useRef, useState } from "react";

const testMessages = {
  response_received: "已收到模型的普通文本响应。工具调用和醒来协议仍需结合实际醒来记录确认。",
  channel_accepted: "通知渠道已接受测试消息，请到接收端确认。终端通知器只会输出到服务日志。",
  configuration_incomplete: "模型配置不完整，请先按清单补齐后重启服务。",
  notification_not_delivered: "未能送达，请检查通知配置、推送依赖及订阅。",
  notification_error: "通知器执行失败，请检查对应渠道配置。",
  provider_request_timeout: "模型请求超时，请检查服务连接。",
  provider_connection_error: "无法连接模型服务。",
  "provider returned an invalid response": "模型响应格式不兼容。",
  "missing final response": "没有收到完整文本响应；请检查模型兼容性或输出限制。",
};

function failureMessage(status) {
  return {
    401: "令牌无效或权限不足；查看清单用 Web 令牌，执行测试需管理员令牌。",
    403: "当前令牌没有所需权限。",
    404: "后端尚不支持此功能，请更新后端。",
    429: "同类测试每分钟限一次，请稍后手动重试。",
    503: "后端尚未配置相应访问令牌。",
  }[status] || "请求失败，请检查网络和后端状态。";
}

function SetupStep({ number, title, status, children }) {
  return <article className="setup-step"><header><span className="setup-number">{number}</span>
    <h3>{title}</h3><span className="setup-status">{status}</span></header><div>{children}</div></article>;
}

export function SetupGuide({ settings }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [adminToken, setAdminToken] = useState("");
  const [testing, setTesting] = useState("");
  const [result, setResult] = useState(null);
  const testController = useRef(null);
  const configured = Boolean(settings.apiBase && settings.token);
  const base = settings.apiBase.trim().replace(/\/$/, "");

  useEffect(() => {
    let cancelled = false;
    setData(null); setError(""); setResult(null); setAdminToken(""); setTesting("");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    setLoading(configured);
    if (configured) fetch(`${base}/world/setup`, {
      headers: { Authorization: `Bearer ${settings.token}` }, signal: controller.signal,
    }).then(async (response) => {
      if (!response.ok) throw Object.assign(new Error("request failed"), { safeMessage: failureMessage(response.status) });
      const payload = await response.json();
      if (!payload.model || !payload.identity || !payload.notifications || !Array.isArray(payload.external_mcp)) {
        throw Object.assign(new Error("invalid checklist"), { safeMessage: "配置清单格式不兼容，请确认前后端版本。" });
      }
      if (!cancelled) setData(payload);
    }).catch((cause) => {
      if (!cancelled) setError(cause.name === "AbortError" ? "读取超时，请稍后刷新清单。" : cause.safeMessage || "无法读取清单，请检查地址、网络和后端版本。");
    }).finally(() => {
      clearTimeout(timeout);
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; clearTimeout(timeout); controller.abort(); };
  }, [configured, base, settings.token, refresh]);

  useEffect(() => () => { testController.current?.abort(); testController.current = null; }, [base, settings.token]);

  const runTest = async (target) => {
    if (!adminToken.trim() || testController.current) return;
    const controller = new AbortController();
    testController.current = controller;
    setTesting(target); setResult(null);
    const token = adminToken.trim();
    setAdminToken("");
    const timeout = setTimeout(() => controller.abort(), 45000);
    try {
      const response = await fetch(`${base}/admin/tests/${target}`, {
        method: "POST", headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal, redirect: "error",
      });
      if (!response.ok) throw Object.assign(new Error("request failed"), { safeMessage: failureMessage(response.status) });
      const payload = await response.json();
      const text = testMessages[payload.code] || (/^provider returned HTTP [1-5][0-9]{2}$/.test(payload.code) ? `模型服务返回 HTTP ${payload.code.slice(-3)}。` : "测试未通过，请结合服务配置排查。");
      if (testController.current === controller) setResult({ ok: payload.ok === true, text });
    } catch (cause) {
      if (testController.current === controller) setResult({ ok: false, text: cause.name === "AbortError" ? "请求超时，后台可能仍在执行。先检查接收端或日志，再手动重试。" : cause.safeMessage || "测试请求未完成，请检查连接。" });
    } finally {
      clearTimeout(timeout);
      if (testController.current === controller) { testController.current = null; setTesting(""); }
    }
  };

  const notifications = data?.notifications;
  const pushReady = notifications?.kind === "webpush" && notifications.key_configured && notifications.dependency_installed && notifications.subscriptions > 0;

  return <section className="setup-guide" aria-label="首次配置引导">
    <header className="setup-heading"><div><h2>首次配置引导</h2><p>先保存上方连接，再检查后端配置。这里只查看配置，不会自动调用模型或发通知。</p></div>
      <button type="button" className="secondary-button" disabled={!configured || loading || Boolean(testing)} onClick={() => setRefresh((value) => value + 1)}>{loading ? "读取中…" : "刷新清单"}</button></header>
    {!configured && <p className="runtime-notice">请先填写并保存 WakeTrace 地址和只读 Web 令牌。</p>}
    {error && <p className="runtime-notice runtime-error" role="alert">{error}</p>}
    {data && <>
      <div className="setup-steps">
        <SetupStep number="1" title="唤醒模型" status={data.model.configuration_complete ? "基础配置已填写" : "需要补充"}>
          <p>接口地址：{data.model.endpoint_configured ? "已填写" : "未正确填写"} · 模型名：{data.model.name_configured ? "已填写" : "未填写"} · 密钥：{data.model.key_configured ? "已填写" : "未填写"}</p>
          <p>在服务器环境变量或 .env 中设置以下项目，修改后重启服务。密钥不会显示在网页里。</p>
          <code>WAKETRACE_API_BASE_URL<br />WAKETRACE_MODEL<br />WAKETRACE_API_KEY</code>
        </SetupStep>
        <SetupStep number="2" title="名称与时区" status={data.identity.using_default_names ? "正在使用默认名称" : "已设置"}>
          <p>后端小机名称：{data.identity.companion_name} · 用户名称：{data.identity.user_name}<br />后端时区：{data.timezone}</p>
          <p>上方“小机名称”只控制网页显示。唤醒提示与通知使用后端名称；请按自己的所在地核对时区。</p>
          <code>WAKETRACE_COMPANION_NAME<br />WAKETRACE_USER_NAME<br />WAKETRACE_TIMEZONE=Asia/Shanghai</code>
        </SetupStep>
        <SetupStep number="3" title="通知渠道" status={notifications.kind === "webpush" ? pushReady ? "可手动测试" : "尚未就绪 · 可选" : "可手动测试"}>
          {notifications.kind === "webpush" ? <><p>Web Push 私钥：{notifications.key_configured ? "已配置" : "未配置"} · 推送依赖：{notifications.dependency_installed ? "已安装" : "未安装"} · 订阅：{notifications.subscriptions} 个</p>
            <p>设置 WAKETRACE_VAPID_PRIVATE_KEY、WAKETRACE_VAPID_CLAIMS_EMAIL；Python 部署安装 .[webpush]。订阅需由接收通知的宿主 PWA 创建并提交，本网页不会自动创建订阅。</p></> : <p>{notifications.kind === "console" ? "终端输出：通知会出现在服务日志中。" : "自定义通知器：请按你选择的渠道完成配置。"}</p>}
          <p>不使用推送也能保留和查看行径。配置完成不代表已经送达。</p>
        </SetupStep>
        <SetupStep number="4" title="外部 MCP" status={data.external_mcp.length ? "已配置 · 可选" : "未配置 · 可选"}>
          <p>不接外部工具也能使用内置线头与作品工具。客户端中的工具需要在唤醒后端单独接入。</p>
          <code>WAKETRACE_EXTERNAL_MCP_CONFIG</code>
          {data.external_mcp.map((server) => <p key={server.name}>{server.name}：{({ pending: "等待首次唤醒发现", ready: "最近连接成功", partial: "部分允许工具未找到", unavailable: "最近连接失败" })[server.state] || "状态未知"}</p>)}
          <p>此处不会连接外部服务；完整配置示例见仓库 README 的“接入外部 MCP 工具”。</p>
        </SetupStep>
      </div>
      <section className="setup-tests"><h3>手动验证连接</h3>
        <p>测试模型会发送一次短请求，消耗少量 API 额度；测试通知会向已配置渠道发送一条明确标注的测试消息。两者均不会生成行径或更改醒来计划。</p>
        <label htmlFor="test-admin-token">管理员令牌 · 仅本次测试</label>
        <input id="test-admin-token" type="password" value={adminToken} autoComplete="off" spellCheck={false} disabled={Boolean(testing) || !data.admin_tests_available}
          onChange={(event) => setAdminToken(event.target.value)} placeholder="WAKETRACE_ADMIN_TOKEN" />
        <p>令牌不会写入浏览器存储，点击测试后立即清空；只读 Web 令牌没有测试权限。同类测试每分钟限一次。</p>
        {!data.admin_tests_available && <p className="runtime-error-text">请先在后端设置 WAKETRACE_ADMIN_TOKEN 并重启服务。</p>}
        <div className="setup-test-actions">
          <button type="button" className="secondary-button" disabled={!adminToken.trim() || Boolean(testing) || !data.model.configuration_complete} onClick={() => runTest("model")}>{testing === "model" ? "正在测试模型…" : "测试模型 · 少量 API 额度"}</button>
          <button type="button" className="secondary-button" disabled={!adminToken.trim() || Boolean(testing) || (notifications.kind === "webpush" && !pushReady)} onClick={() => runTest("notification")}>{testing === "notification" ? "正在发送…" : "发送测试通知"}</button>
        </div>
        {result && <p role="status" className={result.ok ? "runtime-ok-text" : "runtime-error-text"}>{result.text}</p>}
      </section>
    </>}
  </section>;
}
