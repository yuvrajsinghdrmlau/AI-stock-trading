/* India Quant v2: real instrument discovery and explicitly bounded research views. */
const marketState = {
  q:'', exchange:'ALL', kind:'CASH', offset:0, catalogue:null, watch:[],
  key:null, strategy:'trend_pullback', chart:null, mode:'Swing', board:null,
  auto:false, timer:null, busy:false, dataJob:null, jobResult:null, filters:{},
  overlays:{ema20:true,ema50:true,ema200:false,bands:false,levels:true,vwap:false},
  pane:'rsi', zoom:120, expiries:[], chain:null, historySource:'auto', brokers:[], historyAttempts:{}
};
let searchTimer;
function stateLabel(s){return String(s||'UNAVAILABLE').replaceAll('_',' ');}
function marketPill(s){return pill(stateLabel(s), ['FRESH_SNAPSHOT','RESEARCH_ESTIMATE'].includes(s)?'green':s==='NO_TRADE'?'gray':'amber');}
function marketReadiness(config){
  return `${config.catalogue.source_headers?.fixture?'<div class="banner"><p><strong>OFFLINE UI TEST FIXTURES.</strong> Catalogue records and chart prices shown in this test workspace are fictional. No live feed is connected.</p></div>':''}<div class="connection-strip"><span>${pill(config.upstox_configured?'BROKER TOKEN CONFIGURED':'NO-KEY HISTORY OPTION',config.upstox_configured?'violet':'amber')}</span><span>${num(config.catalogue.total,0)} searchable provider instruments</span><span>${config.catalogue.fetched_at?'Catalogue refreshed '+h(config.catalogue.fetched_at.slice(0,16).replace('T',' '))+' IST':'Catalogue not downloaded'}</span><span class="right tiny">REAL ORDERS DISABLED</span></div>`;
}
function dataJobView(){
  const j=marketState.dataJob;
  if(j) return `<div class="progress-wrap" id="provider-progress"><div class="row-flex"><strong>${h(j.message||'Requesting provider data')}</strong><span>${j.progress||0}%</span></div><div class="meter"><span style="width:${j.progress||0}%"></span></div><p>Requests are rate-limited. Network failures do not create substitute prices.</p></div>`;
  const result=marketState.jobResult;
  if(!result) return '';
  const failed=result.error?[result.error]:(result.items||[]).filter(r=>!r.ok).map(r=>`${r.instrument_key}: ${r.error}`);
  return `<div class="banner ${failed.length?'':'info'}"><p>${failed.length?failed.map(h).join('<br>'):h(result.total?`Catalogue refreshed: ${result.total} provider records.`:`Completed ${result.successes||0} historical-data updates.`)}</p></div>`;
}
async function startDataJob(path,body){
  if(marketState.dataJob) throw Error('A data refresh is running; its progress is shown above.');
  const result=await api(path,body); if(!result.job_id)return; marketState.dataJob={id:result.job_id,progress:0,message:'Starting data request'};marketState.jobResult=null;
  const where=$('#provider-job'); if(where)where.innerHTML=dataJobView();
  const poll=async()=>{
    try{
      const j=await api('/market/jobs/'+marketState.dataJob.id);marketState.dataJob=j;
      const holder=$('#provider-job');if(holder)holder.innerHTML=dataJobView();
      if(j.status==='running'){setTimeout(poll,1000);return;}
      marketState.dataJob=null;marketState.jobResult=j.status==='failed'?{error:j.error}:j.result;
      await refreshBoot();
      if(state.page==='market')await renderMarket();else if(state.page==='desk')await renderDaily();else if(state.page==='studio')await renderStudio();
      if(j.status==='failed')toast(j.error,true);else toast('Data job completed. Review coverage and source timestamps.');
    }catch(err){marketState.dataJob=null;marketState.jobResult={error:err.message};toast(err.message,true);}
  };setTimeout(poll,400);
}
async function renderMarket(){
  stopDeskTimer();const config=await api('/market/config');marketState.catalogue=config.catalogue;marketState.watch=config.watchlist;
  $('#content').innerHTML=heading('Every symbol starts with the right data.','Search NSE and BSE by company name, trading symbol or ISIN.',`<button class="button subtle" data-page="desk">Open daily desk</button><button class="button primary" data-v2="sync">Refresh NSE + BSE catalogue</button>`,'MARKET EXPLORER / V2')+
    marketReadiness(config)+`<div id="provider-job">${dataJobView()}</div>`+
    `<div class="stats">${stat('NSE CATALOGUE',num(config.catalogue.counts?.NSE||0,0),'Provider cash segment + indices')}${stat('BSE CATALOGUE',num(config.catalogue.counts?.BSE||0,0),'Separate exchange identities')}${stat('LIVE WATCHLIST',config.watchlist.length+' / 25','Bounded polling; search is unrestricted')}${stat('MODEL POLICY','Evidence first','No fabricated accuracy or guaranteed returns','purple-text')}</div>
    <section class="panel"><div class="market-searchbar"><div class="searchbox-large"><span>&#9906;</span><input id="universe-query" aria-label="Search NSE or BSE stocks" placeholder="Search company, symbol or ISIN..." value="${h(marketState.q)}" maxlength="100"></div><select id="universe-exchange" aria-label="Exchange"><option value="ALL">NSE + BSE</option><option value="NSE">NSE</option><option value="BSE">BSE</option></select><select id="universe-kind" aria-label="Instrument kind"><option value="CASH">Cash segment</option><option value="INDEX">Indices</option><option value="ALL">Cash + indices</option></select></div>
    <div class="panel-head compact"><div><h3>Instrument directory</h3><small id="search-count">Searching...</small></div><span class="tiny muted">IDENTIFIERS FROM THE PROVIDER MASTER</span></div><div class="table-wrap"><table id="universe-table"><thead><tr><th>Symbol / company</th><th>Exchange</th><th>Type / series</th><th>ISIN</th><th>Scope</th><th>Watchlist</th><th></th></tr></thead><tbody></tbody></table></div><div class="pagination"><button class="button subtle small" data-v2="previous-search">Previous</button><span id="search-page"></span><button class="button subtle small" data-v2="next-search">Next</button></div></section>
    <div class="equal-columns"><section class="panel"><div class="panel-head"><h3>Your research watchlist</h3><span class="tiny muted">PERSISTED LOCALLY</span></div><div class="panel-body">${watchlistView()}</div></section><section class="panel"><div class="panel-head"><h3>From discovery to evidence</h3>${pill('READ ONLY','gray')}</div><div class="panel-body"><div class="process-step"><b>01</b><div><strong>Refresh the catalogue</strong><p>Download the provider's current NSE/BSE cash and index master. Suspended records stay visible and blocked for trade candidates.</p></div></div><div class="process-step"><b>02</b><div><strong>Load completed candles</strong><p>Public Yahoo Finance historical bars need no Upstox key. Broker history is used when your token is configured. Public data may be delayed or unavailable.</p></div></div><div class="process-step"><b>03</b><div><strong>Review historical setups</strong><p>Add stocks to the watchlist, inspect the chart, and review setups on the daily desk. Qualified trade candidates still require fresh broker quotes and validated models.</p></div></div><p class="note-block">Coverage follows the provider master, not an independently reconciled list of every exchange security. Cash results may include funds or special series. Searchability does not mean a trade is available.</p></div></section></div>`;
  $('#universe-exchange').value=marketState.exchange;$('#universe-kind').value=marketState.kind;await searchUniverse();
  if((!config.catalogue.total||config.catalogue.refresh_required)&&!marketState.initialSyncAttempted){marketState.initialSyncAttempted=true;await startDataJob('/universe/sync',{});}
}
function watchlistView(){
  if(!marketState.watch.length)return '<p class="muted small">Add a result from the directory. Your watched instruments drive the daily boards; no stocks are selected on your behalf.</p>';
  return marketState.watch.map(r=>`<div class="watch-row"><button class="text-button" data-stock="${h(r.instrument_key)}"><strong>${h(r.symbol)}</strong><small>${h(r.exchange||'Missing from catalogue')} &middot; ${h(r.name||'Refresh required')}</small></button><button class="icon-button" aria-label="Remove ${h(r.symbol)}" data-watch-remove="${h(r.instrument_key)}">&times;</button></div>`).join('');
}
async function searchUniverse(){
  const serial=marketState.searchSerial=(marketState.searchSerial||0)+1;
  const r=await api('/universe/search?'+new URLSearchParams({q:marketState.q,exchange:marketState.exchange,kind:marketState.kind,offset:marketState.offset,limit:30}));
  if(state.page!=='market'||serial!==marketState.searchSerial)return;
  marketState.searchResult=r;
  $('#search-count').textContent=r.total?`${r.total.toLocaleString('en-IN')} matching records; catalogue metadata, not price quotes`:'No matching records. Refresh the catalogue on first use.';
  const watched=new Set(marketState.watch.map(x=>x.instrument_key));
  $('#universe-table tbody').innerHTML=r.items.length?r.items.map(i=>`<tr><td><strong>${h(i.symbol)}</strong><small>${h(i.name)}</small></td><td>${pill(i.exchange,'violet')}</td><td>${h(i.instrument_type)}<small>Lot ${i.lot_size}</small></td><td class="mono small">${h(i.isin||'Index')}</td><td>${pill(i.suspended?'SUSPENDED':i.simple_equity?'CASH RESEARCH':i.kind==='INDEX'?'INDEX':'SPECIAL / OTHER',i.suspended?'red':i.simple_equity?'green':'gray')}</td><td><button class="button small subtle" data-watch-add="${h(i.instrument_key)}" ${watched.has(i.instrument_key)?'disabled':''}>${watched.has(i.instrument_key)?'Added':'+ Watch'}</button></td><td><button class="text-button" data-stock="${h(i.instrument_key)}">Chart &amp; research &#8599;</button></td></tr>`).join(''):`<tr><td colspan="7" class="table-empty">${marketState.catalogue?.total?'No instrument matched your search.':'No catalogue is bundled or invented. Click Refresh NSE + BSE catalogue to download it.'}</td></tr>`;
  $('#search-page').textContent=r.total?`${r.offset+1}-${Math.min(r.offset+30,r.total)} of ${r.total}`:'0 records';
  $('[data-v2="previous-search"]').disabled=!r.offset;$('[data-v2="next-search"]').disabled=r.next_offset===null;
}
function stopDeskTimer(){if(marketState.timer)clearTimeout(marketState.timer);marketState.timer=null;}
function scheduleDesk(){stopDeskTimer();if(marketState.auto&&marketState.brokerConfigured&&state.page==='desk'&&marketState.mode!=='F&O')marketState.timer=setTimeout(()=>refreshBoard(),20000);}
function scanFiltersForm(){const f=marketState.filters;return `<div class="filters-grid">
  <label>Min price<input data-filter="min_price" type="number" value="${f.min_price}" min="0"></label><label>Max price<input data-filter="max_price" type="number" value="${f.max_price}" min="1"></label>
  <label>Min relative volume<input data-filter="min_relative_volume" type="number" value="${f.min_relative_volume}" min="0" max="20" step="0.1"></label>
  <label>RSI minimum<input data-filter="rsi_min" type="number" value="${f.rsi_min}" min="0" max="100"></label><label>RSI maximum<input data-filter="rsi_max" type="number" value="${f.rsi_max}" min="0" max="100"></label>
  <label>Max spread (bps)<input data-filter="max_spread_bps" type="number" value="${f.max_spread_bps}" min="1" max="200"></label>
  <label>Min checklist / 100<input data-filter="min_checklist" type="number" value="${f.min_checklist}" min="0" max="100"></label><label>Min target-hit estimate<input data-filter="min_probability" type="number" value="${f.min_probability}" min="0.5" max="0.95" step="0.01"></label>
  <label class="inline-check"><input type="checkbox" data-filter="uptrend_only" ${f.uptrend_only?'checked':''}> Uptrend only</label><label class="inline-check"><input type="checkbox" data-filter="candidates_only" ${f.candidates_only?'checked':''}> Hide rejected setups</label></div><div class="row-flex"><p class="tiny muted">Probability thresholds apply when a validated model estimate exists; rules-only plans have no estimate. Spread checks require broker data. Filters do not clear news risk.</p><button class="button primary small" data-v2="apply-filters">Apply &amp; refresh snapshots</button></div>`;}
