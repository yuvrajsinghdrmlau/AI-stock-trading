/* Explicit, local trading tools. Watching runs only while the relevant UI is open. */
const tradeTools={key:null,strategy:'trend_pullback',side:'buy',derivative:false,tab:'entry',timer:null,watch:false,request:0,signal:null,alertTimer:null,alertAuto:false,alertBusy:false};
function toolButton(row){return `<button class="button subtle" data-open-tools="${h(row.instrument.instrument_key)}" data-tools-strategy="${h(row.strategy||'trend_pullback')}" data-tools-side="${row.idea?.direction==='DOWN'?'sell':'buy'}" data-tools-derivative="${!!row.idea}">Trade toolkit</button>`;}
function toolBody(refresh=false){return {instrument_key:tradeTools.key,strategy:tradeTools.strategy,side:tradeTools.side,derivative:tradeTools.derivative,stop_method:document.getElementById('tool-stop')?.value||'atr',reward_r:Number(document.getElementById('tool-reward')?.value||2),refresh};}
function toolDialog(id,title){
  document.getElementById(id)?.remove();const dialog=document.createElement('dialog');dialog.id=id;dialog.className='trade-review tools-dialog';
  dialog.innerHTML=`<div class="panel-head"><h2>${h(title)}</h2><button class="icon-button" data-close-tool aria-label="Close">×</button></div><div class="panel-body" data-tool-dialog-body></div>`;
  dialog.addEventListener('click',e=>{if(e.target===dialog||e.target.closest('[data-close-tool]'))dialog.close();});
  dialog.addEventListener('close',()=>{if(id==='trade-toolkit'){stopEntryWatch();tradeTools.request++;}dialog.remove();});
  document.body.append(dialog);dialog.showModal();return dialog;
}
async function openTradeToolkit(button){
  stopEntryWatch();tradeTools.key=button.dataset.openTools;tradeTools.strategy=button.dataset.toolsStrategy||'trend_pullback';tradeTools.side=button.dataset.toolsSide||'buy';tradeTools.derivative=button.dataset.toolsDerivative==='true';tradeTools.tab='entry';tradeTools.signal=null;
  const row=discoveryState.result?.rows.find(r=>r.instrument.instrument_key===tradeTools.key);
  const dialog=toolDialog('trade-toolkit',(row?.instrument.symbol||'Stock')+' · trade toolkit');
  dialog.querySelector('[data-tool-dialog-body]').innerHTML=`<p class="small muted">Check the entry, compare exit scenarios, review historical results and follow your own alerts.</p><div class="tools-tabs" role="tablist" aria-label="Trade tools">${[['entry','Entry & exits'],['replay','Historical replay'],['news','Headlines'],['alerts','Price alerts']].map(([key,label])=>`<button role="tab" data-tool-tab="${key}" aria-selected="${key==='entry'}">${label}</button>`).join('')}</div><div id="tool-panel" aria-live="polite"></div>`;
  await showToolTab('entry');
}
function stopEntryWatch(){tradeTools.watch=false;clearTimeout(tradeTools.timer);tradeTools.timer=null;}
async function showToolTab(tab){
  stopEntryWatch();tradeTools.tab=tab;tradeTools.request++;
  for(const b of document.querySelectorAll('[data-tool-tab]'))b.setAttribute('aria-selected',b.dataset.toolTab===tab?'true':'false');
  const panel=$('#tool-panel');if(!panel)return;
  if(tab==='entry'){
    panel.innerHTML=`<div class="tools-controls"><label>Direction<select id="tool-side"><option value="buy">Upward / buy</option><option value="sell">Downward / short intraday</option></select></label><label>Stop method<select id="tool-stop"><option value="atr">1.5 × normal price movement (ATR)</option><option value="range_mid">Opening-range midpoint</option><option value="range_edge">Opposite opening-range edge</option></select></label><label>Target / risk<select id="tool-reward"><option value="1">1 : 1</option><option value="2" selected>2 : 1</option><option value="3">3 : 1</option><option value="4">4 : 1</option></select></label></div><div class="tip-card-actions"><button class="button primary" data-tool-refresh>Load / recheck candles</button><label class="inline-check"><input type="checkbox" id="tool-watch"> Watch entry every minute while open</label></div><div id="entry-tool-result"></div>`;
    $('#tool-side').value=tradeTools.side;await loadEntryTool(false);
  }else if(tab==='replay'){
    panel.innerHTML=`<p>Replay the fixed strategy on this stock’s completed history. Costs, gaps and non-overlapping trades are included.</p><p class="small muted">The replay uses the original fixed strategy and 2R target, not custom exit scenarios from the other tab.${tradeTools.derivative?' F&O replay covers the underlying direction only; it does not estimate option returns or futures basis.':''}</p><button class="button primary" data-run-replay>Run historical replay</button><div id="replay-tool-result"></div>`;
  }else if(tab==='news'){
    panel.innerHTML='<p>Headlines can reveal results, corporate actions or regulatory events that a chart alone misses.</p><button class="button primary" data-load-headlines>Load recent headlines</button><div id="news-tool-result"></div>';
  }else{
    panel.innerHTML=`<p>Set a reminder for this stock or index. Alerts use the underlying price, not an option premium.</p><form id="tool-alert-form" class="tools-controls"><label>Notify when price is<select id="tool-alert-condition"><option value="above">At or above</option><option value="below">At or below</option></select></label><label>Price in rupees<input id="tool-alert-level" type="number" min="0.01" step="0.01" required></label><button class="button primary" type="submit">Add local alert</button></form><p class="small muted">Alerts last seven days and trigger once. Checks need recent prices. They run on demand or with the open-page auto-check option.</p><div id="stock-alert-list"></div>`;
    await renderStockAlerts();
  }
}
async function loadEntryTool(refresh){
  const version=++tradeTools.request,key=tradeTools.key,holder=$('#entry-tool-result');if(!holder)return;
  holder.innerHTML='<p class="tools-loading">Checking completed candles…</p>';
  try{
    const result=await api('/tools/entry',toolBody(refresh));
    if(version!==tradeTools.request||key!==tradeTools.key||!$('#entry-tool-result'))return;
    const t=result.timing,s=result.scenario;
    $('#entry-tool-result').innerHTML=`<div class="tool-status ${t.status==='TRIGGERED'?'tool-status-triggered':''}"><span class="tip-badge tip-wait">${h(stateLabel(t.status))}</span><p>${h(t.message)}</p>${t.range?`<p class="small">Opening range ${money(t.range.low,2)} – ${money(t.range.high,2)}${t.distance_to_trigger!=null?' · distance to trigger '+money(t.distance_to_trigger,2):''}</p>`:''}${t.signal?`<p class="small">First confirmed ${h(tipTime(t.signal.confirmed_at))} at ${money(t.signal.price,2)}.</p>`:''}<p class="small muted">${h(t.method)} This timing indicator is not a completed trade-plan review.</p></div>
      ${s?`<h3 class="tools-section-title">Exit & position-size scenario</h3>${tipLevels(['Entry reference','Stop-loss','Target'],[s.entry,s.stop,s.target])}<p>${s.quantity} cash-equity practice shares · estimated allocation ${money(s.cash_estimate,2)}<br>Planned loss including costs ${money(s.planned_loss_with_costs,2)} / budget ${money(s.risk_budget,2)}</p>${s.flat_by?`<p>Intraday reminder: plan to exit by ${h(tipTime(s.flat_by))}.</p>`:''}<p class="small muted">${h(s.note)}</p>`:`<p class="note-block">${h(result.scenario_error||'Load history to calculate an exit scenario.')}</p>`}<p class="small muted">Source: ${h(result.source||'History not loaded')} · checked ${h(tipTime(t.generated_at))}</p>`;
    if(t.status==='TRIGGERED'&&tradeTools.signal!==t.signal.confirmed_at&&tradeTools.watch){tradeTools.signal=t.signal.confirmed_at;toast(result.instrument.symbol+': opening-range entry confirmed. Recheck your trade plan.');}
  }catch(err){if(version===tradeTools.request&&$('#entry-tool-result'))$('#entry-tool-result').innerHTML=`<p class="note-block">${h(err.message)}</p>`;stopEntryWatch();const checkbox=$('#tool-watch');if(checkbox)checkbox.checked=false;}
  if(tradeTools.watch&&document.getElementById('trade-toolkit'))tradeTools.timer=setTimeout(()=>{if(document.visibilityState==='visible')loadEntryTool(true);else scheduleEntryWatch();},60000);
}
function scheduleEntryWatch(){if(tradeTools.watch)tradeTools.timer=setTimeout(()=>{if(document.visibilityState==='visible')loadEntryTool(true);else scheduleEntryWatch();},60000);}
async function runToolReplay(button){
  button.disabled=true;const version=tradeTools.request;$('#replay-tool-result').innerHTML='<p class="tools-loading">Replaying historical setups…</p>';
  try{
    const r=await api('/tools/replay',{...toolBody(false),paths:1000,seed:42});if(version!==tradeTools.request||!$('#replay-tool-result'))return;
    const s=r.overall,n=r.recent,mc=r.scenarios;
    $('#replay-tool-result').innerHTML=`<h3 class="tools-section-title">${h(r.method)}</h3><div class="tools-stats"><div><span>Historical trades</span><strong>${s.trades}</strong></div><div><span>Net-positive trades</span><strong>${s.net_positive_rate==null?'No sample':pct(s.net_positive_rate)}</strong></div><div><span>Average after costs</span><strong>${s.average_net_r==null?'No sample':num(s.average_net_r,2)+' R'}</strong></div><div><span>Gap stops</span><strong>${s.gap_stops}</strong></div></div><p class="small">${s.targets} targets · ${s.stops} stops · ${s.timeouts} time exits. ${s.trades<30?'Small sample: do not read a stable win rate into these results.':''}</p>
      <div class="tool-status"><h3>Recent fixed-rule results</h3><p>Last 30% of history: ${n.trades} trades · ${n.average_net_r==null?'No completed trades':num(n.average_net_r,2)+' R average after costs'}.</p><p class="small muted">These historical observations do not supply a probability for the next trade.</p></div>
      ${r.curve.length>1?`<div class="tools-replay-chart">${lineChart([{color:'#a59bff',points:r.curve.map(p=>({x:p.time,y:p.net_r}))}])}</div><p class="small muted">Cumulative net R from non-overlapping historical trades.</p>`:''}
      <h3 class="tools-section-title">Historical scenarios</h3>${mc.available?`<p>${mc.paths} reproducible resamples of ${mc.horizon_trades} historical trade outcomes, using five-trade blocks. Seed ${mc.seed}.</p><div class="tools-replay-chart">${lineChart([{color:'#f58794',points:mc.bands.map(p=>({x:p.trade,y:p.low}))},{color:'#a59bff',points:mc.bands.map(p=>({x:p.trade,y:p.median}))},{color:'#52d6ab',points:mc.bands.map(p=>({x:p.trade,y:p.high}))}])}</div><p class="small">5th / median / 95th percentile cumulative R. Adverse sampled drawdown: ${num(mc.adverse_drawdown_r,2)} R.</p><p class="small muted">${h(mc.definition)}</p>`:`<p>${h(mc.reason)}</p>`}
      <details class="tip-evidence"><summary>Trades, costs & assumptions</summary><p>${h(r.source)} · ${h(tipTime(r.first_bar))} to ${h(tipTime(r.last_bar))}</p><p>Round-trip estimated costs ${r.costs.roundtrip_bps} bps; slippage ${r.costs.slippage_bps_per_side} bps per side.</p>${r.notes.map(t=>`<p>${h(t)}</p>`).join('')}<div class="table-wrap"><table><thead><tr><th>Entry</th><th>Outcome</th><th>Net R</th></tr></thead><tbody>${r.examples.map(e=>`<tr><td>${h(tipTime(e.entry_time))}</td><td>${h(e.reason)}</td><td>${num(e.r_multiple,2)}</td></tr>`).join('')}</tbody></table></div></details>`;
  }catch(err){if(version===tradeTools.request&&$('#replay-tool-result'))$('#replay-tool-result').innerHTML=`<p class="note-block">${h(err.message)}</p>`;}finally{if(button.isConnected)button.disabled=false;}
}
async function loadToolNews(button){
  button.disabled=true;const key=tradeTools.key,version=tradeTools.request;$('#news-tool-result').innerHTML='<p class="tools-loading">Loading India-focused headlines…</p>';
  try{
    const r=await api('/tools/news?instrument_key='+encodeURIComponent(key));if(version!==tradeTools.request||!$('#news-tool-result'))return;
    $('#news-tool-result').innerHTML=`<p class="small muted">${h(r.source)} · ${h(tipTime(r.fetched_at))}</p>${r.items.length?r.items.map(n=>`<article class="tool-headline"><a href="${h(n.url)}" target="_blank" rel="noopener noreferrer">${h(n.title)} ↗</a><p>${h(n.publisher)} · ${h(tipTime(n.published_at))}</p>${n.tags.map(t=>`<span class="tip-badge tip-wait">${h(t)}</span>`).join(' ')}</article>`).join(''):'<p>No matching recent headlines were returned.</p>'}<p class="small muted">${h(r.coverage)}</p><a class="button subtle" href="${h(r.official_url)}" target="_blank" rel="noopener noreferrer">Official company announcements ↗</a>`;
  }catch(err){if(version===tradeTools.request&&$('#news-tool-result'))$('#news-tool-result').innerHTML=`<p class="note-block">${h(err.message)}</p>`;}finally{if(button.isConnected)button.disabled=false;}
}
function alertsMarkup(items){return items.length?items.map(a=>`<div class="tool-alert-row"><div><strong>${h(a.symbol||a.instrument_key)}</strong><p>${a.condition==='above'?'At or above':'At or below'} ${money(a.level,2)} · ${h(a.status)}${a.price?' · seen '+money(a.price,2):''}</p><small>${a.triggered?'Triggered '+h(tipTime(a.triggered)):'Expires '+h(tipTime(a.expires))}</small></div>${a.status==='ACTIVE'?`<button class="button subtle small" data-cancel-local-alert="${h(a.id)}">Cancel</button>`:''}</div>`).join(''):'<p class="small muted">No alerts yet. Open a stock’s Trade toolkit → Price alerts to add one.</p>';}
async function renderStockAlerts(){const key=tradeTools.key,items=await api('/tools/alerts');if($('#stock-alert-list')&&key===tradeTools.key)$('#stock-alert-list').innerHTML=alertsMarkup(items.filter(a=>a.instrument_key===key));}
async function openAlertsCenter(){
  const dialog=toolDialog('alerts-center','My price alerts');dialog.querySelector('[data-tool-dialog-body]').innerHTML=`<p>Follow up to 20 price levels. Each alert triggers once using a recent stock/index snapshot.</p><div class="tip-card-actions"><button class="button primary" data-check-local-alerts>Check prices now</button><label class="inline-check"><input type="checkbox" id="alerts-auto" ${tradeTools.alertAuto?'checked':''}> Auto-check every minute while this app is visible</label></div><p class="small muted">No check runs after the page closes. Alerts do not place stop, target or broker orders.</p><p id="alerts-check-status" role="status"></p><div id="all-local-alerts"></div>`;
  $('#all-local-alerts').innerHTML=alertsMarkup(await api('/tools/alerts'));
}
async function checkLocalAlerts(){
  if(tradeTools.alertBusy)return;tradeTools.alertBusy=true;const button=$('[data-check-local-alerts]');if(button)button.disabled=true;
  try{
    const r=await api('/tools/alerts/check',{});
    for(const alert of r.fired)toast('Price alert: '+(alert.symbol||alert.instrument_key)+' '+(alert.condition==='above'?'at/above ':'at/below ')+money(alert.level,2));
    if($('#alerts-check-status'))$('#alerts-check-status').textContent=r.fired.length+' newly triggered. '+r.unavailable_keys.length+' instruments lacked a recent usable price. Checked '+tipTime(r.checked_at)+'.';
    if($('#all-local-alerts'))$('#all-local-alerts').innerHTML=alertsMarkup(await api('/tools/alerts'));
  }catch(err){if($('#alerts-check-status'))$('#alerts-check-status').textContent=err.message;tradeTools.alertAuto=false;const box=$('#alerts-auto');if(box)box.checked=false;}
  finally{tradeTools.alertBusy=false;if(button?.isConnected)button.disabled=false;}
}
function scheduleAlertCheck(){clearTimeout(tradeTools.alertTimer);if(tradeTools.alertAuto)tradeTools.alertTimer=setTimeout(async()=>{if(document.visibilityState==='visible')await checkLocalAlerts();scheduleAlertCheck();},60000);}
function openPracticeBudget(){
  const s=state.boot.account.settings,dialog=toolDialog('practice-budget','Your practice budget');
  dialog.querySelector('[data-tool-dialog-body]').innerHTML=`<p>Set virtual capital to make share and lot-size checks relevant to your practice account.</p><form id="practice-budget-form"><div class="tools-controls"><label>Virtual capital (₹)<input id="practice-capital" type="number" min="1000" max="10000000" step="100" value="${s.capital}" required></label><label>Risk per trade (%)<input id="practice-risk" type="number" min="0.1" max="1" step="0.1" value="${s.risk_pct}" required></label><label>Maximum allocation (%)<input id="practice-exposure" type="number" min="1" max="25" step="1" value="${s.exposure_pct}" required></label></div><p class="small muted">This changes practice sizing only. Once journal trades exist, starting-capital edits are locked to preserve their results.</p><button class="button primary" type="submit">Save practice budget</button><p id="practice-budget-status" role="status"></p></form>`;
}
document.addEventListener('click',async e=>{
  const tools=e.target.closest('[data-open-tools]');if(tools){try{await openTradeToolkit(tools);}catch(err){toast(err.message,true);}return;}
  const tab=e.target.closest('[data-tool-tab]');if(tab){try{await showToolTab(tab.dataset.toolTab);}catch(err){toast(err.message,true);}return;}
  if(e.target.closest('[data-tool-refresh]')){clearTimeout(tradeTools.timer);await loadEntryTool(true);}
  const replay=e.target.closest('[data-run-replay]');if(replay)await runToolReplay(replay);
  const news=e.target.closest('[data-load-headlines]');if(news)await loadToolNews(news);
  if(e.target.closest('[data-open-alert-center]'))try{await openAlertsCenter();}catch(err){toast(err.message,true);}
  if(e.target.closest('[data-check-local-alerts]'))await checkLocalAlerts();
  const cancel=e.target.closest('[data-cancel-local-alert]');if(cancel){try{await api('/tools/alerts/'+cancel.dataset.cancelLocalAlert+'/cancel',{});if($('#all-local-alerts'))$('#all-local-alerts').innerHTML=alertsMarkup(await api('/tools/alerts'));if($('#stock-alert-list'))await renderStockAlerts();}catch(err){toast(err.message,true);}}
  if(e.target.closest('[data-open-practice-budget]'))openPracticeBudget();
});
document.addEventListener('change',async e=>{
  if(['tool-side','tool-stop','tool-reward'].includes(e.target.id)){tradeTools.side=$('#tool-side').value;clearTimeout(tradeTools.timer);await loadEntryTool(false);}
  if(e.target.id==='tool-watch'){stopEntryWatch();tradeTools.watch=e.target.checked;if(tradeTools.watch)await loadEntryTool(true);}
  if(e.target.id==='alerts-auto'){tradeTools.alertAuto=e.target.checked;if(tradeTools.alertAuto)await checkLocalAlerts();scheduleAlertCheck();}
});
document.addEventListener('submit',async e=>{
  if(e.target.id==='tool-alert-form'){
    e.preventDefault();e.stopImmediatePropagation();const button=e.target.querySelector('button');button.disabled=true;
    try{await api('/tools/alerts',{instrument_key:tradeTools.key,condition:$('#tool-alert-condition').value,level:Number($('#tool-alert-level').value)});await renderStockAlerts();toast('Local price alert added. Use My alerts to check it.');}catch(err){toast(err.message,true);}finally{if(button.isConnected)button.disabled=false;}
  }
  if(e.target.id==='practice-budget-form'){
    e.preventDefault();e.stopImmediatePropagation();const button=e.target.querySelector('button');button.disabled=true;
    try{await api('/tools/budget',{capital:Number($('#practice-capital').value),risk_pct:Number($('#practice-risk').value),exposure_pct:Number($('#practice-exposure').value)});await refreshBoot();document.getElementById('practice-budget').close();discoveryState.result=null;discoveryState.error=null;await renderRecommendations();toast('Practice budget saved. Scan results are being rechecked for the new budget.');}catch(err){if($('#practice-budget-status'))$('#practice-budget-status').textContent=err.message;}finally{if(button.isConnected)button.disabled=false;}
  }
});
