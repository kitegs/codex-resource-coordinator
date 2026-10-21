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