async function renderDaily(){
  stopDeskTimer();const request=marketState.renderSerial=(marketState.renderSerial||0)+1;const requestedMode=marketState.mode;
  const config=await api('/market/config');
  if(state.page!=='desk'||request!==marketState.renderSerial||requestedMode!==marketState.mode)return;
  marketState.watch=config.watchlist;
  marketState.brokerConfigured=config.upstox_configured;
  marketState.brokers=config.brokers;
  if(!config.upstox_configured)marketState.auto=false;
  if(!Object.keys(marketState.filters).length)marketState.filters={...config.filters};
  const mode=marketState.mode;
  $('#content').innerHTML=heading('Trade ideas & manual plans','Watch stocks, refresh data, inspect the entry conditions, then decide on your own broker.',`<button class="button subtle" data-page="market">Manage watchlist</button><button class="button primary" data-v2="refresh-history">Refresh data + find setups</button>`,'LOCAL RESEARCH / MANUAL BROKER WORKFLOW')+
    marketReadiness(config)+`<div id="provider-job">${dataJobView()}</div><div class="toolbar"><div class="segmented">${['Intraday','Swing','Delivery','F&O'].map(m=>`<button data-desk-mode="${m}" class="${mode===m?'selected':''}">${m}</button>`).join('')}</div><label class="inline-check right"><input id="desk-auto" type="checkbox" ${marketState.auto?'checked':''} ${config.upstox_configured?'':'disabled'}> Auto-refresh broker snapshots</label><button class="button subtle small" data-v2="refresh-board">Refresh board</button></div>`+
    (mode==='F&O'?`<div id="options-live"></div>`:`<section class="panel filter-panel"><details><summary>Research filters <span>Price, trend, volume, spread, model threshold</span></summary><div class="panel-body">${scanFiltersForm()}</div></details></section><div id="board-summary"></div><div id="daily-board">${loading('Checking your watchlist')}</div><p class="note-block">${config.upstox_configured?'Auto-refresh polls broker snapshots every 20 seconds. For already-loaded intraday stocks it also requests newly completed candles during the supported session.':'Without a broker token, refresh completed candles manually to update historical setups. Public history is not a live quote feed.'} No polling places orders. Daily models describe conditional next-open setups, not an instruction to enter at the displayed LTP. No filter can eliminate losses.</p><section class="panel"><div class="panel-head"><h3>First-seen signal records</h3><button class="text-button" data-v2="signal-log">Load local audit</button></div><div id="signal-log" class="panel-body small muted">Timestamped model outputs are stored once per setup/model/status. The log is local and is not a verified live-performance track record.</div></section>`);
  if(mode==='F&O')renderLiveOptions();else{document.getElementById('provider-job').insertAdjacentHTML('afterend',dataAccessView(config));await refreshBoard();}
}
async function refreshBoard(){
  if(marketState.busy||state.page!=='desk'||marketState.mode==='F&O')return;
  marketState.busy=true;
  const mode=marketState.mode;
  try{
    const r=await api('/desk/scan',{mode,filters:marketState.filters});
    if(state.page!=='desk'||mode!==marketState.mode)return;
    marketState.board=r;drawBoard(r);if(marketState.auto&&mode==='Intraday'&&!marketState.dataJob)await startDataJob('/market/refresh-due',{mode:'Intraday'});
  }catch(err){if(state.page==='desk'&&mode===marketState.mode&&$('#daily-board')){$('#daily-board').innerHTML=empty('Refresh failed; current signals are unavailable',err.message);$('#board-summary').innerHTML='<div class="banner"><p>Previous snapshot results have been removed. Do not act on expired data.</p></div>';}toast(err.message,true);}
  finally{marketState.busy=false;if(state.page==='desk'&&mode!==marketState.mode&&marketState.mode!=='F&O')refreshBoard();else scheduleDesk();}
}
function drawBoard(r){
  const matches=r.rows.filter(x=>x.trade_plan?.decision==='CONDITIONAL_BUY').length;
  const historical=r.rows.filter(x=>x.trade_plan?.live_qualified).length;
  const fresh=r.rows.filter(x=>x.quote?.fresh).length;
  $('#board-summary').innerHTML=`<div class="stats">${stat('SETUPS EVALUATED',r.evaluated,`${r.watchlist_size} instruments in your watchlist`)}${stat('CONDITIONAL BUY SETUPS',`<span id="conditional-plan-count">${matches}</span>`,'Review the next-open window and conditions')}${stat('BROKER + MODEL QUALIFIED',`<span id="qualified-plan-count">${historical}</span>`,'Includes all live and risk checks')}${stat('SOURCE-FRESH ROWS',fresh,'Broker quotes across strategies')}</div>`+
   r.errors.map(e=>`<div class="banner"><p>${h(e)}</p></div>`).join('');
  if(!r.rows.length){$('#daily-board').innerHTML=empty(r.watchlist_size?'No setups pass the selected visibility filters.':'Your live watchlist is empty.','Add an NSE/BSE result in Market Explorer. Load its history and train a model. Missing evidence stays unavailable; it is never replaced with a made-up percentage.');return;}
  $('#daily-board').innerHTML=`<div class="candidate-grid">${r.rows.map((x,i)=>{
    const m=x.model||{},q=x.quote||{},plan=x.plan||{},isCandidate=x.trade_plan?.decision==='CONDITIONAL_BUY';
    return `<article class="panel candidate-card ${isCandidate?'candidate-pass':''}"><div class="panel-head"><div><h3><button class="text-button" data-stock="${h(x.instrument.instrument_key)}">${h(x.instrument.symbol)}</button></h3><small>${h(x.instrument.exchange||'')} &middot; ${h(x.strategy_name||'Instrument unavailable')}</small></div><span data-card-decision>${marketPill(x.trade_plan?.decision||x.status)}</span></div><div class="panel-body"><div class="candidate-number-row"><div><small>VALIDATED TARGET-HIT ESTIMATE</small><div class="candidate-probability">${x.trade_plan?.probability==null?'Unavailable':pct(x.trade_plan.probability)}</div><span class="tiny muted">${h(m.selected_model||'Rules research; no compatible saved model')}</span></div><div class="candidate-ltp"><small>BROKER QUOTE</small><strong>${money(q.last_price,2)}</strong>${marketPill(q.status||'NOT_CONNECTED')}</div></div>
    <div class="candidate-meta"><span>Checklist <b>${x.setup_score??'--'}/100</b></span><span>RSI <b>${num(x.rsi,1)}</b></span><span>Rel. volume <b>${num(x.relative_volume,2)}x</b></span><span>Spread <b>${num(q.spread_bps,1)} bps</b></span></div>
    ${tradePlanView(x)}
    <p class="tiny muted">Last completed bar: ${h(x.last_bar?.slice(0,16).replace('T',' ')||'Not loaded')} IST. LTP is not the modeled next-open fill.</p>
    <div class="candidate-reasons">${(x.trade_plan?.reasons?.length?x.trade_plan.reasons:x.reasons)?.slice(0,3).map(t=>`<p>&times; ${h(t)}</p>`).join('')||'<p>Review company events, the actual opening price and trading session before deciding.</p>'}</div>
    <details class="evidence-details"><summary>Inspect all gates and confidence evidence</summary><ul class="evidence-list">${(x.checks||[]).map(c=>`<li>${passIcon(c.pass)}${h(c.name)}</li>`).join('')}</ul><p class="small">${h(m.definition||'Probability is withheld until a model can be evaluated.')}</p><p class="small muted">${h(m.status||'NOT TRAINED')} &middot; ${m.test_events||0} test events &middot; ${m.test_trades||0} filtered test trades. Model outcomes are historical, not a promise.</p>${m.cohort?`<p class="small">Comparable test bucket: n=${m.cohort.n}; observed hit rate ${pct(m.cohort.observed)}; approximate 95% cohort interval ${pct(m.cohort.observed_wilson_95[0])}-${pct(m.cohort.observed_wilson_95[1])}. This is not a per-trade guarantee.</p>`:''}<p class="tiny muted">Feed timestamp: ${h(q.feed_time||'Unknown')}<br>Last trade: ${h(q.trade_time||'Unknown')}<br>Estimated planned loss: ${money(plan.planned_loss_with_estimated_costs,2)}. Actual losses may exceed it.</p></details>
    <div class="row-flex candidate-actions"><button class="button subtle small" data-stock="${h(x.instrument.instrument_key)}" data-stock-strategy="${h(x.strategy||'trend_pullback')}">Chart &amp; filters</button>${x.dataset_id?`<button class="button primary small" data-review-key="${h(x.instrument.instrument_key)}" data-review-strategy="${h(x.strategy)}">Review plan / open broker</button><button class="button small" data-train-dataset="${h(x.dataset_id)}" data-train-strategy="${h(x.strategy)}">Train / review AI</button>`:`<button class="button small" data-fetch-key="${h(x.instrument.instrument_key)}">Load candles</button>`}</div></div></article>`;
  }).join('')}</div>`;
  expireTradePlans();
  // Expiry is wall-clock, not dependent on the success of the next request.
  const generated=r.generated_at;
  if(r.configured)setTimeout(()=>{if(state.page==='desk'&&marketState.board?.generated_at===generated){const el=$('#board-summary');if(el)el.insertAdjacentHTML('afterbegin','<div class="banner"><p>This displayed snapshot has expired. Refresh before assessing any research setup.</p></div>');}},20500);
}
function marketCsvForm(timeframe){return `<section class="panel"><div class="panel-head"><h3>Import candles for this stock</h3>${pill('OFFLINE CSV','violet')}</div><div class="panel-body"><p class="note-block">Use an OHLCV export you are entitled to use. The file must have timestamp,open,high,low,close,volume columns and at least 70 completed ${timeframe==='1d'?'daily':'15-minute'} bars. It will be linked only to this selected listing.</p><form id="market-csv-form"><input id="market-csv-file" type="file" accept=".csv,text/csv" required><button class="button subtle" type="submit">Import CSV candles</button></form></div></section>`;}
async function renderStudio(){
  stopDeskTimer();const config=await api('/market/config');marketState.watch=config.watchlist;
  marketState.brokers=config.brokers;
  if(!marketState.key)marketState.key=marketState.watch.find(r=>!r.unavailable)?.instrument_key;
  if(!marketState.key){$('#content').innerHTML=heading('Chart & filter studio','Choose a stock from the NSE/BSE directory.',`<button class="button primary" data-page="market">Search stocks</button>`)+empty('No instrument selected','Use Market Explorer to select any provider-listed NSE/BSE cash instrument or index.');return;}
  const r=await api('/market/chart?'+new URLSearchParams({instrument_key:marketState.key,strategy:marketState.strategy}));marketState.chart=r;
  const inst=r.instrument, spec=state.boot.strategies.find(s=>s.id===marketState.strategy);
  $('#content').innerHTML=heading(inst.symbol+' / Chart studio',`${inst.name} | ${inst.exchange} | ${spec.timeframe} completed candles`, `<button class="button subtle" data-watch-add="${h(inst.instrument_key)}">+ Watch</button><button class="button primary" data-v2="refresh-one">Load / refresh candles</button>`,'CHARTS, INDICATORS & TRANSPARENT FILTERS')+
    marketReadiness(config)+`<div id="provider-job">${dataJobView()}</div><div class="toolbar"><select id="studio-strategy" class="select-inline">${options(state.boot.strategies,marketState.strategy)}</select><span class="tiny muted">HISTORICAL CANDLES &ne; LIVE QUOTE</span><div class="zoom-buttons right">${[60,120,180].map(z=>`<button data-studio-zoom="${z}" class="${marketState.zoom===z?'selected':''}">${z} bars</button>`).join('')}</div></div>`;
  $('#provider-job').insertAdjacentHTML('afterend',dataAccessView(config));
  if(r.data_required){
    $('#content').insertAdjacentHTML('beforeend',empty('Loading the price graph',r.configured?'Requesting authorized broker history.':'Requesting public historical candles. No Upstox key is needed. If this source cannot supply the listing, the exact error will stay visible and you can import CSV below.')+marketCsvForm(spec.timeframe));
    const attempt=[inst.instrument_key,spec.timeframe,marketState.historySource].join('|');
    if(!marketState.historyAttempts[attempt]&&!marketState.dataJob){
      marketState.historyAttempts[attempt]=true;
      try{await startDataJob('/market/history',{instrument_keys:[inst.instrument_key],timeframe:spec.timeframe,source:marketState.historySource});}
      catch(err){marketState.jobResult={error:err.message};const holder=$('#provider-job');if(holder)holder.innerHTML=dataJobView();toast(err.message,true);}
    }
    return;
  }
  $('#content').insertAdjacentHTML('beforeend',`<section class="panel" id="studio-trade-decision"><div class="panel-body">${loading('Calculating the current trade decision')}</div></section>`);
  const a=r.last,m=r.model;
  $('#content').insertAdjacentHTML('beforeend',`${r.dataset.synthetic?demoBanner(true):''}<div class="two-column studio-layout"><section class="panel"><div class="panel-head"><div><h3>${money(a.c,2)} <span class="muted small">last completed close</span></h3><small>${h(a.t.slice(0,16).replace('T',' '))} IST</small></div>${pill(a.regime,a.regime==='UPTREND'?'green':'gray')}</div><div class="overlay-controls">${Object.entries({ema20:'EMA 20',ema50:'EMA 50',ema200:'EMA 200',bands:'Bollinger bands',levels:'Prior 20-bar levels',vwap:'Session VWAP'}).map(([k,label])=>`<label class="inline-check"><input type="checkbox" data-overlay="${k}" ${marketState.overlays[k]?'checked':''} ${k==='vwap'&&spec.timeframe!=='15m'?'disabled':''}>${label}</label>`).join('')}</div><div id="studio-chart" class="studio-chart"></div><div class="pane-selector"><button data-pane="rsi" class="${marketState.pane==='rsi'?'selected':''}">RSI</button><button data-pane="macd" class="${marketState.pane==='macd'?'selected':''}">MACD</button><span class="tiny muted">Hover to inspect a completed candle</span></div><div class="chart-context"><div><small>ATR 14</small><strong>${money(a.atr,2)}</strong></div><div><small>RELATIVE VOLUME</small><strong>${num(a.rv,2)}x</strong></div><div><small>RSI 14</small><strong>${num(a.rsi,1)}</strong></div><div><small>MACD</small><strong>${num(a.macd,2)}</strong></div></div></section><section class="panel"><div class="panel-head"><h3>Setup &amp; model evidence</h3>${marketPill(m.status)}</div><div class="panel-body"><small class="muted">DEFINED TARGET-HIT ESTIMATE</small><div class="candidate-probability">${pct(m.probability)}</div><p class="small muted">A confidence score is not a guaranteed return. ${h(m.definition||'Train on genuine historical data to measure a defined outcome.')}</p><ul class="evidence-list">${r.checks.map(c=>`<li>${passIcon(c.pass)}${h(c.name)}</li>`).join('')}</ul><p class="small">Checklist: <strong>${r.setup_score}/100</strong> &mdash; not a probability.</p><button class="button primary full" data-train-dataset="${h(r.dataset.id)}" data-train-strategy="${h(marketState.strategy)}">Compare models + walk-forward</button><div class="divider"></div><h3>Data &amp; quote check</h3><p class="tiny muted">History source: ${h(r.dataset.source)}</p>${r.configured?'<button class="button subtle full" data-v2="quote-one">Fetch authorized quote snapshot</button>':'<p class="note-block">No broker quote is connected. The close above is historical, not a current price.</p>'}<div id="studio-quote" class="small muted" style="margin-top:15px">Displayed candles are not labeled live.</div><div class="divider"></div><p class="note-block">Indicators describe the chart; no combination is a never-fail filter. New-event risk, corporate actions and suitability still require review.</p></div></section></div><section class="panel"><div class="panel-head"><h3>Filter your daily research shortlist</h3><button class="button subtle small" data-page="desk">Open filters</button></div><div class="panel-body small muted">The daily desk combines chart rules with volume, price, spread, data freshness, model validation and paper-account limits. Changing overlays here does not retrain the model or improve its measured performance.</div></section>`);
  drawStudioChart();
  loadStudioDecision(inst.instrument_key,marketState.strategy);
}
async function loadStudioDecision(key,strategy){
  const holder=$('#studio-trade-decision');if(!holder)return;
  try{
    const row=await api('/desk/review',{instrument_key:key,strategy,filters:marketState.filters});
    if(state.page!=='studio'||marketState.key!==key||marketState.strategy!==strategy||!holder.isConnected)return;
    const plan=row.trade_plan||{};
    holder.innerHTML=`<div class="panel-head"><div><h3>Current trade decision</h3><small>Calculated from the last completed candle; rechecked when this panel loaded</small></div>${marketPill(plan.decision||row.status)}</div><div class="panel-body">${tradePlanView(row)}<div class="candidate-reasons">${(plan.reasons?.length?plan.reasons:row.reasons)?.slice(0,4).map(t=>`<p>&times; ${h(t)}</p>`).join('')||'<p>All configured historical setup gates passed. Review the entry window and limitations.</p>'}</div><div class="row-flex"><button class="button primary" data-review-key="${h(key)}" data-review-strategy="${h(strategy)}">Review details / open my broker</button><button class="button subtle" data-v2="refresh-one">Refresh candles and recalculate</button></div><p class="tiny muted">This is conditional research, not a guaranteed-profit call. No order has been placed.</p></div>`;
    expireTradePlans();
  }catch(err){if(holder.isConnected)holder.innerHTML=`<div class="panel-body"><p class="note-block">Trade decision unavailable: ${h(err.message)}</p></div>`;}
}
function drawStudioChart(){
  const el=$('#studio-chart'),r=marketState.chart;if(!el||r?.data_required)return;
  const bars=r.chart.slice(-marketState.zoom),W=1000,H=520,L=15,R=70,T=20,ph=275,vt=315,vh=40,pt=392,pH=90,dx=(W-L-R)/bars.length;
  const lines=[];if(marketState.overlays.ema20)lines.push(['ema20','#d9b478']);if(marketState.overlays.ema50)lines.push(['ema50','#ad97f3']);if(marketState.overlays.ema200)lines.push(['ema200','#7bbed2']);if(marketState.overlays.vwap&&r.dataset.timeframe==='15m')lines.push(['vwap','#71d1b1']);if(marketState.overlays.bands)lines.push(['bb_upper','#6b7c9e'],['bb_lower','#6b7c9e']);
  const vals=bars.flatMap(b=>[b.l,b.h,...lines.map(([k])=>b[k]).filter(Number.isFinite)]);let lo=Math.min(...vals),hi=Math.max(...vals);const pad=(hi-lo)*.08||1;lo-=pad;hi+=pad;
  const y=v=>T+(hi-v)/(hi-lo)*ph,x=i=>L+(i+.5)*dx,cw=Math.max(1,dx*.6),mv=Math.max(...bars.map(b=>b.v),1);let shape='';
  for(let i=0;i<6;i++){const v=lo+(hi-lo)*i/5,Y=y(v);shape+=`<line x1="${L}" x2="${W-R}" y1="${Y}" y2="${Y}" stroke="#293342" stroke-width=".7"/><text x="${W-R+8}" y="${Y+4}" fill="#8492a8" font-size="11">${num(v,1)}</text>`;}
  if(marketState.overlays.bands)shape+=`<polygon points="${bars.map((b,i)=>x(i)+','+y(b.bb_upper)).join(' ')} ${bars.map((b,i)=>[x(i),y(b.bb_lower)]).reverse().map(p=>p.join(',')).join(' ')}" fill="#64799a" opacity=".08"/>`;
  bars.forEach((b,i)=>{const color=b.c>=b.o?'#58cdaa':'#df8290';shape+=`<line x1="${x(i)}" x2="${x(i)}" y1="${y(b.h)}" y2="${y(b.l)}" stroke="${color}"/><rect x="${x(i)-cw/2}" y="${Math.min(y(b.o),y(b.c))}" width="${cw}" height="${Math.max(1,Math.abs(y(b.c)-y(b.o)))}" fill="${color}"/><rect x="${x(i)-cw/2}" y="${vt+vh-b.v/mv*vh}" width="${cw}" height="${b.v/mv*vh}" fill="${color}" opacity=".45"/>`;});
  for(const [key,color] of lines)shape+=`<polyline points="${bars.map((b,i)=>x(i)+','+y(b[key])).join(' ')}" fill="none" stroke="${color}" stroke-width="1.5"/>`;
  if(marketState.overlays.levels)for(const [key,label] of [['support','PRIOR LOW'],['resistance','PRIOR HIGH']]){const val=bars.at(-1)[key];if(val>lo&&val<hi)shape+=`<line x1="${L}" x2="${W-R}" y1="${y(val)}" y2="${y(val)}" stroke="#9d9aaa" stroke-dasharray="5,5" opacity=".6"/><text x="${L+5}" y="${y(val)-5}" fill="#9d9aaa" font-size="9">${label}</text>`;}
  shape+=`<line x1="${L}" x2="${W-R}" y1="305" y2="305" stroke="#30394a"/><line x1="${L}" x2="${W-R}" y1="377" y2="377" stroke="#30394a"/>`;
  if(marketState.pane==='rsi'){
    const ry=v=>pt+(100-v)/100*pH;
    for(const v of [30,50,70])shape+=`<line x1="${L}" x2="${W-R}" y1="${ry(v)}" y2="${ry(v)}" stroke="#4b5265" stroke-dasharray="4,5"/><text x="${W-R+8}" y="${ry(v)+4}" fill="#8590a4" font-size="10">${v}</text>`;
    shape+=`<polyline points="${bars.map((b,i)=>x(i)+','+ry(b.rsi)).join(' ')}" stroke="#ad97f3" stroke-width="1.5" fill="none"/>`;
  }else{
    const mv=Math.max(...bars.flatMap(b=>[Math.abs(b.macd),Math.abs(b.macd_signal),Math.abs(b.macd_hist)]),.01),my=v=>pt+pH/2-v/mv*pH/2;
    bars.forEach((b,i)=>{shape+=`<rect x="${x(i)-cw/2}" y="${Math.min(my(0),my(b.macd_hist))}" width="${cw}" height="${Math.max(1,Math.abs(my(b.macd_hist)-my(0)))}" fill="${b.macd_hist>=0?'#58cdaa':'#df8290'}" opacity=".6"/>`;});
    for(const [key,color] of [['macd','#ad97f3'],['macd_signal','#d9b478']])shape+=`<polyline points="${bars.map((b,i)=>x(i)+','+my(b[key])).join(' ')}" fill="none" stroke="${color}" stroke-width="1.3"/>`;
  }
  for(let k=0;k<5;k++){const i=Math.floor((bars.length-1)*k/4);shape+=`<text x="${Math.min(W-R-65,Math.max(L,x(i)-20))}" y="510" fill="#8492a8" font-size="10">${h(bars[i].t.slice(5,10)+(r.dataset.timeframe==='15m'?' '+bars[i].t.slice(11,16):''))}</text>`;}
  shape+=`<text x="${W/2}" y="155" fill="#9ca5c1" opacity=".08" text-anchor="middle" font-size="46">${r.dataset.synthetic?'SYNTHETIC FIXTURE':'COMPLETED BARS'}</text>`;
  el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" aria-label="Candles with selected indicators, volume and ${marketState.pane}">${shape}<line class="studio-crosshair" x1="0" x2="0" y1="10" y2="482" stroke="#9ca8c0" stroke-dasharray="3,4" opacity="0"/></svg><div class="studio-tooltip">Hover to inspect prices and indicators</div>`;
  const svg=$('svg',el),tip=$('.studio-tooltip',el),cross=$('.studio-crosshair',el);
  svg.addEventListener('mousemove',e=>{const bounds=svg.getBoundingClientRect(),mx=(e.clientX-bounds.left)/bounds.width*W,i=Math.max(0,Math.min(bars.length-1,Math.floor((mx-L)/dx))),b=bars[i];cross.setAttribute('x1',x(i));cross.setAttribute('x2',x(i));cross.setAttribute('opacity','.65');tip.textContent=`${b.t.slice(0,16).replace('T',' ')} IST | O ${num(b.o)} H ${num(b.h)} L ${num(b.l)} C ${num(b.c)} | RSI ${num(b.rsi,1)} | MACD ${num(b.macd,2)}`;});
  svg.addEventListener('mouseleave',()=>cross.setAttribute('opacity','0'));
}
function renderLiveOptions(){
  const candidates=marketState.watch.filter(r=>!r.unavailable);const target=$('#options-live');
  target.innerHTML=`<div class="banner"><p><strong>F&amp;O is read-only research.</strong> Option-chain prices, OI and Greeks do not constitute a validated options-profit forecast. No confidence percentage or automatic trade is fabricated.</p></div><section class="panel"><div class="panel-head"><h3>Option-chain snapshot</h3>${pill('NOT A RECOMMENDATION','amber')}</div><div class="panel-body"><div class="form-grid"><div class="field"><label>Underlying from your watchlist</label><select id="chain-key">${candidates.map(r=>`<option value="${h(r.instrument_key)}">${h(r.exchange+' / '+r.symbol)}</option>`).join('')}</select></div><div class="field"><label>Expiry from provider</label><select id="chain-expiry"><option value="">Load expiries first</option></select></div></div><div class="row-flex"><button class="button subtle" data-v2="load-expiries" ${!candidates.length?'disabled':''}>Load expiries</button><button class="button primary" data-v2="load-chain">Fetch chain</button><button class="button subtle" data-page="options">Defined-risk payoff lab</button></div><p class="tiny muted">Add an eligible index or stock in Market Explorer. Being listed does not imply that derivatives exist on it.</p><div id="chain-table"></div></div></section>`;
}
function drawChain(r){$('#chain-table').innerHTML=`<p class="note-block">${h(r.note)} Received ${h(r.received_at.slice(0,19))} IST.</p><div class="table-wrap"><table><thead><tr><th>Call bid / ask</th><th>Call OI</th><th>Call IV</th><th>Strike</th><th>Put IV</th><th>Put OI</th><th>Put bid / ask</th></tr></thead><tbody>${r.rows.map(x=>`<tr><td>${money(x.call.bid_price,2)} / ${money(x.call.ask_price,2)}</td><td>${num(x.call.oi,0)}</td><td>${num(x.call.iv,1)}</td><td class="mono"><strong>${num(x.strike,0)}</strong></td><td>${num(x.put.iv,1)}</td><td>${num(x.put.oi,0)}</td><td>${money(x.put.bid_price,2)} / ${money(x.put.ask_price,2)}</td></tr>`).join('')||'<tr><td colspan="7">No chain rows returned.</td></tr>'}</tbody></table></div>`;}
function walkforwardView(r){if(!r.walkforward)return '';const w=r.walkforward;return `<section class="panel"><div class="panel-head"><h3>Expanding-history walk-forward validation</h3>${pill(w.all_folds_evaluable?'3 DISJOINT TEST WINDOWS':'INSUFFICIENT FOLD EVIDENCE',w.all_folds_evaluable?'violet':'amber')}</div><div class="table-wrap"><table><thead><tr><th>Fold / test window</th><th>Selected model</th><th>Test events</th><th>Test Brier / prior</th><th>Filtered trades</th><th>Net simulated P&amp;L</th><th>Evidence</th></tr></thead><tbody>${w.folds.map(f=>`<tr><td><strong>Fold ${f.fold}</strong><small>${h(f.splits[3].from.slice(0,10))} - ${h(f.splits[3].to.slice(0,10))}</small></td><td>${h(f.selected_model||'None')}</td><td>${f.test_events}</td><td>${num(f.test_brier,4)} / ${num(f.baseline_brier,4)}</td><td>${f.trades}</td><td>${money(f.net_pnl,2)}</td><td>${marketPill(f.evidence_status)}</td></tr>`).join('')}</tbody></table></div><div class="table-note">${h(w.definition)} ${w.synthetic?'All of this evidence is SYNTHETIC.':''}</div></section>`;}

