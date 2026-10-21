"use strict";
// Render peer-provided strings as text, never executable markup.
const $ = id => document.getElementById(id);
const labels = {unknown:"未知",working:"开发中",waiting:"等待中",needs_input:"需要决定",ready_for_review:"待验收",finished:"已报完成",paused:"已暂停",active:"忙碌",idle:"空闲",notLoaded:"未载入",systemError:"宿主异常",inProgress:"进行中",completed:"成功完成",interrupted:"本轮中断",failed:"失败",leased:"已获占用",running:"执行中",suspect:"占用过期·待核查",observed_only:"仅观察·未接入",self_reported:"已主动上报",passed:"通过",not_run:"未测",pending:"待处理",build:"构建",runtime:"运行",test:"测试",asset:"资产"};
let snapshot = null, selected = null, busy = false, lastError = "";
const token = new URLSearchParams(location.hash.slice(1)).get("key") || "";
function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; }
function label(value) { return labels[value] || value || "未知"; }
function noticeLabel(value) { return {pending:"待代发",sending:"发送中·待回执",delivered:"投递受理·未确认已读",failed:"明确未发送",uncertain:"结果不明·勿重发"}[value] || "未知"; }
function time(value) { return value == null ? "没有记录" : new Date(value * 1000).toLocaleString("zh-CN", {hour12:false}); }
function age(value) { if (value == null) return "未上报"; const s=Math.max(0,Math.floor(Date.now()/1000-value)); return s<60 ? `${s} 秒前` : s<3600 ? `${Math.floor(s/60)} 分钟前` : `${Math.floor(s/3600)} 小时前`; }
function badge(text, tone="") { return el("span",`badge ${tone}`,text); }
function needsAttention(chat) { return !chat.work_fresh || !chat.host_fresh || ["needs_input","ready_for_review"].includes(chat.work_state) || chat.host_state==="systemError" || chat.turn_state==="failed" || chat.blockers.length>0; }
function tone(state) { return ["failed","systemError","suspect"].includes(state) ? "danger" : ["waiting","needs_input","ready_for_review"].includes(state) ? "warn" : ["working","running","finished"].includes(state) ? "good" : ""; }
function notice(text) { $("notice").textContent=text; $("notice").hidden=!text; }
function pair(list, name, value) { list.append(el("dt","",name),el("dd","",value || "未提供")); }
function section(root,title) { root.append(el("h4","",title)); const d=el("dl");root.append(d);return d; }
function choose(type,id) { selected={type,id};render(); }
function relevant() {
  const key=$("project").value;
  const chats=(snapshot.chats||[]).filter(c=>!key||c.project_key===key);
  const owners=new Set(chats.map(c=>c.chat_id));
  return {chats,queue:(snapshot.queue||[]).filter(q=>!key||owners.has(q.owner)),notices:(snapshot.release_notices||[]).filter(n=>!key||n.project_key===key)};
}
function renderChat(c) {
  const card=el("button","chat-card");card.type="button";card.setAttribute("aria-pressed",String(selected?.type==="chat"&&selected.id===c.chat_id));card.onclick=()=>choose("chat",c.chat_id);
  const top=el("div","card-top");top.append(el("strong","",c.label),badge(c.work_fresh?label(c.work_state):"开发状态过期",c.work_fresh?tone(c.work_state):"warn"));card.append(top,el("p","summary",c.summary||"尚未提供开发摘要。"));
  const host=el("div","card-meta");host.append(el("span","",`原生对话：${label(c.host_state)}${c.host_fresh?"":" · 过期／未知"}`),el("span","",age(c.host_observed)));card.append(host);
  const meta=el("div","card-meta");meta.append(el("span","",label(c.adoption)),el("span","",c.client_version?`客户端 ${c.client_version}`:"版本未知"));card.append(meta);
  card.append(el("div","card-next",c.blockers.length?`阻塞：${c.blockers.join("；")}`:`下一步：${c.next_step||"尚未上报"}`));return card;
}
function renderQueue(q) {
  const row=el("button","queue-row");row.type="button";row.setAttribute("aria-pressed",String(selected?.type==="request"&&selected.id===q.id));row.onclick=()=>choose("request",q.id);
  const owner=(snapshot.chats||[]).find(c=>c.chat_id===q.owner)?.label||q.owner;
  const main=el("div");main.append(el("strong","",q.purpose));
  const reason=q.dependency_blockers?.length?`等待 ${q.dependency_blockers.length} 项前置成功`:q.resource_blocker_details?.length?`资源被 ${q.resource_blocker_details.map(b=>(snapshot.chats||[]).find(c=>c.chat_id===b.owner)?.label||b.owner).join("、")} 占用／排队`:q.eligible_by_queue_rules?"可申请候选 · 仍须执行前检查":"占用不会因状态过期自动释放";
  main.append(el("p","",`${owner} · ${reason}`));row.append(main,badge(label(q.state),tone(q.state)));return row;
}
function renderNotice(n) {
  const row=el("button","queue-row");row.type="button";row.onclick=()=>choose("notice",n.id);
  row.setAttribute("aria-pressed",String(selected?.type==="notice"&&selected.id===n.id));
  const name=(snapshot.chats||[]).find(c=>c.chat_id===n.recipient)?.label||n.recipient;
  const purpose=(snapshot.queue||[]).find(q=>q.id===n.target_request)?.purpose||n.target_request;
  const main=el("div");main.append(el("strong","",`提醒 ${name}`),el("p","",purpose));
  row.append(main,badge(noticeLabel(n.state),["failed","uncertain"].includes(n.state)?"danger":n.state==="delivered"?"":"warn"));return row;
}
function details() {
  const root=$("detail");root.replaceChildren();$("detail-kind").textContent=selected?.type==="chat"?"对话":selected?.type==="notice"?"提醒":selected?"请求":"未选择";
  if(!selected) {root.append(el("p","empty","选择一个对话或请求，查看版本、证据和阻塞关系。"));return;}
  const item=selected.type==="chat"?(snapshot.chats||[]).find(c=>c.chat_id===selected.id):selected.type==="notice"?(snapshot.release_notices||[]).find(n=>n.id===selected.id):(snapshot.queue||[]).find(q=>q.id===selected.id);
  if(!item) {root.append(el("p","empty","这条记录已离开当前快照。完成的资源请求不再占位。"));return;}
  if(selected.type==="notice") {
    const d=section(root,"提醒状态");pair(d,"接收对话",(snapshot.chats||[]).find(c=>c.chat_id===item.recipient)?.label||item.recipient);pair(d,"投递状态",noticeLabel(item.state));pair(d,"更新时间",time(item.updated));pair(d,"通知编号",item.id);pair(d,"目标请求",item.target_request);
    const codes={tool_unavailable:"宿主消息工具不可用",approval_denied:"未获发送授权",definitive_rejection:"宿主明确拒绝且确认未发送",transport_uncertain:"超时或无法确定是否发出"};pair(d,"结果原因",codes[item.result_code]||"尚无失败记录");
    root.append(el("p","detail-warning",item.state==="uncertain"?"可能已送出。先核查宿主回执，不得自动重发或改用另一通道补发。":item.state==="failed"?"修复原因并确认未发送后，可通过协调工具显式重新排队；本页面不能发消息。":"由完成方领取后使用宿主对话消息工具发送。投递受理不证明已读、开始执行或已获得资源。"));
  } else if(selected.type==="chat") {
    root.append(el("strong","",item.label));let d=section(root,"状态与来源");pair(d,"开发状态",`${label(item.work_state)} · ${item.work_fresh?"有效":"过期／未知"}`);pair(d,"开发上报时间",time(item.work_updated));pair(d,"宿主／本轮",`${label(item.host_state)} / ${item.turn_state==="completed"?"本轮结束":label(item.turn_state)}`);pair(d,"原生快照",`${item.host_source||"没有来源"} · ${time(item.host_observed)}`);pair(d,"接入情况",`${label(item.adoption)} · ${item.client_version||"版本未知"}`);pair(d,"下一步",item.next_step);pair(d,"阻塞",item.blockers.join("；"));
    d=section(root,"责任与版本");pair(d,"项目组",item.project_key);pair(d,"工作树",item.worktree);pair(d,"当前提交",item.commit_id);pair(d,"基线提交",item.provenance?.base_commit);pair(d,"未提交修改",item.provenance?.dirty===true?"有":item.provenance?.dirty===false?"无":"未知");pair(d,"负责文件／接口",item.provenance?.write_scope?.join("\n"));
    const evidence=item.provenance?.evidence||[];section(root,"证据指针");if(!evidence.length)root.append(el("p","muted","尚未提供。"));for(const e of evidence)root.append(el("p","summary",`${label(e.kind)} · ${label(e.status)}\n版本 ${e.revision}\n${e.reference}`));
    root.append(el("p","detail-warning","证据由对话声明，面板未核验其内容；本轮结束不等于验收通过。"));
  } else {
    root.append(el("strong","",item.purpose));let d=section(root,"请求信息");pair(d,"状态",label(item.state));pair(d,"负责人",(snapshot.chats||[]).find(c=>c.chat_id===item.owner)?.label||item.owner);pair(d,"创建时间",time(item.created));pair(d,"请求编号",item.id);pair(d,"资源",item.resources.map(r=>`${r.mode==="exclusive"?"独占":"共享"} · ${r.key}`).join("\n"));
    d=section(root,"阻塞与前置");pair(d,"尚未成功的依赖",item.dependency_blockers?.map(b=>`${b.id} · ${label(b.state)}`).join("\n"));pair(d,"资源阻塞",item.resource_blocker_details?.map(b=>`${b.purpose} · ${b.owner} · ${label(b.state)}`).join("\n"));pair(d,"全部前置请求",item.depends_on?.join("\n"));
    root.append(el("p","detail-warning",item.state==="suspect"?"占用过期仍阻挡。须确认工作及记录进程结束后，由负责人显式恢复。":"候选顺序不是运行许可。仍须检查未登记程序、用户授权、试玩与未保存资产。"));
  }
}
function render() {
  const {chats,queue,notices}=relevant();const attention=chats.filter(needsAttention).length+queue.filter(q=>q.state==="suspect").length+notices.filter(n=>n.state!=="delivered").length;
  $("metric-chats").textContent=String(chats.length);$("metric-active").textContent=String(queue.filter(q=>["leased","running","suspect"].includes(q.state)).length);$("metric-waiting").textContent=String(queue.filter(q=>q.state==="waiting").length);$("metric-attention").textContent=String(attention);
  const only=$("attention-only").checked;const cards=chats.filter(c=>!only||needsAttention(c));$("chats").replaceChildren(...cards.map(renderChat));if(!cards.length)$("chats").append(el("p","empty",chats.length?"当前筛选下没有需关注的对话。":"还没有对话接入。请通过插件登记参与者并上报；不会自动扫描所有历史聊天。"));
  const rows=queue.filter(q=>!only||q.state==="suspect"||q.dependency_blockers?.length||q.resource_blockers?.length);$("queue").replaceChildren(...rows.map(renderQueue));if(!rows.length)$("queue").append(el("p","empty",queue.length?"当前筛选下没有阻塞请求。":"没有已登记的活动请求；这不代表机器或 UE 空闲。"));
  const handoffs=notices.filter(n=>!only||n.state!=="delivered");$("handoffs").replaceChildren(...handoffs.map(renderNotice));if(!handoffs.length)$("handoffs").append(el("p","empty","没有交接提醒记录；未启用或没有符合条件的下一候选时不会产生通知。"));
  if(lastError)notice(lastError);else if(snapshot.queue_truncated)notice("队列超过当前显示上限，候选顺序已禁用；请使用协调工具分批检查。");else if(snapshot.notices_truncated)notice("仅显示最近及未决的 200 条交接提醒，请用协调工具检查更多记录。");else notice("");details();
}
async function refresh() {
  if(busy)return;busy=true;$("refresh").disabled=true;
  try {
    if(!token)throw new Error("缺少本机访问凭据，请使用启动面板时给出的完整地址。");
    const response=await fetch("/api/board",{headers:{"X-Coord-Token":token},cache:"no-store",signal:AbortSignal.timeout(5000)});if(!response.ok)throw new Error(response.status===403?"连接凭据已失效，请从当前面板进程重新打开。":`状态库读取失败（${response.status}）`);
    snapshot=await response.json();lastError="";$("version").textContent=`v${snapshot.version}`;$("captured").textContent=`读取于 ${time(snapshot.captured_at)}`;$("freshness-policy").textContent=`状态有效期 ${snapshot.stale_after} 秒 · 仅刷新本机状态库`;
    $("connection-dot").className="dot connected";$("connection-status").textContent="本机连接正常 · 不自动监控原生对话";
    if(!snapshot.available) {notice(snapshot.reason==="not_initialized"?"尚无协作状态库。面板不会创建数据库或接管已有任务；先由插件初始化并登记对话。":"状态库暂不可读或尚未完成升级；不能据此判断任何资源空闲。");for(const id of ["metric-chats","metric-active","metric-waiting","metric-attention"])$(id).textContent="—";$("chats").replaceChildren(el("p","empty","等待真实协调数据，不使用模拟进度填充。"));$("queue").replaceChildren();$("handoffs").replaceChildren();$("detail").replaceChildren(el("p","empty","状态数据不可用。"));return;}
    const old=$("project").value;const options=[el("option","","全部项目")];options[0].value="";for(const key of [...new Set(snapshot.chats.map(c=>c.project_key))].sort()){const o=el("option","",key);o.value=key;options.push(o);}$("project").replaceChildren(...options);$("project").value=options.some(o=>o.value===old)?old:"";render();
  } catch(error) {lastError=error.message;$("connection-dot").className="dot error";$("connection-status").textContent="连接中断 · 页面旧数据不代表当前状态";if(snapshot?.available){snapshot.chats=snapshot.chats.map(c=>({...c,work_fresh:false,host_fresh:false}));render();}notice(lastError);}
  finally {busy=false;$("refresh").disabled=false;}
}
$("refresh").addEventListener("click",refresh);$("project").addEventListener("change",()=>{if(snapshot?.available)render();});$("attention-only").addEventListener("change",()=>{if(snapshot?.available)render();});
setInterval(()=>{if($("auto-refresh").checked&&!document.hidden)refresh();},5000);document.addEventListener("visibilitychange",()=>{if(!document.hidden&&$("auto-refresh").checked)refresh();});refresh();
