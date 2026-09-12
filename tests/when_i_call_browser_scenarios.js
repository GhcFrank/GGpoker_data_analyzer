(async () => {
  const q = s => document.querySelector(s);
  const qa = s => [...document.querySelectorAll(s)];
  const passed = [];
  function check(value, name) { if (!value) throw Error(name); passed.push(name); }
  const pause = () => new Promise(r => setTimeout(r, 30));
  async function until(fn) { for (let n=0;n<200;n++) {if (fn()) return; await pause();} throw Error('timeout ' + fn.toString()); }
  function changed(el) { el.dispatchEvent(new Event('change', {bubbles:true})); }
  function choose(group, values) {
    const inputs = qa(group + ' input');
    inputs.forEach(el => { el.checked = values.includes(el.value); });
    changed(inputs.find(el=>el.checked) || inputs[0]);
  }
  const stats = () => qa('#whenICallStats .value').map(e=>e.textContent.trim());
  await until(() => q('#summaryText').textContent.includes('已加载'));
  const originalFetch = window.fetch;
  const requests = [];
  let holdNext = false;
  let releaseHeld;
  window.fetch = async (url, init) => {
    const held = url === '/api/metrics/when_i_call' && holdNext;
    if (held) holdNext = false;
    if (init?.body) requests.push({url, body:JSON.parse(init.body)});
    const response = await originalFetch(url, init);
    if (held) return new Promise(resolve => { releaseHeld = () => resolve(response); });
    return response;
  };
  const last = url => requests.filter(r=>r.url===url).at(-1)?.body;
  const metric = '/api/metrics/when_i_call';
  const wirMetric = '/api/metrics/when_i_raise';
  check(qa('[id]').length === new Set(qa('[id]').map(e=>e.id)).size, 'DOM ids unique');
  q('#tableFormatGroup input[value="6max"]').click();
  q('#analyzeBtn').click();
  await until(() => q('#filterStatus').textContent.startsWith('已分析'));
  check(stats()[0] === '6' && stats()[1] === '4', 'all-panel analyze has 6 spots / 4 hands');
  check(qa('#whenICallStats .label').map(e=>e.textContent).join('|') === '样本数|涉及手数|Facing Bet|Facing Raise', 'WIC stat labels');
  check(q('#wicShowdownWrap').hidden, 'mixed counts hide range');
  check(q('#panel-when_i_call').previousElementSibling.id === 'panel-when_i_raise', 'panel order');
  const wirCount = requests.filter(r=>r.url===wirMetric).length;
  q('#wicPlayersGroup input[value="3+"]').click();
  await until(() => qa('#wicShowdownCells td').length === 169);
  check(!q('#wicHeroPositionRow').hidden && q('#wicRelativePositionRow').hidden, '6max HU exact position rows');
  check(getComputedStyle(q('#wicRelativePositionRow')).display === 'none', 'relative row hidden by CSS');
  check(requests.filter(r=>r.url===wirMetric).length === wirCount, 'WIC live refresh does not request WIR');
  check(last(metric).options.hero_positions.length === 6 && !('positions' in last(metric).options), 'exact request excludes relative axis');
  check(q('#wicShowdownStatus').textContent === '已知对手手牌：2 / 4', 'range known denominator');
  check(qa('#wicShowdownCells td')[13].textContent.includes('25.00%'), 'range AKo displays 25 percent');
  check(getComputedStyle(q('#wicFlopTextureRow')).display === 'none', 'flop texture controls hidden initially');
  q('#wicReplayBtn').click();
  await until(() => q('#replayPage').textContent === '1/4');
  check(last('/api/replay/hand').source === 'when_i_call', 'replay source');
  check(JSON.stringify(last('/api/replay/hand').options) === JSON.stringify(last(metric).options), 'replay spot filters match metric');
  check(last('/api/replay/hand').table_format === '6max', 'replay global filter');
  q('#replayNextHand').click();
  await until(() => q('#replayPage').textContent === '2/4');
  q('#replayNextFrame').click();
  check(q('#replayStepLabel').textContent.startsWith('2 /'), 'replay frame navigation');
  q('#replayClose').click();

  q('#wicFlopDetailEnable').click();
  await until(() => !q('#wicReplayBtn').disabled);
  check(JSON.stringify(last(metric).options.streets) === '["flop","turn","river"]', 'flop detail street defaults');
  check(q('#wicStreetGroup input[value="preflop"]').disabled, 'flop detail blocks preflop');
  q('#wicFlopTextureGroup [data-key="has_ace"].flop-tex-enable').click();
  q('#wicFlopTextureGroup input[name="wic-flop-has_ace"][value="false"]').click();
  await until(() => stats()[0] === '0');
  check(q('#wirFlopTextureGroup input[name="wir-flop-has_ace"][value="true"]').checked, 'texture radio names isolated');
  check(last(metric).options.flop_textures.has_ace === false, 'texture false polarity sent');
  q('#wicFlopTextureGroup [data-key="has_ace"].flop-tex-enable').click();
  q('#wicTurnDetailEnable').click();
  q('#wicTurnFlopLineGroup input[value="flop_call"]').click();
  await until(() => stats()[0] === '2' && stats()[1] === '1');
  check(JSON.stringify(last(metric).options.streets) === '["turn","river"]', 'turn detail street defaults');
  check(q('#wicStreetGroup input[value="flop"]').disabled, 'turn detail blocks flop');
  check(!q('#wicTurnFlopLineRow').hidden, 'turn line controls shown');
  q('#wicReplayBtn').click();
  await until(() => q('#replayPage').textContent === '1/1');
  check(last('/api/replay/hand').options.turn_flop_lines[0] === 'flop_call', 'turn line replay options');
  q('#replayClose').click();
  q('#wicTurnDetailEnable').click();
  q('#wicFlopDetailEnable').click();
  choose('#wicStreetGroup', ['ALL']);
  await until(() => stats()[0] === '6');

  holdNext = true;
  choose('#wicSizeGroup', ['small']);
  await until(() => !!releaseHeld);
  choose('#wicSizeGroup', ['medium']);
  await until(() => stats()[0] === '6');
  releaseHeld(); releaseHeld = null;
  await new Promise(r=>setTimeout(r,150));
  check(stats()[0] === '6', 'stale async response cannot replace newer data');

  q('#tableFormatGroup input[value="9max"]').click();
  check(!q('#wicRelativePositionRow').hidden && q('#wicHeroPositionRow').hidden, '9max uses relative positions');
  check(q('#wicReplayBtn').disabled && q('#wicShowdownWrap').hidden, 'table change invalidates WIC results');
  choose('#wicPositionGroup', ['OOP']);
  await until(() => stats()[0] === '1');
  check(last(metric).table_format === '9max' && !('hero_positions' in last(metric).options), '9max request excludes exact positions');
  q('#tableFormatGroup input[value="6max"]').click();
  q('#analyzeBtn').click();
  await until(() => q('#filterStatus').textContent.startsWith('已分析'));
  check(qa('#wicHeroPositionGroup input:checked').length === 6, 'returning to exact mode clears old filters');
  const wicBefore = requests.filter(r=>r.url===metric).length;
  q('#wirSizeGroup input[value="small"]').click();
  await pause();
  check(requests.filter(r=>r.url===metric).length === wicBefore, 'WIR live refresh does not request WIC');

  q('#resetFilterBtn').click();
  check(!q('#tableFormatGroup input:checked') && q('#wicHeroPositionRow').hidden, 'global reset syncs position mode');
  check(q('#wicReplayBtn').disabled, 'global reset invalidates replay');
  q('#tableFormatGroup input[value="6max"]').click();
  q('#analyzeBtn').click();
  await until(() => q('#filterStatus').textContent.startsWith('已分析'));
  q('#reloadBtn').click();
  await until(() => q('#filterStatus').textContent.includes('数据已重新扫描'));
  check(q('#panels').hidden && q('#wicShowdownWrap').hidden && q('#wicReplayBtn').disabled, 'data reload clears visible analysis');
  q('#tableFormatGroup input[value="6max"]').click();
  q('#analyzeBtn').click();
  await until(() => q('#filterStatus').textContent.startsWith('已分析'));
  check(stats()[0] === '6', 'WIC reanalyzes after reload');
  q('#panel-when_i_call').scrollIntoView();
  return {ok:true, passed};
})()
