import { createRequire } from 'node:module';
import { homedir } from 'node:os';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PABLO_PLAYWRIGHT_MODULE || homedir() + '/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
import { spawn, execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createServer } from 'node:net';

const root=process.cwd(), python=process.env.PABLO_TEST_PYTHON || resolve('.runtime/Scripts/python.exe');
const net=createServer();await new Promise(r=>net.listen(0,'127.0.0.1',r));const port=net.address().port;await new Promise(r=>net.close(r));
const base=`http://127.0.0.1:${port}`;
const database=resolve(`.local/ui-qa-${Date.now()}.db`);
const env={...process.env,PYTHONPATH:resolve('backend'),DATABASE_URL:'sqlite:///'+database,APP_ORIGIN:base,AI_API_KEY:'',AI_EMBED_MODEL:'',PABLO_SECRET_KEY_FILE:database+'.key',PABLO_WORKSPACE_ROOT:database+'.files'};
mkdirSync(resolve('docs/screenshots'),{recursive:true});
execFileSync(python,['-m','alembic','-c','backend/alembic.ini','upgrade','head'],{env,cwd:root,windowsHide:true,stdio:'pipe'});
const children=[spawn(python,['-m','uvicorn','pablo.main:app','--host','127.0.0.1','--port',String(port)],{env,windowsHide:true,stdio:'pipe'}),spawn(python,['-m','pablo.worker'],{env,windowsHide:true,stdio:'pipe'})];
let logs='';for(const child of children){child.stdout.on('data',b=>logs+=b);child.stderr.on('data',b=>logs+=b);}
let browser;
try {
  for(let i=0;i<100;i++){try{if((await fetch(base+'/ready')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({channel:'chrome',headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:1000},locale:'es-ES'});
  const setup=await context.request.post(base+'/api/v1/auth/setup',{headers:{'X-Pablo-Request':'1'},data:{name:'Pablo QA',password:'QA-temporary-password-12345'}});if(!setup.ok())throw new Error('Setup '+await setup.text());
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);await page.getByRole('heading',{name:'Hola, Pablo QA.'}).waitFor();
  await page.screenshot({path:resolve('docs/screenshots/inicio.png'),fullPage:true});
  if(await page.getByRole('tab',{name:'Hacer',exact:true}).count())throw new Error('Old mode selector still visible');
  if(await page.getByRole('button',{name:'Agentes',exact:true}).count())throw new Error('Agents navigation still visible');
  await page.getByLabel('¿Qué quieres conseguir?',{exact:true}).fill('Añade como tareas:\n- Comprar pan QA\n- Estudiar QA');
  await page.getByRole('button',{name:'Enviar objetivo',exact:true}).click();
  for (const title of ['Comprar pan QA','Estudiar QA']) {
    await page.locator('.approval').filter({hasText:title}).getByRole('button',{name:'Aprobar este paso',exact:true}).click();
  }
  await page.locator('.messages').getByText('Tarea creada:',{exact:false}).last().waitFor();
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:/^Tareas/}).click();
  await page.getByText('Comprar pan QA',{exact:true}).first().waitFor();
  await page.getByText('Estudiar QA',{exact:true}).first().waitFor();
  await page.getByRole('button',{name:'Inicio',exact:true}).click();
  await page.getByRole('button',{name:'Actualizar resumen',exact:true}).click();
  await page.locator('.execution-inline').waitFor();
  if(!await page.getByRole('button',{name:'Nueva conversación',exact:true}).isVisible())throw new Error('Daily summary did not open Command');
  await page.getByRole('button',{name:'Inicio',exact:true}).click();
  const scaffold = await context.request.post(base+'/api/v1/tool-runs',{headers:{'X-Pablo-Request':'1'},data:{tool:'code.scaffold',arguments:{name:'Web QA',kind:'app'}}});
  if(!scaffold.ok())throw new Error('Scaffold request failed');
  const scaffoldRun=await scaffold.json();
  for(let i=0;i<40;i++){
    const current=await (await context.request.get(base+'/api/v1/state')).json();
    const approval=current.approvals.find(a=>a.run_id===scaffoldRun.id);
    if(approval){const approved=await context.request.post(base+'/api/v1/approvals/'+approval.id,{headers:{'X-Pablo-Request':'1'},data:{approve:true}});if(!approved.ok())throw new Error('Scaffold approval failed');break;}
    await new Promise(r=>setTimeout(r,250));
  }
  for(let i=0;i<40;i++){
    const run=await (await context.request.get(base+'/api/v1/runs/'+scaffoldRun.id)).json();
    if(run.status==='COMPLETED')break;
    if(run.status==='FAILED')throw new Error('Scaffold failed: '+run.result);
    await new Promise(r=>setTimeout(r,250));
  }
  // No click/refresh: background executions must become visible while Home is idle.
  await page.getByText('Usar code.scaffold',{exact:true}).first().waitFor({timeout:25000});
  await page.getByRole('button',{name:'Workspace',exact:true}).click();
  await page.locator('summary').filter({hasText:'web-qa'}).click();
  await page.getByRole('button',{name:'web-qa/index.html',exact:true}).click();
  await page.getByRole('heading',{name:'web-qa/index.html',exact:true}).waitFor();
  await page.getByRole('button',{name:'web-qa/styles.css',exact:true}).waitFor();
  const popupPromise=page.waitForEvent('popup');
  await page.getByRole('link',{name:'Abrir web · index.html',exact:true}).click();
  const preview=await popupPromise;
  preview.on('console',msg=>{if(msg.type()==='error')console.log('Preview console: '+msg.text());});
  preview.on('pageerror',err=>console.log('Preview error: '+err.message));
  await preview.getByRole('heading',{name:'Web QA',exact:true}).waitFor();
  await preview.getByPlaceholder('¿Qué quieres conseguir?').fill('Tarea dentro de la web');
  await preview.getByRole('button',{name:'Añadir tarea',exact:true}).click();
  await preview.getByText('Tarea dentro de la web',{exact:true}).waitFor();
  const isolated=await preview.evaluate(()=>{try{void document.cookie;return false;}catch{return true;}});
  if(!isolated)throw new Error('Generated website is not isolated from application cookies');
  await preview.close();
  await page.screenshot({path:resolve('docs/screenshots/workspace-audit.png'),fullPage:true});
  await page.getByRole('button',{name:'Calendario',exact:true}).click();
  if(await page.locator('.calendar-grid').evaluate(el=>getComputedStyle(el).display)!=='grid')throw new Error('Calendar styles missing');
  await page.getByRole('button',{name:'Nuevo evento',exact:true}).click();
  await page.getByLabel('Título',{exact:true}).fill('Sesión de revisión');
  await page.getByRole('button',{name:'Guardar evento',exact:true}).click();
  await page.getByRole('button',{name:/Sesión de revisión/}).waitFor();
  await page.screenshot({path:resolve('docs/screenshots/agenda.png'),fullPage:true});
  await page.getByRole('button',{name:'Integraciones',exact:true}).click();
  await page.getByRole('heading',{name:'GitHub',exact:true}).waitFor();
  await page.screenshot({path:resolve('docs/screenshots/integraciones.png'),fullPage:true});
  await page.getByRole('button',{name:'Ajustes',exact:true}).click();
  await page.getByRole('heading',{name:'Inteligencia artificial',exact:true}).waitFor();
  await page.getByRole('button',{name:'Detectar IA local gratuita',exact:true}).click();
  await page.getByText(/Ollama está conectado|No se pudo conectar con Ollama|Ollama funciona, pero/).waitFor();
  await page.screenshot({path:resolve('docs/screenshots/ajustes.png'),fullPage:true});
  const before=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:resolve('docs/screenshots/movil.png'),fullPage:true});
  const mobile=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
  if(before.scroll>before.width+2||mobile.scroll>mobile.width+2)throw new Error('Horizontal overflow '+JSON.stringify({before,mobile}));
  if(errors.length)throw new Error(errors.join('\n'));
  const phone = await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true,deviceScaleFactor:3,locale:'es-ES'});
  const phoneLogin = await phone.request.post(base+'/api/v1/auth/login',{headers:{'X-Pablo-Request':'1'},data:{name:'Pablo QA',password:'QA-temporary-password-12345'}});
  if(!phoneLogin.ok())throw new Error('Mobile login failed');
  const phonePage=await phone.newPage();
  await phonePage.goto(base);
  await phonePage.getByRole('heading',{name:'Hola, Pablo QA.'}).waitFor();
  const syncedTask=await context.request.post(base+'/api/v1/items/tasks',{headers:{'X-Pablo-Request':'1'},data:{title:'Sincronización desde ordenador',priority:'HIGH'}});
  if(!syncedTask.ok())throw new Error('Desktop task creation failed');
  await phonePage.getByRole('button',{name:'Sincronización desde ordenador',exact:true}).first().waitFor({timeout:25000});
  await phonePage.screenshot({path:resolve('docs/screenshots/iphone-home.png'),fullPage:true});
  const mobileTask=await phone.request.post(base+'/api/v1/items/tasks',{headers:{'X-Pablo-Request':'1'},data:{title:'Sincronización desde móvil',priority:'HIGH'}});
  if(!mobileTask.ok())throw new Error('Mobile task creation failed');
  const desktopState=await (await context.request.get(base+'/api/v1/state')).json();
  if(!desktopState.items.some(i=>i.title==='Sincronización desde móvil'))throw new Error('Mobile changes not visible on desktop');
  await phonePage.evaluate(()=>navigator.serviceWorker.ready);
  await phonePage.waitForFunction(()=>!!navigator.serviceWorker.controller);
  if((await phonePage.evaluate(()=>caches.keys())).length)throw new Error('Private app unexpectedly caches responses');
  await phone.setOffline(true);
  await phonePage.goto(base);
  await phonePage.getByRole('heading',{name:'No hay conexión'}).waitFor();
  await phone.close();
  console.log('PASS: separate mobile/desktop sessions share tasks; installed service worker shows offline screen and stores no private responses.');
  console.log('PASS: chat task creation and approval, daily summary navigation, idle refresh, isolated website files in Workspace, desktop/mobile, local calendar creation, integrations/settings, no JavaScript errors or horizontal overflow.');
} catch(error) {writeFileSync(resolve('.local/ui-qa.log'),logs);if(browser){const pages=browser.contexts().flatMap(c=>c.pages());if(pages[0]){console.log((await pages[0].locator('body').innerText()).slice(0,10000));await pages[0].screenshot({path:resolve('docs/screenshots/qa-error.png'),fullPage:true});}}throw error;}
finally {if(browser)await browser.close();for(const child of children){try{execFileSync('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'pipe'});}catch{} } }

