const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const base=process.env.WEB_URL||'http://127.0.0.1:8768';
const out=process.env.BROWSER_OUTPUT||'examples/browser';
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL,headless:true}:{headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1100}});const checks=[];const errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
 const ok=(name,condition=true)=>{assert.ok(condition,name);checks.push({name,passed:true});};
 async function scenario(name){await page.selectOption('#scenario',name);await page.click('#run');await page.waitForFunction(()=>!document.querySelector('#run').disabled,{},{timeout:30000});}
 await page.goto(base);await page.waitForFunction(()=>document.querySelector('#scenario').options.length>0);ok('page and bootstrap loaded');
 await scenario('reference');ok('reference completes',await page.textContent('#state')==='已完成');ok('cost is eight',await page.textContent('#cost')==='8.00');
 let before=await page.textContent('#reason');await page.click('#resume');await page.waitForFunction(()=>!document.querySelector('#run').disabled);ok('repeat returns existing plan',(await page.textContent('#reason')).includes('复用已保存方案'));
 const downloadPromise=page.waitForEvent('download');await page.click('#download');const dl=await downloadPromise;await dl.saveAs(path.join(out,'downloaded-run.json'));let job=JSON.parse(fs.readFileSync(path.join(out,'downloaded-run.json'),'utf8'));ok('download retains actual result and input',job.result.actual_cost===8&&job.result.steps_used===0&&job.payload.request.budget==='10');
 await page.reload();await page.waitForFunction(()=>document.querySelector('#state').textContent==='已完成');ok('reload restores original request',(await page.inputValue('#request-id'))===job.payload.request.request_id);
 await scenario('resume');ok('failed script visible',await page.textContent('#state')==='执行失败');ok('successful search cost retained',await page.textContent('#cost')==='2.00');
 await page.fill('#topic','未提交的不同主题');await page.click('#resume');await page.waitForFunction(()=>!document.querySelector('#run').disabled);ok('resume uses original payload',await page.inputValue('#topic')==='秋季新品内容活动');ok('resume completes for eight',await page.textContent('#cost')==='8.00'&&await page.textContent('#state')==='已完成');ok('search is not repeated',(await page.textContent('#steps')).includes('已尝试 1 次'));
 await scenario('missing');ok('missing input guard',await page.textContent('#state')==='待补信息'&&await page.textContent('#cost')==='0.00');
 await scenario('over_budget');ok('budget gap shown',await page.textContent('#state')==='无可行方案'&&(await page.textContent('#options')).includes('预算缺口 1'));
 await scenario('tool_failure');ok('replanning preserves failed premium',(await page.textContent('#steps')).includes('injected_tool_failure')&&await page.textContent('#state')==='已完成');
 await scenario('save_failure');ok('save failure not success',await page.textContent('#saved')==='未保存'&&await page.textContent('#cost')==='6.00');await page.click('#resume');await page.waitForFunction(()=>!document.querySelector('#run').disabled);ok('save-only resume',await page.textContent('#saved')==='已保存'&&await page.textContent('#cost')==='8.00');
 await page.locator('.setup details').evaluate(n=>n.open=true);await page.fill('#catalog','{broken');await page.click('#run');ok('invalid JSON is actionable',(await page.textContent('#notice')).includes('JSON'));
 await page.selectOption('#scenario','reference');await page.fill('#topic','<img src=x onerror=alert(1)>');await page.click('#run');await page.waitForFunction(()=>!document.querySelector('#run').disabled);ok('topic rendered as text',await page.locator('#plan img').count()===0&&(await page.textContent('#plan')).includes('<img'));
 await scenario('reference');await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});ok('mobile no horizontal overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
 await page.goto(base+'/manual.html');ok('manual available',(await page.textContent('h1')).includes('活动方案'));ok('no browser errors',errors.length===0);
 fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({tested_at:new Date().toISOString(),base,checks,errors,passed:true},null,2));await browser.close();console.log(`${checks.length} browser checks passed`);
})().catch(e=>{console.error(e);process.exit(1)});
