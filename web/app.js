"use strict";
const el = (id) => document.getElementById(id);
let boot, lastJob, active = false;
const labels = {completed:"已完成",failed:"执行失败",needs_information:"待补信息",infeasible:"无可行方案",budget_exhausted:"达到步数上限",succeeded:"成功",pending:"待执行"};
const names = {search_materials:"素材检索",generate_script:"脚本生成",save_plan:"方案保存",estimate_cost:"成本估算",select_plan:"选择方案",finish:"结束"};
function text(tag, value, className) { const n=document.createElement(tag); n.textContent=value; if(className)n.className=className; return n; }
async function api(path, data) {
  const r=await fetch(path,data===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":boot.csrf_token},body:JSON.stringify(data)});
  const value=await r.json(); if(!r.ok)throw new Error(value.error||`请求失败 ${r.status}`); return value;
}
function notice(message,error=false){el("notice").textContent=message;el("notice").classList.toggle("error",error);}
function busy(value){active=value;for(const id of ["run","resume","scenario","new-id"])el(id).disabled=value;el("state").textContent=value?"规划中…":el("state").textContent;}
function loadPayload(p){
  el("topic").value=p.request.topic;el("budget").value=p.request.budget??"";
  const d=p.request.deadline?new Date(p.request.deadline):null;
  el("deadline").value=d?new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16):"";
  el("request-id").value=p.request.request_id;el("catalog").value=JSON.stringify(p.catalog,null,2);
  el("mode").value=p.mode;el("max-steps").value=p.max_steps||16;
}
function payload(){return {request:{request_id:el("request-id").value.trim(),topic:el("topic").value.trim(),budget:el("budget").value===""?null:el("budget").value,deadline:el("deadline").value?new Date(el("deadline").value).toISOString():null},catalog:JSON.parse(el("catalog").value),mode:el("mode").value,max_steps:Number(el("max-steps").value)};}
function render(job){
  lastJob=job;const r=job.result;
  el("empty").hidden=true;el("result").hidden=false;el("trace").replaceChildren();
  for(const row of job.trace){const n=text("div","","trace-row");n.append(text("b",`${row.step}. ${names[row.action.tool]||row.action.tool} · ${row.observation.status}`),text("div",row.action.reason),text("pre",JSON.stringify({arguments:row.action.arguments,observation:row.observation,next_action:row.next_action},null,2)));el("trace").append(n);}
  if(!r){el("state").textContent="未完成";el("state").classList.add("bad");el("reason").textContent=job.error;el("cost").textContent="待核对";el("package").textContent="—";el("saved").textContent="待核对";for(const id of ["steps","options","plan"])el(id).replaceChildren();return;}
  el("state").textContent=labels[r.status]||r.status;el("state").classList.toggle("bad",r.status!=="completed");
  el("cost").textContent=r.actual_cost.toFixed(2);el("package").textContent=r.package||"—";el("saved").textContent=r.plan_id?"已保存":"未保存";
  const reasons={missing_required_inputs:`请补充：${r.missing.join("、")}，再生成新请求 ID。`,no_feasible_plan:"当前预算或截止时间内没有可行方案，缺口见下方。",model_step_limit:"本次达到模型步数上限。已完成步骤保留，可续跑原请求。",model_unavailable:"模型请求失败。已完成步骤保留，请检查服务后续跑。",existing_plan_reused:"复用已保存方案；本次未增加工具费用。"};
  el("reason").textContent=reasons[r.reason]||(r.status==="completed"?`方案已保存 · ${r.plan_id} · 本次 ${r.steps_used} 步`:`未完成步骤已记录，成功结果保留。累计模拟耗时 ${r.simulated_elapsed_minutes} 分钟。`);
  el("steps").replaceChildren();
  const keys=[...new Set([...r.task_plan.map(s=>s.step),...Object.keys(r.steps)])];
  for(const key of keys){const step=r.steps[key]||{status:"pending",attempts:0};const row=text("div","","step");const body=text("div",(names[key.split(":")[0]]||key)+(key.includes(":")?" / "+key.split(":")[1]:""));const dep=r.task_plan.find(s=>s.step===key)?.depends_on||[];body.append(text("small",`依赖：${dep.join(" → ")||"无"} · 已尝试 ${step.attempts} 次${step.error?" · "+step.error:""}`));row.append(body,text("span",labels[step.status]||step.status,"status "+step.status));el("steps").append(row);}
  el("options").replaceChildren();for(const q of r.options)el("options").append(text("div",`${q.package}：预计总费 ${q.estimated_total} / 预算缺口 ${q.budget_gap} / 超时 ${q.deadline_gap_minutes} 分钟 / ${q.feasible?"可行":"不可行"}`,"option"));
  el("plan").replaceChildren();if(r.saved_plan){el("plan").append(text("h3","已保存活动方案"));const box=text("div",r.saved_plan.script.title,"plan-text");for(const part of r.saved_plan.script.script)box.append(text("p",part.stage+" · "+part.text));box.append(text("small",`素材：${r.saved_plan.script.material_ids.join("、")}；合成脚本工具输出，仅保存方案。`));el("plan").append(box);}
}
async function plans(){try{const data=await api("/api/plans");el("plans").replaceChildren();if(!data.plans.length)el("plans").append(text("p","尚无方案。完成规划并实际保存后会出现在这里。","help"));for(const p of data.plans){const n=text("div",`${p.topic} · ${p.package} · ${p.total_cost} 模拟单位`,"plan-card");n.append(text("br",""),text("small",`${p.plan_id} / 请求 ${p.request_id}`));el("plans").append(n);}}catch(e){notice(e.message,true);}}
async function watch(id){
  busy(true);notice("任务执行中；真实模型通常需要数分钟。可以刷新页面恢复查看。");
  try{for(;;){const job=await api("/api/jobs/"+id);loadPayload(job.payload);if(job.state!=="running"){render(job);notice(job.state==="error"?job.error:"执行结束；结果与费用以保存状态和账本为准。",job.state==="error");await plans();break;}await new Promise(r=>setTimeout(r,900));}}
  catch(e){notice(e.message+"。原始输入已保留，可重新提交同一请求续跑。",true);}
  finally{busy(false);}
}
async function start(p){if(active)return;busy(true);try{localStorage.setItem("q2-payload",JSON.stringify(p));const j=await api("/api/jobs",p);localStorage.setItem("q2-job",j.job_id);await watch(j.job_id);}catch(e){notice(e.message,true);busy(false);}}
el("plan-form").addEventListener("submit",e=>{e.preventDefault();try{start(payload());}catch(err){notice("配置 JSON 或输入无效："+err.message,true);}});
el("scenario").addEventListener("change",()=>{const p=structuredClone(boot.scenarios[el("scenario").value]);p.request.request_id=el("scenario").value+"-"+crypto.randomUUID();loadPayload(p);notice("已载入新场景。点击开始规划。");});
el("new-id").addEventListener("click",()=>{el("request-id").value="plan-"+crypto.randomUUID();});
el("resume").addEventListener("click",()=>{if(lastJob)start(lastJob.payload);});
el("refresh-plans").addEventListener("click",plans);
el("download").addEventListener("click",()=>{if(!lastJob)return;const url=URL.createObjectURL(new Blob([JSON.stringify(lastJob,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download=lastJob.payload.request.request_id+"-run.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
(async()=>{try{boot=await api("/api/bootstrap");for(const [value,label] of Object.entries(boot.labels)){const option=text("option",label);option.value=value;el("scenario").append(option);}el("model-info").textContent="真实模式使用："+boot.model_name+"。离线模式仅验证流程与守卫。";loadPayload(boot.scenarios.reference);await plans();const saved=localStorage.getItem("q2-payload");if(saved){try{loadPayload(JSON.parse(saved));}catch{localStorage.removeItem("q2-payload");}}const id=boot.active_job||localStorage.getItem("q2-job");if(id)await watch(id);else notice("服务已连接。选择场景，或填写你的活动需求。");}catch(e){notice("无法连接本地工作台："+e.message,true);}})();