document.addEventListener('input',e=>{
  if(e.target.id==='universe-query'){marketState.q=e.target.value;marketState.offset=0;clearTimeout(searchTimer);searchTimer=setTimeout(()=>searchUniverse().catch(err=>toast(err.message,true)),250);}
});
document.addEventListener('submit',async e=>{
  if(e.target.id!=='market-csv-form')return;
  e.preventDefault();
  const button=e.target.querySelector('button[type="submit"]');button.disabled=true;
  try{
    const file=$('#market-csv-file').files[0];if(!file)throw Error('Select a CSV file.');
    if(file.size>4000000)throw Error('CSV limit is 4 MB.');
    const timeframe=state.boot.strategies.find(s=>s.id===marketState.strategy).timeframe;
    const r=await api('/market/import-csv',{instrument_key:marketState.key,timeframe,csv_text:await file.text()});
    await refreshBoot();await renderStudio();toast(`Imported ${r.bars} completed candles for this listing.`);
  }catch(err){toast(err.message,true);}finally{if(button.isConnected)button.disabled=false;}
});
document.addEventListener('change',async e=>{try{
  if(e.target.id==='universe-exchange'||e.target.id==='universe-kind'){marketState.exchange=$('#universe-exchange').value;marketState.kind=$('#universe-kind').value;marketState.offset=0;await searchUniverse();}
  if(e.target.id==='desk-auto'){marketState.auto=e.target.checked;scheduleDesk();}
  if(e.target.id==='studio-strategy'){marketState.strategy=e.target.value;await renderStudio();}
  if(e.target.dataset.overlay){marketState.overlays[e.target.dataset.overlay]=e.target.checked;drawStudioChart();}
}catch(err){toast(err.message,true);}});
document.addEventListener('click',async e=>{
  const action=e.target.closest('[data-v2]'),stock=e.target.closest('[data-stock]'),add=e.target.closest('[data-watch-add]'),remove=e.target.closest('[data-watch-remove]'),mode=e.target.closest('[data-desk-mode]'),train=e.target.closest('[data-train-dataset]'),fetchKey=e.target.closest('[data-fetch-key]'),zoom=e.target.closest('[data-studio-zoom]'),pane=e.target.closest('[data-pane]');
  try{
    if(stock){marketState.key=stock.dataset.stock;if(stock.dataset.stockStrategy)marketState.strategy=stock.dataset.stockStrategy;await navigate('studio');return;}
    if(add||remove){const key=(add||remove).dataset[add?'watchAdd':'watchRemove'];marketState.watch=await api('/watchlist',{instrument_key:key,enabled:!!add});if(state.page==='market')await renderMarket();toast(add?'Instrument added to your watchlist.':'Removed from watchlist.');return;}
    if(mode){marketState.mode=mode.dataset.deskMode;await renderDaily();return;}
    if(train){await refreshBoot();state.dataset=train.dataset.trainDataset;state.strategy=train.dataset.trainStrategy;state.mode=strategySpec().mode;state.result=null;await navigate('lab');return;}
    if(fetchKey){await startDataJob('/market/history',{instrument_keys:[fetchKey.dataset.fetchKey],timeframe:marketState.mode==='Intraday'?'15m':'1d',source:marketState.historySource});return;}
    if(zoom){marketState.zoom=Number(zoom.dataset.studioZoom);for(const b of $$('[data-studio-zoom]'))b.classList.toggle('selected',b===zoom);drawStudioChart();return;}
    if(pane){marketState.pane=pane.dataset.pane;for(const b of $$('[data-pane]'))b.classList.toggle('selected',b===pane);drawStudioChart();return;}
    if(!action)return;
    const name=action.dataset.v2;action.disabled=true;
    if(name==='sync')await startDataJob('/universe/sync',{});
    else if(name==='previous-search'||name==='next-search'){marketState.offset=name==='previous-search'?Math.max(0,marketState.offset-30):marketState.searchResult.next_offset??marketState.offset;await searchUniverse();}
    else if(name==='refresh-board')await refreshBoard();
    else if(name==='apply-filters'){for(const el of $$('[data-filter]'))marketState.filters[el.dataset.filter]=el.type==='checkbox'?el.checked:Number(el.value);await refreshBoard();}
    else if(name==='refresh-history'){if(marketState.mode==='F&O')throw Error('Use the option-chain panel to fetch a read-only F&O snapshot.');const keys=marketState.watch.filter(r=>!r.unavailable&&!r.suspended).map(r=>r.instrument_key);if(!keys.length)throw Error('Add an active stock to the watchlist, or refresh the catalogue if its suspension flags need updating.');await startDataJob('/market/history',{instrument_keys:keys,timeframe:marketState.mode==='Intraday'?'15m':'1d',source:marketState.historySource});}
    else if(name==='refresh-one')await startDataJob('/market/history',{instrument_keys:[marketState.key],timeframe:state.boot.strategies.find(s=>s.id===marketState.strategy).timeframe,source:marketState.historySource});
    else if(name==='quote-one'){const result=await api('/market/quote?'+new URLSearchParams({instrument_key:marketState.key}));const q=result.quote;$('#studio-quote').innerHTML=`${marketPill(q.status)} <strong>${money(q.last_price,2)}</strong><p>Feed ${h(q.feed_time||'unknown')}<br>Trade ${h(q.trade_time||'unknown')}<br>Exchange ${h(result.market.status)}<br>Spread ${num(q.spread_bps,1)} bps</p>`;const time=q.received_at;setTimeout(()=>{const el=$('#studio-quote');if(el&&el.dataset?.fetched===time)el.innerHTML='<p>This displayed quote has expired. Fetch again.</p>';},60000);$('#studio-quote').dataset.fetched=time;}
    else if(name==='signal-log'){const rows=await api('/desk/log');$('#signal-log').innerHTML=rows.length?`<div class="table-wrap"><table><thead><tr><th>First seen</th><th>Instrument / strategy</th><th>Validated estimate</th><th>Recorded decision</th><th>After study window?</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${h(r.generated_at.slice(0,19))}</td><td>${h(r.instrument_key)}<small>${h(r.strategy)}</small></td><td>${pct(r.trade_plan?r.trade_plan.probability:r.probability)}</td><td>${marketPill(r.trade_plan?.decision||r.status)}</td><td>${r.prospective?'Yes':'No'}</td></tr>`).join('')}</tbody></table></div>`:'No records yet. Load history and evaluate a watched instrument.';}
    else if(name==='load-expiries'){const key=$('#chain-key').value;if(!key)throw Error('Add a derivative-eligible underlying to the watchlist first.');const r=await api('/market/expiries?'+new URLSearchParams({instrument_key:key}));$('#chain-expiry').innerHTML=r.expiries.map(d=>`<option>${h(d)}</option>`).join('')||'<option value="">No contracts available</option>';}
    else if(name==='load-chain'){const key=$('#chain-key').value,expiry=$('#chain-expiry').value;if(!key||!expiry)throw Error('Load and select an exact expiry first.');const r=await api('/market/option-chain?'+new URLSearchParams({instrument_key:key,expiry}));drawChain(r);}
  }catch(err){toast(err.message,true);}
  finally{if(action?.isConnected)action.disabled=false;}
});
