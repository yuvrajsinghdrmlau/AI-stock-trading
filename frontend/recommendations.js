/* Plain-language stock tips. Backend decisions and timestamps remain authoritative. */
const discoveryState={mode:'Intraday',job:null,result:null,busy:false,progress:0,message:'',error:null,request:0};
const tipModes={Intraday:'Today',Swing:'A few days',Delivery:'A few weeks'};

function tipTime(value){
  const date=new Date(value);
  return Number.isFinite(date.getTime())?new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',hour12:true}).format(date)+' IST':'Time unavailable';
}
function tipAge(value){
  const stamp=Date.parse(value);
  if(!Number.isFinite(stamp))return 'Time unavailable';
  const seconds=Math.max(0,Math.floor((Date.now()-stamp)/1000));
  return seconds<60?'Just updated':seconds<3600?Math.floor(seconds/60)+' min old':seconds<86400?Math.floor(seconds/3600)+' hr old':Math.floor(seconds/86400)+' days old';
}
function currentTip(row){
  const plan=row.trade_plan||{};
  const expires=Date.parse(plan.expires_at);
  const buy=plan.decision==='CONDITIONAL_BUY'&&plan.entry&&Number.isFinite(expires)&&expires>Date.now();
  const expired=plan.decision==='EXPIRED'||(plan.decision==='CONDITIONAL_BUY'&&!buy);
  return {plan,buy,expired,label:buy?'BUY SETUP':expired?'EXPIRED':'WAIT'};
}
function bestStockTips(rows){
  const selected=new Map();
  const rank=row=>{const t=currentTip(row);return (t.buy?10000:0)+(row.dataset_id?1000:0)+(row.setup_score||0);};
  for(const row of rows||[]){
    const key=row.instrument?.instrument_key;if(!key)continue;
    const previous=selected.get(key);
    if(!previous||rank(row)>rank(previous))selected.set(key,row);
  }
  return [...selected.values()].sort((a,b)=>rank(b)-rank(a)||String(a.instrument.symbol).localeCompare(String(b.instrument.symbol)));
}
function tipPrice(row){
  const publicQuote=row.public_snapshot,broker=row.quote;
  if(broker?.last_price>0&&broker.fresh){
    return {price:broker.last_price,label:'Broker snapshot',time:broker.feed_time,kind:'broker',source:broker.source||'Connected broker'};
  }
  if(publicQuote?.last_price>0){
    const time=publicQuote.price_time||publicQuote.feed_time;
    const age=Number.isFinite(Date.parse(time))?(Date.now()-Date.parse(time))/1000:null;
    const label=age===null?'Price time unverified':age>900?'Older public price':age>120?'Delayed public price':'Latest public snapshot';
    return {price:publicQuote.last_price,label,time,kind:'public',source:publicQuote.source||'Public market data'};
  }
  const reference=row.trade_plan?.entry?.reference||row.plan?.reference_entry||row.last_close;
  if(reference>0)return {price:reference,label:'Last completed close',time:row.last_bar,kind:'history',source:row.trade_plan?.data_source||'Historical candles'};
  return {price:null,label:'Price unavailable',time:null,kind:'missing',source:publicQuote?.error||'Refresh to request a price'};
}
function tipReason(row){
  const t=currentTip(row);
  if(t.buy)return t.plan.entry.rule==='NEXT_SESSION_OPEN'?'Buy only if the next session opens inside the entry range.':'Buy only if the next 15-minute bar opens inside the entry range.';
  if(t.expired)return 'This entry window has passed. Refresh for the next setup.';
  const reasons=row.trade_plan?(row.trade_plan.reasons||[]):(row.reasons||[]);
  const reason=reasons[0]||'The strategy has no buy setup right now.';
  const plain={
    'Trend does not pass your filter.':'The stock is not in the required upward trend.',
    'The strategy has no entry setup on the last completed candle.':'The latest completed candle does not give an entry signal.',
    'Checklist does not pass your filter.':'Too few entry conditions match right now.',
    'Volume does not pass your filters.':'Trading volume is too low for this setup.',
    'RSI does not pass your filter.':'Momentum is outside this strategy\'s entry range.',
    'The completed close is outside the price filter.':'The stock price is outside the selected range.'
  };
  return plain[reason]||reason;
}
function stockTipCard(row){
  const t=currentTip(row),p=t.plan,e=p.entry,q=tipPrice(row),i=row.instrument;
  const reasons=row.trade_plan?(p.reasons||[]):(row.reasons||[]);
  const strategyName=row.strategy_name||'Entry conditions';
  return `<article class="stock-tip ${t.buy?'stock-tip-buy':''}" data-tip-key="${h(i.instrument_key)}" data-tip-expiry="${t.buy?h(p.expires_at):''}">
    <div class="tip-card-head"><div><h2>${h(i.symbol)}</h2><p>${h(i.name||i.symbol)}</p></div><span class="tip-badge ${t.buy?'tip-buy':'tip-wait'}" data-tip-decision>${t.label}</span></div>
    <div class="tip-price"><strong>${q.price==null?'Unavailable':money(q.price,2)}</strong><div><span data-tip-price-label>${h(q.label)}</span><small data-tip-price-time="${h(q.time||'')}" data-tip-price-kind="${h(q.kind)}">${h(q.time?tipTime(q.time)+' · '+tipAge(q.time):'A price has not arrived yet')}</small></div></div>
    <p class="tip-explanation" data-tip-explanation>${h(tipReason(row))}</p>
    ${t.buy?`<div class="tip-action-levels"><div class="tip-levels"><div><span>Entry reference</span><strong>${money(e.reference,2)}</strong></div><div><span>Stop-loss</span><strong>${money(e.stop_at_reference,2)}</strong></div><div><span>Target</span><strong>${money(e.target_at_reference,2)}</strong></div></div><p class="tip-entry-range">Buy range: <strong>${money(e.min,2)} – ${money(e.max,2)}</strong></p><p class="tip-fill-note">Levels above use ${money(e.reference,2)} entry. For another fill: stop = entry − ${money(e.stop_distance,2)}; target = entry + ${money(e.target_distance,2)}.</p><p class="tip-expiry">Entry: ${h(tipTime(p.entry_window))}<br>Refresh by ${h(tipTime(p.expires_at))}</p></div>`:''}
    <div class="tip-card-actions">${row.dataset_id?`<button class="button ${t.buy?'primary':'subtle'} small" data-review-key="${h(i.instrument_key)}" data-review-strategy="${h(row.strategy)}" data-review-latest="true">${t.buy?'Review & open broker':'View reasons'}</button>`:''}<button class="button subtle small" data-stock="${h(i.instrument_key)}" data-stock-strategy="${h(row.strategy||'trend_pullback')}">View graph</button></div>
    <details class="tip-evidence"><summary>How this tip was calculated</summary><p>${h(strategyName)} · ${h(p.basis==='VALIDATED_MODEL_AND_RULES'?'Model and rules':'Rule-based setup')}</p>${reasons.length?`<ul>${reasons.map(r=>`<li>${h(r)}</li>`).join('')}</ul>`:'<p>The configured entry and risk checks passed.</p>'}<p>Signal candle: ${h(tipTime(row.last_bar||p.last_bar))}</p><p>Price source: ${h(q.source)}${q.kind==='public'?'. Public snapshots may be delayed.':''}</p>${e?`<p>Holding limit: ${e.horizon_bars} bars${e.session_exit_at?' or the same-day session close, whichever comes first':''}.</p>`:''}</details>
  </article>`;
}
async function renderRecommendations(){
  stopDeskTimer();
  const config=await api('/market/config');
  if(state.page!=='recommendations')return;
  marketState.brokers=config.brokers;
  $('#content').innerHTML=`<div class="tips-heading"><div><div class="eyebrow">YOUR STOCK SHORTLIST</div><h1>Trade Tips</h1><p>Choose how long you want to hold. We scan the stocks for you.</p></div><button class="button primary" data-discovery-refresh>${discoveryState.busy?'Scanning…':'Refresh tips'}</button></div><div class="tips-toolbar"><div class="tips-modes" aria-label="Holding period">${Object.entries(tipModes).map(([mode,label])=>`<button data-tip-mode="${mode}" class="${discoveryState.mode===mode?'selected':''}"><strong>${h(label)}</strong><span>${h(mode==='Delivery'?'Longer trades':mode)}</span></button>`).join('')}</div><p>25-stock starter list<br><span>No search or watchlist needed</span></p></div><div id="discovery-progress" role="status" aria-live="polite"></div><div id="tips-summary"></div><div id="stock-tips"></div><details class="tips-scan-details"><summary>Scan details</summary><div id="discovery-basket" class="small muted">Stocks and data coverage appear after the scan.</div></details>`;
  updateDiscoveryControls();
  if(discoveryState.result?.mode===discoveryState.mode)showDiscovery(discoveryState.result);
  if(discoveryState.busy){discoveryProgress(discoveryState.message||'Scanning stocks…',discoveryState.progress);return;}
  if(discoveryState.error){discoveryProgress(discoveryState.error,null,true);return;}
  if(!discoveryState.result||discoveryState.result.mode!==discoveryState.mode)await scanDiscovery(false);
}
function updateDiscoveryControls(){
  for(const button of document.querySelectorAll('[data-discovery-refresh]')){button.disabled=discoveryState.busy;button.textContent=discoveryState.busy?'Scanning…':'Refresh tips';}
  for(const button of document.querySelectorAll('[data-tip-mode]')){button.disabled=discoveryState.busy;button.classList.toggle('selected',button.dataset.tipMode===discoveryState.mode);}
}
function discoveryProgress(message,progress=null,error=false){
  discoveryState.message=message;discoveryState.progress=progress;
  if(state.page!=='recommendations')return;
  const holder=$('#discovery-progress');if(!holder)return;
  holder.innerHTML=message?`<div class="tips-progress ${error?'tips-progress-error':''}"><span>${h(message)}</span>${Number.isFinite(progress)?`<progress max="100" value="${Math.max(0,Math.min(100,progress))}" aria-label="Scan progress"></progress>`:''}</div>`:'';
}
function showDiscovery(result){
  if(state.page!=='recommendations'||result.mode!==discoveryState.mode)return;
  const rows=bestStockTips(result.rows),buys=rows.filter(r=>currentTip(r).buy).length;
  $('#tips-summary').innerHTML=`<div class="tips-result-heading"><div><h2 data-tips-summary-title>${buys?buys+' buy setup'+(buys===1?'':'s')+' to review':'No buy setup right now'}</h2><p data-tips-summary-note>${buys?'Check the entry range before placing a trade.':'The stocks below are waiting for their entry conditions. Refresh after new market data arrives.'}</p></div><small>${rows.length} stocks checked<br>${h(tipTime(result.generated_at))}</small></div>`;
  $('#stock-tips').innerHTML=rows.length?rows.map(stockTipCard).join(''):'<div class="empty-state"><h3>No stocks could be evaluated</h3><p>Refresh tips to retry the data connection.</p></div>';
  const errors=result.errors||[],missing=result.missing_symbols||[];
  $('#discovery-basket').innerHTML=`<p>${h((result.basket_symbols||[]).join(', '))}</p><p>${h(result.scope||'A starter list of up to 25 NSE stocks.')} ${result.refreshed||0} candle histories refreshed.</p>${missing.length?`<p>Listings unavailable: ${h(missing.join(', '))}</p>`:''}${errors.length?`<ul>${errors.map(error=>`<li>${h(error)}</li>`).join('')}</ul>`:''}`;
  discoveryProgress(errors.some(e=>!/No broker token/.test(e))?'Some data updates failed. Available results are shown; see Scan details.':'');
  updateTipFreshness();
}
async function scanDiscovery(refresh){
  if(discoveryState.busy)return;
  discoveryState.busy=true;discoveryState.error=null;discoveryState.result=null;
  const request=++discoveryState.request,mode=discoveryState.mode,started=Date.now();
  if(state.page==='recommendations'){
    $('#stock-tips').innerHTML='';$('#tips-summary').innerHTML='';updateDiscoveryControls();
  }
  discoveryProgress('Checking current prices and loading candles. The first scan can take a few minutes.',0);
  try{
    const launched=await api('/recommendations/scan',{mode,refresh,source:'auto'});
    if(!launched.job_id)throw Error('The scan did not start. Please try again.');
    discoveryState.job=launched.job_id;
    let failures=0;
    const poll=async()=>{
      if(request!==discoveryState.request)return;
      try{
        if(Date.now()-started>15*60*1000)throw Error('The scan is taking too long. Refresh tips to retry.');
        const job=await api('/market/jobs/'+discoveryState.job);failures=0;
        discoveryProgress(job.message||'Scanning stocks…',job.progress||0);
        if(job.status==='running'){setTimeout(poll,1000);return;}
        discoveryState.busy=false;discoveryState.job=null;updateDiscoveryControls();
        if(job.status==='failed')throw Error(job.error||'Data could not be loaded.');
        if(!job.result||!Array.isArray(job.result.rows))throw Error('The service returned an incomplete scan.');
        discoveryState.result=job.result;showDiscovery(job.result);
      }catch(err){
        if(discoveryState.busy&&Date.now()-started<=15*60*1000&&++failures<3){setTimeout(poll,failures*2000);return;}
        discoveryState.busy=false;discoveryState.job=null;discoveryState.error='Unable to finish: '+err.message;
        updateDiscoveryControls();discoveryProgress(discoveryState.error,null,true);
      }
    };setTimeout(poll,400);
  }catch(err){
    discoveryState.busy=false;discoveryState.job=null;discoveryState.error='Unable to start: '+err.message;
    updateDiscoveryControls();discoveryProgress(discoveryState.error,null,true);
  }
}
function updateTipFreshness(){
  if(typeof state==='undefined'||state.page!=='recommendations')return;
  for(const card of document.querySelectorAll('[data-tip-expiry]')){
    const expiry=Date.parse(card.dataset.tipExpiry);
    if(Number.isFinite(expiry)&&Date.now()>=expiry){
      card.dataset.tipExpiry='';card.classList.remove('stock-tip-buy');
      const badge=card.querySelector('[data-tip-decision]');badge.textContent='EXPIRED';badge.className='tip-badge tip-wait';
      card.querySelector('.tip-action-levels')?.remove();
      card.querySelector('[data-tip-explanation]').textContent='This plan or its price snapshot has expired. Refresh tips before deciding.';
      const review=card.querySelector('[data-review-key]');if(review){review.textContent='Recheck setup';review.classList.remove('primary');review.classList.add('subtle');}
    }
    const priceTime=card.querySelector('[data-tip-price-time]');if(priceTime?.dataset.tipPriceTime){
      const time=priceTime.dataset.tipPriceTime;priceTime.textContent=tipTime(time)+' · '+tipAge(time);
      const age=(Date.now()-Date.parse(time))/1000,label=card.querySelector('[data-tip-price-label]');
      if(priceTime.dataset.tipPriceKind==='public'&&age>120)label.textContent=age>900?'Older public price':'Delayed public price';
      if(priceTime.dataset.tipPriceKind==='broker'&&age>60)label.textContent='Broker snapshot expired';
    }
  }
  const count=document.querySelectorAll('.stock-tip-buy').length,title=$('[data-tips-summary-title]'),note=$('[data-tips-summary-note]');
  if(title){title.textContent=count?count+' buy setup'+(count===1?'':'s')+' to review':'No buy setup right now';if(!count&&note)note.textContent='The stocks below are waiting for their entry conditions. Refresh after new market data arrives.';}
}
document.addEventListener('click',e=>{
  if(e.target.closest('[data-discovery-refresh]'))scanDiscovery(true);
  const button=e.target.closest('[data-tip-mode]');
  if(button&&!discoveryState.busy&&button.dataset.tipMode!==discoveryState.mode){
    discoveryState.mode=button.dataset.tipMode;discoveryState.error=null;scanDiscovery(false);
  }
});
setInterval(updateTipFreshness,1000);
