/* Beginner trading desk. Source times and server decisions remain authoritative. */
const discoveryState={mode:'Delivery',scope:'nifty500',holding:'Intraday',job:null,result:null,busy:false,progress:0,message:'',error:null,request:0,limit:12,filter:'setups',query:''};
const tipModes={Delivery:['Delivery','Buy shares; hold for weeks'],Intraday:['Intraday','Buy shares; exit the same day'],Swing:['Swing','Hold shares for a few days'],Options:['Calls & puts','Options on stocks and indices'],Futures:['Futures','Buy or sell a listed futures contract']};
const tipScopes={nifty500:'Nifty 500 · broad market',nifty200:'Nifty 200',nifty100:'Nifty 100',nifty50:'Nifty 50',all_nse:'All regular NSE stocks',fo:'All NSE F&O stocks & indices'};
function tipTime(value){
  if(!value)return 'Time unavailable';
  const date=new Date(value);
  return Number.isFinite(date.getTime())?new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',hour12:true}).format(date)+' IST':'Time unavailable';
}
function tipAge(value){
  const stamp=Date.parse(value);if(!Number.isFinite(stamp))return 'Time unavailable';
  const seconds=Math.max(0,Math.floor((Date.now()-stamp)/1000));
  return seconds<60?'Just updated':seconds<3600?Math.floor(seconds/60)+' min old':seconds<86400?Math.floor(seconds/3600)+' hr old':Math.floor(seconds/86400)+' days old';
}
function currentTip(row){
  if(row.idea){
    const p=row.idea,expired=!!p.expires_at&&Date.parse(p.expires_at)<=Date.now();
    const buy=p.decision==='REVIEW_TRADE'&&!expired;
    const setup=!!p.action&&!!p.underlying_levels&&!expired;
    const label=expired?'RECHECK':buy?'TRADE TO REVIEW':p.decision==='BUDGET_TOO_SMALL'?'PRACTISE ONLY':setup?(p.action==='BUY_CALL'?'CALL IDEA':p.action==='BUY_PUT'?'PUT IDEA':'FUTURES IDEA'):'WAIT';
    return {plan:p,buy,setup,expired,label};
  }
  const p=row.trade_plan||{},expires=Date.parse(p.expires_at);
  const buy=p.decision==='CONDITIONAL_BUY'&&p.entry&&Number.isFinite(expires)&&expires>Date.now();
  const expired=p.decision==='EXPIRED'||(p.decision==='CONDITIONAL_BUY'&&!buy);
  return {plan:p,buy,setup:buy,expired,label:buy?'BUY SETUP':expired?'RECHECK':'WAIT'};
}
function bestStockTips(rows){
  const selected=new Map();
  const rank=row=>{const t=currentTip(row);return (t.buy?10000:0)+(t.setup?5000:0)+(row.dataset_id?1000:0)+(row.setup_score||0);};
  for(const row of rows||[]){const key=row.instrument?.instrument_key;if(!key)continue;const previous=selected.get(key);if(!previous||rank(row)>rank(previous))selected.set(key,row);}
  return [...selected.values()].sort((a,b)=>rank(b)-rank(a)||String(a.instrument.symbol).localeCompare(String(b.instrument.symbol)));
}
function tipPrice(row){
  const q=row.public_snapshot,b=row.quote;
  if(b?.last_price>0&&b.fresh)return {price:b.last_price,label:'Broker snapshot',time:b.feed_time,source:b.source};
  if(q?.last_price>0){const age=(Date.now()-Date.parse(q.price_time))/1000;return {price:q.last_price,label:age>900?'Older public price':age>120?'Delayed public price':'Public price snapshot',time:q.price_time,source:q.source};}
  const reference=row.trade_plan?.entry?.reference||row.plan?.reference_entry||row.last_close;
  return {price:reference>0?reference:null,label:reference>0?'Last completed close':'Price unavailable',time:row.last_bar,source:row.trade_plan?.data_source||'Completed candles'};
}
function tipReason(row){
  const t=currentTip(row);if(row.idea)return t.expired?'The snapshot expired. Recheck this idea for current prices.':row.idea.reasons?.[0]||'Waiting for a setup.';
  if(t.buy)return t.plan.entry.rule==='NEXT_SESSION_OPEN'?'Buy only if the next session opens inside the entry range.':'Buy only if the next 15-minute candle opens inside the entry range.';
  if(t.expired)return 'The entry window passed. Refresh to check a new setup.';
  const reason=t.plan.reasons?.[0]||row.reasons?.[0]||'The entry conditions do not match yet.';
  const plain={'Trend does not pass your filter.':'The stock is not in the required upward trend.','The strategy has no entry setup on the last completed candle.':'The latest candle does not confirm a buy.','Checklist does not pass your filter.':'Too few entry conditions match.','Volume does not pass your filters.':'Trading volume is too low for this setup.','RSI does not pass your filter.':'Momentum is outside the entry range.','The local paper account cannot fit this plan within its risk limits.':'This trade does not fit your practice account’s cash or risk limit.'};
  return plain[reason]||reason;
}
function tipLevels(labels,values){return `<div class="tip-levels">${labels.map((label,j)=>`<div><span>${h(label)}</span><strong>${values[j]==null?'Not available':money(values[j],2)}</strong></div>`).join('')}</div>`;}
function tipMiniChart(row){const values=row.spark||[];return values.length>1?`<div class="tip-mini-chart">${spark(values,values.at(-1)>=values[0]).replace('viewBox=','preserveAspectRatio="none" viewBox=')}<small>Last ${values.length} completed closes</small></div>`:'';}
function stockTipCard(row){
  const t=currentTip(row),p=t.plan,i=row.instrument,q=tipPrice(row),e=p.entry;
  return `<article class="stock-tip ${t.buy?'stock-tip-buy':''}" data-tip-key="${h(i.instrument_key)}" data-tip-expiry="${t.buy?h(p.expires_at):''}">
    <div class="tip-card-head"><div><h2>${h(i.symbol)}</h2><p>${h(i.name||i.symbol)}</p></div><span class="tip-badge ${t.buy?'tip-buy':'tip-wait'}" data-tip-decision>${h(t.label)}</span></div>
    <div class="tip-price"><strong>${q.price==null?'Unavailable':money(q.price,2)}</strong><div><span>${h(q.label)}</span><small>${h(q.time?tipTime(q.time)+' · '+tipAge(q.time):'Refresh to request market data')}</small></div></div>
    ${tipMiniChart(row)}<p class="tip-explanation" data-tip-explanation>${h(tipReason(row))}</p>
    ${t.buy?`<div class="tip-action-levels">${tipLevels(['Buy reference','Stop-loss','Target'],[e.reference,e.stop_at_reference,e.target_at_reference])}<p>Buy range: <strong>${money(e.min,2)} – ${money(e.max,2)}</strong></p><p class="small">${row.plan?.quantity||0} shares in the practice account · planned loss ${money(row.plan?.planned_loss_with_estimated_costs||0,2)}</p><p class="tip-expiry">Entry ${h(tipTime(p.entry_window))} · recheck by ${h(tipTime(p.expires_at))}</p><p class="small muted">At another fill: stop = entry − ${money(e.stop_distance,2)}; target = entry + ${money(e.target_distance,2)}.</p></div>`:''}
    <div class="tip-card-actions">${row.dataset_id?`<button class="button ${t.buy?'primary':'subtle'}" data-review-key="${h(i.instrument_key)}" data-review-strategy="${h(row.strategy)}" data-review-latest="true">${t.buy?'Review trade':'Why wait?'}</button>`:''}<button class="button subtle" data-stock="${h(i.instrument_key)}" data-stock-strategy="${h(row.strategy||'trend_pullback')}">See chart</button></div>
    <details class="tip-evidence"><summary>Signal details</summary><p>${h(row.strategy_name||'Entry conditions')} · ${h(p.basis==='VALIDATED_MODEL_AND_RULES'?'Model and rules':'Technical rules')}</p><p>Signal candle: ${h(tipTime(row.last_bar))}</p><p>Source: ${h(q.source||'Unavailable')}</p>${(p.reasons||[]).map(r=>`<p>${h(r)}</p>`).join('')}</details></article>`;
}
function derivativeTipCard(row){
  const t=currentTip(row),p=row.idea,i=row.instrument,c=p.contract,u=p.underlying_levels,l=p.contract_levels,q=tipPrice(row);
  const action={BUY_CALL:'Buy call (CE)',BUY_PUT:'Buy put (PE)',BUY_FUTURE:'Buy futures',SELL_FUTURE:'Sell futures'}[p.action]||'Wait for a direction';
  return `<article class="stock-tip ${t.buy?'stock-tip-buy':t.setup?'stock-tip-idea':''}" data-tip-key="${h(i.instrument_key)}" data-tip-expiry="${p.expires_at?h(p.expires_at):''}">
    <div class="tip-card-head"><div><h2>${h(i.symbol)}</h2><p>${h(action)}</p></div><span class="tip-badge ${t.buy?'tip-buy':'tip-wait'}" data-tip-decision>${h(t.label)}</span></div>
    <p class="small muted">Underlying ${q.price==null?'price unavailable':money(q.price,2)} · ${h(q.label)}<br>${h(q.time?tipTime(q.time):'')}</p>
    ${tipMiniChart(row)}<p class="tip-explanation" data-tip-explanation>${h(tipReason(row))}</p>
    ${c?`<div class="tip-contract"><strong>${h(c.symbol)}</strong><span>Expiry ${h(c.expiry)} · ${c.lot_size} units per lot${c.strike?' · strike '+money(c.strike,2):''}</span></div>`:''}
    ${l&&!t.expired?`<div class="tip-action-levels"><p class="tip-level-caption">${row.mode==='Options'?'Option premium':'Futures price'} per unit</p>${tipLevels(['Entry reference','Stop-loss','Target'],[l.entry,l.stop,l.target])}<p>1 lot = ${l.quantity} units · planned stop risk ${money(l.planned_risk,2)}</p>${l.premium_cost?`<p>Premium to pay: ${money(l.premium_cost,2)}<br>Full premium at risk: ${money(l.maximum_premium_loss,2)}</p>`:'<p>Check required futures margin on your broker.</p>'}<p class="small muted">${h(l.basis)}. Gaps can exceed the planned stop loss.</p></div>`:u?`<div class="tip-underlying"><p class="tip-level-caption">Underlying trigger · these are ${h(i.symbol)} levels</p>${tipLevels([u.side==='ABOVE'?'Cross above':'Cross below','Invalidation','Target'],[u.trigger,u.stop,u.target])}<p class="small muted">${row.mode==='Options'?'These numbers are stock/index levels, not option premiums.':'These numbers are stock/index levels, not futures entry prices.'}</p></div>`:''}
    <div class="tip-card-actions"><button class="button ${t.buy?'primary':'subtle'}" data-derivative-review="${h(i.instrument_key)}">${t.buy?'Recheck & review trade':'Check contract & next steps'}</button><button class="button subtle" data-stock="${h(i.instrument_key)}" data-stock-strategy="${h(row.strategy)}">See chart</button></div>
    <details class="tip-evidence"><summary>Why this direction?</summary><p>${p.direction==='UP'?'Upward':p.direction==='DOWN'?'Downward':'No confirmed'} trend. EMA trend, RSI momentum and a confirming candle must agree. Stock volume must pass; index volume is not used.</p><p>Signal candle ${h(tipTime(row.last_bar))}. This rules match is not a measured probability of profit.</p><p>Contract selection uses listed expiries at least seven days away and a strike closest to the underlying price. Quotes can select another nearby liquid strike.</p></details></article>`;
}
function beginnerGuide(){return `<details class="tips-guide"><summary>New to trading? Start here <span>What these trade types and numbers mean</span></summary><div class="tips-guide-grid"><div><h3>1. Pick a trade type</h3><p><strong>Delivery:</strong> own shares and hold them for weeks. <strong>Swing:</strong> hold shares for days. <strong>Intraday:</strong> close the trade the same day.</p><p><strong>Call:</strong> an option that benefits from an upward move. <strong>Put:</strong> an option that benefits from a downward move. <strong>Futures:</strong> a leveraged contract you can buy or sell.</p></div><div><h3>2. Read the plan</h3><p><strong>Entry:</strong> where the setup allows a trade. <strong>Stop-loss:</strong> the exit level if it moves against you. <strong>Target:</strong> the planned profit-taking level.</p><p><strong>Lot:</strong> the minimum number of F&O units in one contract. Options can lose the full premium; futures require margin and can lose more than it.</p></div><div><h3>3. Practise, then use your broker</h3><p>Begin with Delivery and a small practice position. A WAIT card means the conditions do not match; it is useful to skip a trade.</p><p>Recheck current prices, expiry and quantity on your own broker. Entry, stop and target orders must be placed there. A stop price does not guarantee a fill.</p></div></div></details>`;}
async function renderRecommendations(){
  stopDeskTimer();const config=await api('/market/config');if(state.page!=='recommendations')return;marketState.brokers=config.brokers;
  const derivatives=['Options','Futures'].includes(discoveryState.mode);
  $('#content').innerHTML=`${config.catalogue.source_headers?.fixture?'<div class="banner"><p>OFFLINE UI TEST: fictional listings and prices, used to verify the interface.</p></div>':''}<div class="tips-heading"><div><div class="eyebrow">A CLEAR PLAN BEFORE EVERY TRADE</div><h1>Your trade ideas</h1><p>Choose your trade type. We find setups across the market for you.</p></div><button class="button primary" data-discovery-refresh>Find trade ideas</button></div>
    <div class="tips-modes" aria-label="Trade type">${Object.entries(tipModes).map(([mode,[label,description]])=>`<button data-tip-mode="${mode}" class="${discoveryState.mode===mode?'selected':''}"><strong>${h(label)}</strong><span>${h(description)}</span></button>`).join('')}</div>
    <div class="tips-toolbar"><label for="tips-universe">Stocks to scan<select id="tips-universe">${Object.entries(tipScopes).map(([key,label])=>`<option value="${key}" ${key===discoveryState.scope?'selected':''}>${h(label)}</option>`).join('')}</select></label>${derivatives?`<label for="tips-holding">Time horizon<select id="tips-holding"><option value="Intraday" ${discoveryState.holding==='Intraday'?'selected':''}>Today · check entry & contract price</option><option value="Swing" ${discoveryState.holding==='Swing'?'selected':''}>Next session · trend ideas</option></select></label>`:''}<p>No watchlist or individual search needed.<br><span>Practice capital ${money(state.boot.account.settings.capital)} · risk per trade ${state.boot.account.settings.risk_pct}%</span></p></div>
    ${beginnerGuide()}<div id="discovery-progress" role="status" aria-live="polite"></div><div id="tips-summary"></div>
    <div class="tips-results-controls"><label for="tips-view">Show<select id="tips-view"><option value="setups">Trade setups first</option><option value="ready">Ready to review</option><option value="all">All checked stocks</option></select></label><label for="tips-search">Find in results<input id="tips-search" type="search" placeholder="Stock or company name" value="${h(discoveryState.query)}"></label></div><div id="stock-tips"></div><div id="tips-more"></div>
    <details class="tips-scan-details"><summary>Coverage & data sources</summary><div id="discovery-basket">Start a scan to see stock coverage.</div></details>`;
  $('#tips-view').value=discoveryState.filter;updateDiscoveryControls();
  if(discoveryState.result)showDiscovery(discoveryState.result);
  if(discoveryState.busy){discoveryProgress(discoveryState.message,discoveryState.progress);return;}
  if(discoveryState.error)discoveryProgress(discoveryState.error,null,true);
  if(!discoveryState.result&&!discoveryState.error)await scanDiscovery(false);
}
function updateDiscoveryControls(){
  for(const b of document.querySelectorAll('[data-discovery-refresh]')){b.disabled=discoveryState.busy;b.textContent=discoveryState.busy?'Scanning…':'Find / refresh trade ideas';}
  for(const b of document.querySelectorAll('[data-tip-mode]')){b.disabled=discoveryState.busy;b.classList.toggle('selected',b.dataset.tipMode===discoveryState.mode);}
  for(const id of ['tips-universe','tips-holding']){const el=document.getElementById(id);if(el)el.disabled=discoveryState.busy;}
}
function discoveryProgress(message,progress=null,error=false){
  discoveryState.message=message;discoveryState.progress=progress;
  if(state.page!=='recommendations')return;const holder=$('#discovery-progress');if(!holder)return;
  holder.innerHTML=message?`<div class="tips-progress ${error?'tips-progress-error':''}"><div><span>${h(message)}</span>${discoveryState.busy&&discoveryState.job?'<button class="button subtle small" data-stop-scan>Stop after this batch</button>':''}</div>${Number.isFinite(progress)?`<progress max="100" value="${Math.max(0,Math.min(100,progress))}" aria-label="Scan progress"></progress>`:''}</div>`:'';
}
function showDiscovery(result){
  if(state.page!=='recommendations'||result.mode!==discoveryState.mode)return;
  const all=bestStockTips(result.rows),buys=all.filter(r=>currentTip(r).buy).length,setups=all.filter(r=>currentTip(r).setup).length;
  const complete=result.complete!==false||result.cancelled;
  $('#tips-summary').innerHTML=`<div class="tips-result-heading"><div><h2 data-tips-summary-title>${buys?buys+' trade'+(buys===1?'':'s')+' to review':setups?setups+' direction idea'+(setups===1?'':'s')+' to check':complete?'No entry setup right now':'Finding setups across the market…'}</h2><p>${buys?'Open a plan and recheck the current entry price.':setups?'An underlying direction is a starting point. Open a card to check the contract and entry conditions.':'WAIT means the entry conditions do not match. You do not need to force a trade.'}</p></div><div class="tips-coverage"><strong>${result.processed??all.length} / ${result.total??all.length}</strong><span>stocks checked${complete?'':' · scan in progress'}</span><small>${result.with_history??all.filter(r=>r.dataset_id).length} with candle data</small></div></div>`;
  let rows=all;
  if(discoveryState.filter==='ready')rows=rows.filter(r=>currentTip(r).buy);
  if(discoveryState.query.trim()){const query=discoveryState.query.trim().toLowerCase();rows=rows.filter(r=>(r.instrument.symbol+' '+r.instrument.name).toLowerCase().includes(query));}
  const ideas=rows.filter(r=>currentTip(r).setup);
  const display=discoveryState.filter==='setups'&&ideas.length?ideas:rows;
  $('#stock-tips').innerHTML=display.length?display.slice(0,discoveryState.limit).map(r=>r.idea?derivativeTipCard(r):stockTipCard(r)).join(''):`<div class="empty-state"><h3>${discoveryState.filter==='ready'?'No trade is ready to review':'No matching results yet'}</h3><p>${discoveryState.busy?'Results appear after each batch of stocks.':'Try All checked stocks to see why stocks are waiting, or refresh after new candles arrive.'}</p></div>`;
  $('#tips-more').innerHTML=display.length>discoveryState.limit?`<button class="button subtle" data-more-tips>Show 12 more (${display.length-discoveryState.limit} remaining)</button>`:'';
  const errors=result.errors||[],coverage=result.coverage||{};
  $('#discovery-basket').innerHTML=`<p><strong>${h(result.scope||tipScopes[discoveryState.scope])}</strong>. ${result.refreshed||0} histories refreshed. ${h(tipTime(result.generated_at))}.</p>${coverage.fallback?'<p>Official index membership was unavailable. This scan uses all eligible NSE listings.</p>':''}${coverage.membership_as_of?`<p>Membership downloaded ${h(tipTime(coverage.membership_as_of))}.</p>`:''}${coverage.source?`<p>Membership/catalogue source: ${h(coverage.source)}</p>`:''}<p>Quotes are individual snapshots taken during the scan, not simultaneous market-wide prices. Recheck a card for a new price.</p><p>${h((result.basket_symbols||[]).join(', '))}</p>${result.missing_symbols?.length?`<p>Members unavailable in the catalogue: ${h(result.missing_symbols.join(', '))}</p>`:''}${errors.length?`<details><summary>${errors.length} data notes / unavailable sources</summary>${errors.slice(0,100).map(e=>`<p>${h(e)}</p>`).join('')}</details>`:''}`;
  updateTipFreshness();
}
async function scanDiscovery(refresh){
  if(discoveryState.busy)return;
  discoveryState.busy=true;discoveryState.error=null;discoveryState.result=null;discoveryState.limit=12;
  const request=++discoveryState.request,started=Date.now();updateDiscoveryControls();
  if(state.page==='recommendations'){$('#stock-tips').innerHTML='';$('#tips-summary').innerHTML='';$('#tips-more').innerHTML='';}
  discoveryProgress('Loading the selected universe. Large first scans can take several minutes; results appear in batches.',0);
  try{
    const launched=await api('/recommendations/scan',{mode:discoveryState.mode,scope:discoveryState.scope,holding:discoveryState.holding,refresh,source:'auto'});
    discoveryState.job=launched.job_id;if(!launched.job_id)throw Error('The scan did not start.');
    let failures=0,lastProcessed=-1;
    const poll=async()=>{
      if(request!==discoveryState.request)return;
      try{
        const job=await api('/market/jobs/'+discoveryState.job+'?after_processed='+lastProcessed);failures=0;
        discoveryProgress(job.message||'Checking stocks…',job.progress||0);
        if(job.result&&job.result.processed!==lastProcessed){lastProcessed=job.result.processed;discoveryState.result=job.result;showDiscovery(job.result);}
        if(job.status==='running'){setTimeout(poll,1500);return;}
        discoveryState.busy=false;discoveryState.job=null;updateDiscoveryControls();
        if(job.status==='failed')throw Error(job.error||'The data request failed.');
        if(!job.result||!Array.isArray(job.result.rows))throw Error('The service returned an incomplete scan.');
        discoveryState.result=job.result;showDiscovery(job.result);
        discoveryProgress(job.result.cancelled?'Scan stopped. Completed batches are shown.':`Scan complete. ${job.result.processed} stocks checked in ${Math.ceil((Date.now()-started)/60000)} minute(s).`);
      }catch(err){
        if(discoveryState.busy&&++failures<3){setTimeout(poll,failures*2000);return;}
        discoveryState.busy=false;discoveryState.job=null;discoveryState.error=err.message;updateDiscoveryControls();discoveryProgress(err.message,null,true);
      }
    };setTimeout(poll,400);
  }catch(err){discoveryState.busy=false;discoveryState.job=null;discoveryState.error=err.message;updateDiscoveryControls();discoveryProgress(err.message,null,true);}
}
function updateTipFreshness(){
  if(typeof state==='undefined'||state.page!=='recommendations')return;
  for(const card of document.querySelectorAll('[data-tip-expiry]')){
    const expiry=Date.parse(card.dataset.tipExpiry);if(!Number.isFinite(expiry)||Date.now()<expiry)continue;
    card.dataset.tipExpiry='';card.classList.remove('stock-tip-buy','stock-tip-idea');
    const badge=card.querySelector('[data-tip-decision]');badge.textContent='RECHECK';badge.className='tip-badge tip-wait';
    card.querySelector('.tip-action-levels')?.remove();card.querySelector('[data-tip-explanation]').textContent='The price snapshot expired. Recheck this idea for current prices.';
  }
  if(discoveryState.result){
    const all=bestStockTips(discoveryState.result.rows),ready=all.filter(r=>currentTip(r).buy).length,ideas=all.filter(r=>currentTip(r).setup).length;
    const title=$('[data-tips-summary-title]');if(title)title.textContent=ready?ready+' trade'+(ready===1?'':'s')+' to review':ideas?ideas+' direction idea'+(ideas===1?'':'s')+' to check':discoveryState.busy?'Finding setups across the market…':'No entry setup right now';
  }
  const dialog=document.getElementById('derivative-review');
  if(dialog?.dataset.expiry&&Date.parse(dialog.dataset.expiry)<=Date.now()){
    dialog.querySelector('[data-derivative-status]').textContent='Snapshot expired. Recheck this idea before an order.';
    dialog.querySelector('.tip-action-levels')?.remove();dialog.dataset.expiry='';
  }
}
async function reviewDerivative(key,button){
  button.disabled=true;
  try{
    const row=await api('/recommendations/review-derivative',{instrument_key:key,product:discoveryState.mode,holding:discoveryState.holding});
    document.getElementById('derivative-review')?.remove();
    const dialog=document.createElement('dialog');dialog.id='derivative-review';dialog.className='trade-review';dialog.dataset.expiry=row.idea.expires_at||'';
    dialog.innerHTML=`<div class="panel-head"><h2>Review your ${row.mode==='Options'?'option':'futures'} idea</h2><button class="icon-button" data-close-derivative aria-label="Close plan">×</button></div><div class="panel-body"><p data-derivative-status>${h(row.idea.decision==='REVIEW_TRADE'?'Checks passed for manual review. No order has been placed.':tipReason(row))}</p>${derivativeTipCard(row)}<div class="tips-next-steps"><h3>What to do next</h3><ol><li>Open your broker and search the exact contract shown above.</li><li>Match the expiry, call/put type, strike and lot size.</li><li>${row.idea.contract_levels?'Recheck the entry and spread, then enter your quantity and place your own stop and target orders.':'Check the current premium or futures quote. The underlying levels are not contract entry prices.'}</li><li>Use a practice trade if one lot does not fit your budget.</li></ol></div><div class="tip-card-actions">${(marketState.brokers||[]).map(b=>`<a class="button subtle" href="${h(b.url)}" target="_blank" rel="noopener noreferrer">Open ${h(b.name)} ↗</a>`).join('')}</div>${(row.data_errors||[]).map(e=>`<p>${h(e)}</p>`).join('')}<p class="small muted">Stock options and stock futures can require physical settlement near expiry. Check the broker’s exit deadline. This idea does not assess news or company events.</p></div>`;
    dialog.querySelector('[data-derivative-review]')?.remove();dialog.querySelector('[data-stock]')?.remove();
    dialog.addEventListener('click',e=>{if(e.target===dialog||e.target.closest('[data-close-derivative]'))dialog.close();});dialog.addEventListener('close',()=>dialog.remove());
    document.body.append(dialog);dialog.showModal();updateTipFreshness();
    if(discoveryState.result){const idx=discoveryState.result.rows.findIndex(r=>r.instrument.instrument_key===key);if(idx>=0)discoveryState.result.rows[idx]=row;showDiscovery(discoveryState.result);}
  }catch(err){toast(err.message,true);}finally{if(button.isConnected)button.disabled=false;}
}
document.addEventListener('click',async e=>{
  if(e.target.closest('[data-discovery-refresh]'))scanDiscovery(true);
  const mode=e.target.closest('[data-tip-mode]');
  if(mode&&!discoveryState.busy&&mode.dataset.tipMode!==discoveryState.mode){discoveryState.mode=mode.dataset.tipMode;discoveryState.result=null;discoveryState.error=null;await renderRecommendations();}
  if(e.target.closest('[data-more-tips]')){discoveryState.limit+=12;showDiscovery(discoveryState.result);}
  const review=e.target.closest('[data-derivative-review]');if(review)reviewDerivative(review.dataset.derivativeReview,review);
  const stop=e.target.closest('[data-stop-scan]');if(stop&&discoveryState.job){stop.disabled=true;try{await api('/market/jobs/'+discoveryState.job+'/cancel',{});discoveryProgress('Stopping after the current batch…',discoveryState.progress);}catch(err){toast(err.message,true);}}
});
document.addEventListener('change',async e=>{
  if(e.target.id==='tips-universe'||e.target.id==='tips-holding'){
    if(discoveryState.busy)return;discoveryState[e.target.id==='tips-universe'?'scope':'holding']=e.target.value;discoveryState.result=null;discoveryState.error=null;await renderRecommendations();
  }
  if(e.target.id==='tips-view'){discoveryState.filter=e.target.value;discoveryState.limit=12;if(discoveryState.result)showDiscovery(discoveryState.result);}
});
document.addEventListener('input',e=>{if(e.target.id==='tips-search'){discoveryState.query=e.target.value;discoveryState.limit=12;if(discoveryState.result)showDiscovery(discoveryState.result);}});
setInterval(updateTipFreshness,1000);
