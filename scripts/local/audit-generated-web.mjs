// Verify the actual synthetic website returned by the live planning audit.
import {createRequire} from 'node:module';
import {homedir} from 'node:os';
import {readFileSync, mkdirSync, writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PABLO_PLAYWRIGHT_MODULE || homedir()+'/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const cases=readFileSync('.local/audit-live.jsonl','utf8').trim().split('\n').map(row=>JSON.parse(row));
const entry=cases.filter(row=>row.case===6&&row.status==='PASS').at(-1);
if(!entry)throw new Error('Run audit-live.py 6 first');
const folder=resolve('.local/audit-generated-'+Date.now());mkdirSync(folder,{recursive:true});
const code='import json,sys; from pablo.workspace_tools import code_scaffold; print(json.dumps(code_scaffold(None,json.load(sys.stdin),None)))';
const result=JSON.parse(execFileSync(resolve('.runtime/Scripts/python.exe'),['-c',code],{input:JSON.stringify(entry.plan.steps[0].arguments),encoding:'utf8',windowsHide:true,env:{...process.env,PYTHONIOENCODING:'utf-8',PYTHONPATH:resolve('backend'),PABLO_WORKSPACE_ROOT:folder}}));
const browser=await chromium.launch({channel:'chrome',headless:true});
try{
  const page=await browser.newPage();
  await page.route(/^https?:/,route=>route.abort());
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(pathToFileURL(resolve(folder,result.entrypoint)).href);
  await page.getByRole('heading',{name:'Restaurante Luna',exact:true}).waitFor();
  await page.getByRole('heading',{name:'Menú',exact:true}).waitFor();
  const dialog=page.waitForEvent('dialog').then(async alert=>{
    const correct=alert.message().includes('123');
    await alert.dismiss();
    if(!correct)throw new Error('Wrong telephone');
  });
  await page.getByRole('button',{name:/teléfono/i}).click();
  await dialog;
  if(errors.length)throw new Error(errors.join('\n'));
  await page.screenshot({path:resolve('docs/screenshots/generated-web-audit.png'),fullPage:true});
  writeFileSync('.local/audit-generated-web.json',JSON.stringify({status:'PASS',checks:['actual model HTML saved in isolated folder','separate CSS/JS','menu visible','telephone button returns 123','no JavaScript errors'],timestamp:new Date().toISOString()},null,2));
  console.log('PASS: actual generated website, separate files, visible menu and working telephone button.');
}finally{await browser.close();}
