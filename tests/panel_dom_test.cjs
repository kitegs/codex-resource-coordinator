// DOM behavior tests, not a substitute for browser/layout acceptance.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const {test}=require("node:test");
const source=fs.readFileSync(path.join(__dirname,"../plugins/resource-coordinator/coordinator/panel/panel.js"),"utf8");
class Element {
  constructor(tag="div"){this.tagName=tag;this.children=[];this.listeners={};this._text="";this.value="";this.checked=false;this.attributes={};}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(c=>c.textContent).join("");}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this._text="";this.children=nodes;}
  setAttribute(key,value){this.attributes[key]=value;}
  addEventListener(event,callback){this.listeners[event]=callback;}
}
function fixture(){
  const chat=id=>({chat_id:id,label:id,project_key:id,work_state:"working",summary:"Synthetic fixture",next_step:"Review",blockers:[],work_fresh:true,host_fresh:true,host_state:"idle",turn_state:"completed",host_observed:Date.now()/1000,work_updated:Date.now()/1000,adoption:"observed_only",client_version:"",provenance:{}});
  return {available:true,version:"0.3.0",captured_at:Date.now()/1000,stale_after:180,chats:[chat("a"),chat("b")],queue:[],queue_truncated:false};
}
async function harness(snapshot=fixture(),hash="#key=synthetic-local-token"){
  const nodes=new Map();let failure=null,current=snapshot;
  const document={hidden:false,getElementById(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},createElement(tag){return new Element(tag);},addEventListener(){}};
  document.getElementById("auto-refresh").checked=true;
  const context={document,location:{hash},URLSearchParams,AbortSignal,Date,console,setInterval(){},async fetch(url,options){assert.equal(url,"/api/board");assert.equal(options.headers["X-Coord-Token"],"synthetic-local-token");if(failure)throw new Error(failure);return {ok:true,json:async()=>structuredClone(current)};}};
  vm.createContext(context);vm.runInContext(source,context);await new Promise(resolve=>setImmediate(resolve));
  return {nodes,context,set(value){current=value;failure=null;},fail(message){failure=message;}};
}
test("peer text, selection and persistent project filter",async()=>{
  const state=fixture();state.chats[0].label="<img src=x onerror=alert(1)>";
  const h=await harness(state),get=id=>h.nodes.get(id);
  assert.equal(get("metric-chats").textContent,"2");assert.equal(get("chats").children[0].children[0].children[0].textContent,state.chats[0].label);
  get("chats").children[0].onclick();assert.match(get("detail").textContent,/本轮结束/);
  get("project").value="b";get("project").listeners.change();assert.equal(get("metric-chats").textContent,"1");
  await h.context.refresh();assert.equal(get("project").value,"b");assert.equal(get("metric-chats").textContent,"1");
});
test("disconnect stays visible across filtering and reconnect recovers",async()=>{
  const h=await harness(),get=id=>h.nodes.get(id);
  h.fail("synthetic disconnect");await h.context.refresh();assert.match(get("connection-status").textContent,/连接中断/);assert.equal(get("notice").hidden,false);
  get("attention-only").checked=true;get("attention-only").listeners.change();assert.match(get("notice").textContent,/synthetic disconnect/);assert.match(get("chats").textContent,/过期/);
  h.set(fixture());await h.context.refresh();assert.equal(get("notice").hidden,true);assert.match(get("connection-status").textContent,/连接正常/);
});
test("missing database or credential shows an honest empty/error state",async()=>{
  const h=await harness({available:false,reason:"not_initialized",version:"0.3.0",captured_at:Date.now()/1000,stale_after:180});
  assert.equal(h.nodes.get("metric-chats").textContent,"—");assert.match(h.nodes.get("notice").textContent,/不会创建数据库/);
  const noKey=await harness(fixture(),"");assert.match(noKey.nodes.get("notice").textContent,/缺少本机访问凭据/);
});
test("handoff recipient, uncertain result and accepted-not-read details stay distinct",async()=>{
  const state=fixture();state.release_notices=[{id:"synthetic-notice",recipient:"b",project_key:"b",target_request:"synthetic-request",state:"uncertain",result_code:"transport_uncertain",updated:Date.now()/1000}];
  const h=await harness(state),get=id=>h.nodes.get(id);
  assert.match(get("handoffs").textContent,/提醒 b/);assert.match(get("handoffs").textContent,/结果不明/);
  get("handoffs").children[0].onclick();assert.match(get("detail").textContent,/不得自动重发/);
  get("project").value="a";get("project").listeners.change();assert.doesNotMatch(get("handoffs").textContent,/提醒 b/);
  state.release_notices[0].state="delivered";state.release_notices[0].result_code="";get("project").value="";h.set(state);await h.context.refresh();
  assert.match(get("handoffs").textContent,/未确认已读/);
  get("attention-only").checked=true;get("attention-only").listeners.change();assert.doesNotMatch(get("handoffs").textContent,/提醒 b/);
});
test("obsolete notices stay inspectable but do not count as actionable",async()=>{
  const state=fixture();state.chats=[];state.release_notices=[{id:"obsolete",recipient:"b",project_key:"test",target_request:"done",state:"obsolete",result_code:"request_no_longer_waiting",updated:Date.now()/1000}];
  const h=await harness(state),get=id=>h.nodes.get(id);
  assert.equal(get("metric-attention").textContent,"0");assert.match(get("handoffs").textContent,/已失效·未发送/);
  get("handoffs").children[0].onclick();assert.match(get("detail").textContent,/领取前已失效/);
  get("attention-only").checked=true;get("attention-only").listeners.change();assert.doesNotMatch(get("handoffs").textContent,/提醒 b/);
});
test("queue progress is local-conflict count not ETA, and monitoring samples are qualified",async()=>{
  const state=fixture();state.queue=[{id:"wait",purpose:"Next compile",owner:"a",state:"waiting",resources:[],queue_progress:{waiting_ahead_count:2},eligible_by_queue_rules:false},{id:"monitor",purpose:"Running",owner:"b",state:"suspect",resources:[],operation:{phase:"needs_verification",active_processes:1,updated:Date.now()/1000}}];
  const h=await harness(state),get=id=>h.nodes.get(id);
  assert.match(get("queue").textContent,/同资源前方 2 项等待/);assert.match(get("queue").textContent,/作业监护待核查/);
  get("queue").children[0].onclick();assert.match(get("detail").textContent,/不估算等待时间/);
  get("queue").children[1].onclick();assert.match(get("detail").textContent,/恢复只观察/);
});
test("simple overview shows current owner, next candidate and actual delivery state",async()=>{
  const state=fixture();state.queue=[{id:"held",purpose:"Build",owner:"a",state:"running",resources:[]},{id:"next",purpose:"Test",owner:"b",state:"waiting",resources:[],resource_blocker_details:[{id:"held",owner:"a",state:"running"}]}];
  const h=await harness(state),get=id=>h.nodes.get(id);
  assert.equal(get("handoff-current").textContent,"a");assert.match(get("handoff-next").textContent,/b · 待前方释放/);assert.match(get("handoff-delivery").textContent,/尚无提醒/);
  state.queue.shift();state.queue[0].eligible_by_queue_rules=true;state.release_notices=[{id:"notice",recipient:"b",project_key:"b",target_request:"next",state:"pending",updated:1}];h.set(state);await h.context.refresh();
  assert.match(get("handoff-next").textContent,/可申请，尚未获占用/);assert.match(get("handoff-delivery").textContent,/待代发/);
  state.release_notices[0].state="delivered";h.set(state);await h.context.refresh();assert.match(get("handoff-delivery").textContent,/投递受理·未确认已读/);
  state.release_notices[0].state="uncertain";h.set(state);await h.context.refresh();assert.match(get("handoff-delivery").textContent,/勿重发/);
});
test("overview does not turn dependency blockage, truncated data or disconnection into clearance",async()=>{
  const state=fixture();state.queue=[{id:"wait",purpose:"Test",owner:"b",state:"waiting",resources:[],dependency_blockers:[{id:"failed",state:"failed"}]}];
  const h=await harness(state),get=id=>h.nodes.get(id);assert.match(get("handoff-next").textContent,/前置条件未满足/);
  state.queue_truncated=true;h.set(state);await h.context.refresh();assert.match(get("handoff-next").textContent,/状态未确认/);
  state.queue_truncated=false;h.set(state);await h.context.refresh();h.fail("disconnect");await h.context.refresh();assert.match(get("handoff-current").textContent,/状态未确认/);
  h.set(fixture());await h.context.refresh();assert.match(get("handoff-current").textContent,/仍需现场检查/);
});
