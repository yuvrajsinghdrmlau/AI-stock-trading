/* Conditional research plans; broker links only open the user's own platform. */
function dataAccessView(config){
  return `<section class="panel data-access"><details><summary>Choose your data source <span>No personal API? Public history and CSV work now.</span></summary><div class="panel-body">
    <label for="history-source">Candle source</label><select id="history-source" class="select-inline">
      <option value="auto" ${marketState.historySource==='auto'?'selected':''}>Automatic: broker when configured, otherwise public history</option>
      <option value="public" ${marketState.historySource==='public'?'selected':''}>Public historical candles (no broker key)</option>
      <option value="broker" ${marketState.historySource==='broker'?'selected':''} ${config.upstox_configured?'':'disabled'}>My authorized Upstox history</option>
    </select><div class="data-options">${config.data_options.map(o=>`<div><strong>${h(o.name)}</strong><p>${h(o.description)}</p>${o.url?`<a href="${h(o.url)}" target="_blank" rel="noopener noreferrer">Official data options ↗</a>`:''}</div>`).join('')}</div>
    <p class="tiny muted">Official exchange websites can be checked in your browser. This app does not scrape them or treat their displayed prices as a licensed live feed.</p></div></details></section>`;
}

function tradePlanView(row){
  const p=row.trade_plan||{},e=p.entry;
  if(!p.decision)return '';
  return `<div class="trade-plan" data-plan-expiry="${h(p.expires_at||'')}">
    <div class="row-flex"><strong data-plan-decision>${h(stateLabel(p.decision))}</strong><span class="tiny muted" data-plan-evidence>${p.live_qualified?'BROKER + MODEL CHECKS PASS':'MANUAL REVIEW REQUIRED'}</span></div>
    ${e?`<div class="trade-entry"><p class="trade-entry-range">Next-open range <strong>${money(e.min,2)} – ${money(e.max,2)}</strong></p>
    <div class="mini-plan"><span>Reference close<strong>${money(e.reference,2)}</strong></span><span>Stop at reference<strong>${money(e.stop_at_reference,2)}</strong></span><span>Target at reference<strong>${money(e.target_at_reference,2)}</strong></span><span>Reward / risk<strong>${num(e.reward_r,1)} R</strong></span></div>
    <p class="tiny">Actual fill − ${money(e.stop_distance,2)} = stop. Actual fill + ${money(e.target_distance,2)} = target. ${e.session_exit_at?`Exit at the earlier of ${e.horizon_bars} bars or 15:30 IST on the signal day if neither level is reached. Verify the actual session; do not carry this intraday plan overnight.`:`Review after ${e.horizon_bars} bars if neither is reached.`}</p>
    <p class="small">${h(e.instruction)}</p></div>`:`<p class="small">${h(p.reasons?.[0]||row.reasons?.[0]||'Load completed history before building a plan.')}</p>`}
    ${p.entry_window?`<p class="tiny muted">Entry window: ${h(p.entry_window.slice(0,16).replace('T',' '))} to ${h((p.entry_window_ends_at||p.expires_at).slice(11,19))} IST. Plan expires / recheck by ${h(p.expires_at.slice(11,19))} IST. Exchange holidays require confirmation.</p>`:''}
    ${p.data_source?`<p class="tiny muted">${h(p.data_source)} · ${h(stateLabel(p.basis))}</p>`:''}
  </div>`;
}

function expireTradePlans(){
  for(const el of document.querySelectorAll('[data-plan-expiry]')){
    const expiry=Date.parse(el.dataset.planExpiry);
    if(Number.isFinite(expiry)&&Date.now()>=expiry&&el.querySelector('.trade-entry')){
      el.querySelector('[data-plan-decision]').textContent='EXPIRED';
      el.querySelector('[data-plan-evidence]').textContent='RECHECK REQUIRED';
      el.querySelector('.trade-entry').outerHTML='<p class="small">This plan or its broker snapshot has expired. Recheck the plan before reviewing any entry.</p>';
      const card=el.closest('.candidate-card'),dialog=el.closest('#trade-review');
      if(card){card.classList.remove('candidate-pass');card.querySelector('[data-card-decision]').innerHTML=marketPill('EXPIRED');}
      if(dialog){const copy=dialog.querySelector('[data-plan-copy]');copy.disabled=true;copy.dataset.expired='true';}
    }
  }
  const rows=marketState.board?.rows||[];
  const current=rows.filter(r=>r.trade_plan?.decision==='CONDITIONAL_BUY'&&Date.parse(r.trade_plan.expires_at)>Date.now());
  const count=document.getElementById('conditional-plan-count'),qualified=document.getElementById('qualified-plan-count');
  if(count)count.textContent=current.length;
  if(qualified)qualified.textContent=current.filter(r=>r.trade_plan.live_qualified).length;
}

function showTradeReview(row){
  document.getElementById('trade-review')?.remove();
  const p=row.trade_plan||{},i=row.instrument;
  const dialog=document.createElement('dialog');dialog.id='trade-review';dialog.className='trade-review';
  dialog.dataset.key=i.instrument_key;dialog.dataset.planStrategy=row.strategy;
  dialog.dataset.latestPrice=row.request_latest_price?'true':'false';
  const brokers=marketState.brokers||[];
  dialog.innerHTML=`<div class="panel-head"><div><h3>${h(i.exchange+' / '+i.symbol)}</h3><small>${h(row.strategy_name)} · ISIN ${h(i.isin||'unavailable')}</small></div><button class="icon-button" data-plan-close aria-label="Close plan">×</button></div>
    <div class="panel-body">${tradePlanView(row)}<ul class="evidence-list">${(p.checks||[]).map(c=>`<li>${passIcon(c.pass)}${h(c.name)}</li>`).join('')}</ul>
    ${(p.limitations||[]).map(t=>`<p class="small muted">${h(t)}</p>`).join('')}
    ${(row.data_errors||[]).map(t=>`<p class="note-block">${h(t)}</p>`).join('')}
    <div class="row-flex"><button class="button primary" data-plan-copy ${p.entry?'':'disabled'}>Recheck &amp; copy plan</button><button class="button subtle" data-plan-download>Save research record</button>
    ${p.official_market_url?`<a class="button subtle" href="${h(p.official_market_url)}" target="_blank" rel="noopener noreferrer">Check official market site ↗</a>`:''}</div>
    <div class="broker-handoff"><strong>Place any trade on your own platform</strong><p class="small muted">Search the symbol and exchange yourself. These links open the broker only; they do not submit or prefill an order.</p>
    <div class="row-flex">${brokers.map(b=>`<a class="button subtle small" href="${h(b.url)}" target="_blank" rel="noopener noreferrer">Open ${h(b.name)} ↗</a>`).join('')}</div><p class="tiny muted">You can use any other registered broker manually. No broker password is collected here.</p></div>
    <textarea id="plan-copy-fallback" aria-label="Research record to copy" hidden readonly></textarea>
    <p class="tiny muted">${p.id?'Record '+h(p.id)+' · ':''}Research output only. No order has been placed.</p></div>`;
  document.body.append(dialog);dialog.showModal();
  dialog.addEventListener('click',e=>{if(e.target===dialog||e.target.closest('[data-plan-close]'))dialog.close();});
  dialog.addEventListener('close',()=>dialog.remove());
  expireTradePlans();
}

document.addEventListener('change',e=>{if(e.target.id==='history-source'){marketState.historySource=e.target.value;marketState.historyAttempts={};}});
document.addEventListener('click',async e=>{
  const review=e.target.closest('[data-review-key]'),copy=e.target.closest('[data-plan-copy]'),save=e.target.closest('[data-plan-download]');
  if(!review&&!copy&&!save)return;
  const button=review||copy||save;button.disabled=true;
  try{
    const dialog=document.getElementById('trade-review');
    const key=review?review.dataset.reviewKey:dialog.dataset.key;
    const strategy=review?review.dataset.reviewStrategy:dialog.dataset.planStrategy;
    const latest_price=review?review.dataset.reviewLatest==='true':dialog.dataset.latestPrice==='true';
    const row=await api('/desk/review',{instrument_key:key,strategy,filters:marketState.filters,latest_price});
    row.request_latest_price=latest_price;
    if(review){showTradeReview(row);return;}
    const p=row.trade_plan||{};
    if(!p.copy_text)throw Error('Load this stock’s completed candles first.');
    showTradeReview(row);
    if(copy&&(p.decision!=='CONDITIONAL_BUY'||!(Date.parse(p.expires_at)>Date.now()))){
      throw Error('The plan is no longer eligible. Its latest status is shown.');
    }
    if(copy){
      try{await navigator.clipboard.writeText(p.copy_text);toast('Research plan copied. Verify the current market in your broker.');}
      catch{const field=document.getElementById('plan-copy-fallback');field.value=p.copy_text;field.hidden=false;field.focus();field.select();toast('Select and copy the research record below.');}
    }else{
      const blob=new Blob([JSON.stringify(row,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');
      a.href=url;a.download='research-plan-'+p.id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }
  }catch(err){toast(err.message,true);}finally{if(button.isConnected)button.disabled=button.dataset.expired==='true';}
});
setInterval(expireTradePlans,1000);
