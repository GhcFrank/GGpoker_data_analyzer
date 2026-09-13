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
  const statValue = label => qa('#whenICallStats .stat').find(card =>
    card.querySelector('.label').textContent === label)?.querySelector('.value').textContent.trim();
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
  const selected = group => qa(group + ' input:checked').map(input => input.value);
  async function openStatReplay(button) {
    const before = requests.filter(request => request.url === '/api/replay/hand').length;
    button.click();
    await until(() => requests.filter(request => request.url === '/api/replay/hand').length > before &&
      !q('#replayOverlay').hidden && !q('#replayStage .replay-loading'));
    const firstRequest = last('/api/replay/hand');
    const total = Number(q('#replayPage').textContent.split('/')[1]);
    const ids = [];
    for (let index = 0; index < total; index++) {
      await until(() => q('#replayPage').textContent === `${index + 1}/${total}`);
      ids.push(q('#replayMeta').textContent.split('#').at(-1));
      if (index + 1 < total) q('#replayNextHand').click();
    }
    q('#replayClose').click();
    return { firstRequest, ids: ids.sort(), total };
  }
  check(qa('[id]').length === new Set(qa('[id]').map(e=>e.id)).size, 'DOM ids unique');
  q('#tableFormatGroup input[value="6max"]').click();
  q('#analyzeBtn').click();
  await until(() => q('#filterStatus').textContent.startsWith('已分析'));
  check(stats()[0] === '12' && stats()[1] === '10', 'WIC General includes aggression and checked-to-Hero decisions');
  check(qa('#whenICallStats .label').map(e=>e.textContent).join('|') ===
    '样本数|涉及手数|Hero Fold|Hero Call|Hero Raise|Hero Check|Hero Bet',
    'WIC General shows both outcome groups');
  check(stats().slice(2).every(value => !value.includes('—')) &&
    stats()[2].includes('20.00%') && stats()[3].includes('60.00%') && stats()[4].includes('20.00%'),
    'WIC aggression percentages keep their original denominator');
  check(statValue('Hero Check').includes('50.00%') && statValue('Hero Bet').includes('50.00%'),
    'WIC checked-to-Hero outcomes use the Check-spot denominator');
  check(qa('#wicPotTypeGroup input:checked').map(e=>e.value).join('|') === 'srp|3bet|4bet|5bet',
    'WIC defaults to SRP 3BP 4BP 5BP');
  check(qa('#wicStreetGroup input').map(e=>e.value).join('|') === 'ALL|flop|turn|river',
    'WIC target streets are postflop only');
  check(qa('#wicSizeGroup input').map(input => input.value).join('|') === 'check|small|medium|large|overbet' &&
    q('#wicSizeGroup input[value="check"]').checked, 'WIC Opponent Action / Size includes Check by default');
  check(qa('#whenICallStats .label').every(e=>!e.textContent.startsWith('Facing ')), 'Facing cards are absent');
  check(qa('#whenIRaiseStats .value')[0].textContent.trim() === '9', 'WIR result includes its own Check fixtures');
  check(q('#wicShowdownWrap').hidden, 'mixed counts hide range');
  check(q('#panel-when_i_call').previousElementSibling.id === 'panel-when_i_raise', 'panel order');
  check(qa('#whenICallStats .stat-replay').length === 7 &&
    getComputedStyle(q('#whenICallStats .stat-replay')).cursor === 'pointer',
    'nonzero WIC statistics are visibly clickable');
  const allWICHands = [
    'fold-small', 'raise-large', 'suited', 'triple', 'unknown', 'wic-3bet', 'wic-4bet', 'wic-5bet',
    'wic-check-bet', 'wic-check-check',
  ];
  const baseStatButtons = qa('#whenICallStats .stat-replay:not([data-replay-outcome])');
  const sampleReplay = await openStatReplay(baseStatButtons[0]);
  check(sampleReplay.total === 10 && JSON.stringify(sampleReplay.ids) === JSON.stringify(allWICHands) &&
    !('replay_outcome' in sampleReplay.firstRequest.options),
    'WIC sample count opens every distinct matching hand without an outcome filter');
  const handReplay = await openStatReplay(baseStatButtons[1]);
  check(handReplay.total === 10 && JSON.stringify(handReplay.ids) === JSON.stringify(allWICHands) &&
    !('replay_outcome' in handReplay.firstRequest.options),
    'WIC hand count opens the same distinct matching hands');
  for (const [outcome, expected] of [
    ['hero_fold', ['fold-small', 'wic-4bet']],
    ['hero_call', ['suited', 'triple', 'unknown', 'wic-3bet']],
    ['hero_raise', ['raise-large', 'wic-5bet']],
    ['hero_check', ['wic-check-check']],
    ['hero_bet', ['wic-check-bet']],
  ]) {
    const replay = await openStatReplay(q(`#whenICallStats [data-replay-outcome="${outcome}"]`));
    check(replay.firstRequest.options.replay_outcome === outcome &&
      JSON.stringify(replay.ids) === JSON.stringify(expected),
      `WIC ${outcome} statistic opens its distinct matching hands`);
  }
  check(stats()[0] === '12' && stats()[1] === '10', 'closing WIC statistic replay preserves panel results');
  const originalWICSizes = selected('#wicSizeGroup');
  const wirSizesBeforeWICClear = JSON.stringify(selected('#wirSizeGroup'));
  const wicOtherFiltersBeforeSizeClear = JSON.stringify({
    potTypes: selected('#wicPotTypeGroup'),
    streets: selected('#wicStreetGroup'),
    players: selected('#wicPlayersGroup'),
    positions: selected('#wicPositionGroup'),
  });
  const wicRequestsBeforeSizeClear = requests.filter(request => request.url === metric).length;
  check(q('#wicActionSizeUnselectAll').classList.contains('stake-chip-btn') &&
    q('#wicActionSizeUnselectAll').getAttribute('aria-label') === 'Opponent Action / Size: Unselect All',
    'WIC Action / Size Unselect All reuses the accessible position button style');
  q('#wicActionSizeUnselectAll').click();
  await until(() => stats()[0] === '0');
  check(selected('#wicSizeGroup').length === 0, 'WIC Action / Size Unselect All clears every chip');
  check(requests.filter(request => request.url === metric).length > wicRequestsBeforeSizeClear &&
    JSON.stringify(last(metric).options.sizes) === '[]' && !q('#whenICallEmpty').hidden,
    'WIC Action / Size Unselect All refreshes with an empty sizes array');
  check(JSON.stringify(selected('#wirSizeGroup')) === wirSizesBeforeWICClear &&
    JSON.stringify({
      potTypes: selected('#wicPotTypeGroup'),
      streets: selected('#wicStreetGroup'),
      players: selected('#wicPlayersGroup'),
      positions: selected('#wicPositionGroup'),
    }) === wicOtherFiltersBeforeSizeClear,
    'WIC Action / Size Unselect All preserves WIR and other WIC filters');
  choose('#wicSizeGroup', originalWICSizes);
  await until(() => stats()[0] === '12' && stats()[1] === '10');
  choose('#wicSizeGroup', ['check']);
  await until(() => stats()[0] === '2' && stats()[1] === '2');
  check(JSON.stringify(last(metric).options.sizes) === '["check"]' &&
    qa('#whenICallStats .label').map(element => element.textContent).join('|') ===
      '样本数|涉及手数|Hero Check|Hero Bet',
    'WIC Check-only mode hides aggression outcomes');
  choose('#wicSizeGroup', ['check', 'small']);
  await until(() => stats()[0] === '4' && stats()[1] === '4');
  check(statValue('Hero Fold').includes('50.00%') && statValue('Hero Call').includes('50.00%') &&
    statValue('Hero Check').includes('50.00%') && statValue('Hero Bet').includes('50.00%'),
    'WIC Check plus Small keeps independent outcome percentages');
  choose('#wicSizeGroup', ['small']);
  await until(() => stats()[0] === '2' && !q('#whenICallStats [data-replay-outcome="hero_bet"]'));
  check(!qa('#whenICallStats .label').some(element => ['Hero Check', 'Hero Bet'].includes(element.textContent)),
    'deselecting WIC Check hides checked-to-Hero outcomes');
  choose('#wicSizeGroup', ['check', 'small', 'medium', 'large', 'overbet']);
  await until(() => stats()[0] === '12');
  const wirCount = requests.filter(r=>r.url===wirMetric).length;
  q('#wicPlayersGroup input[value="3+"]').click();
  await until(() => qa('#wicShowdownCells td').length === 169);
  check(!q('#wicHeroPositionRow').hidden && q('#wicRelativePositionRow').hidden, '6max HU exact position rows');
  check(getComputedStyle(q('#wicRelativePositionRow')).display === 'none', 'relative row hidden by CSS');
  check(requests.filter(r=>r.url===wirMetric).length === wirCount, 'WIC live refresh does not request WIR');
  check(last(metric).options.hero_positions.length === 6 && !('positions' in last(metric).options), 'exact request excludes relative axis');
  check(q('#wicShowdownStatus').textContent === '已知对手手牌：3 / 10', 'range includes Check matching hands');
  check(qa('#wicShowdownCells td')[13].textContent.includes('10.00%'), 'range AKo uses expanded matching hand denominator');
  const wirPositionState = JSON.stringify([
    selected('#wirPositionGroup'), selected('#wirHeroPositionGroup'), selected('#wirOpponentPositionGroup'),
  ]);
  for (const [axis, otherAxis, option, otherOption] of [
    ['Hero', 'Opponent', 'hero_positions', 'opponent_positions'],
    ['Opponent', 'Hero', 'opponent_positions', 'hero_positions'],
  ]) {
    const group = `#wic${axis}PositionGroup`;
    const originalPositions = selected(group);
    const otherPositions = JSON.stringify(selected(`#wic${otherAxis}PositionGroup`));
    const button = q(`#wic${axis}PositionUnselectAll`);
    check(button.classList.contains('stake-chip-btn'), `${axis} Unselect All reuses the chip button style`);
    button.click();
    check(selected(group).length === 0, `${axis} Unselect All clears every WIC position chip`);
    check(JSON.stringify(selected(`#wic${otherAxis}PositionGroup`)) === otherPositions,
      `${axis} Unselect All preserves the other WIC position axis`);
    await until(() => stats()[0] === '0');
    check(JSON.stringify(last(metric).options[option]) === '[]' &&
      JSON.stringify(last(metric).options[otherOption]) === otherPositions,
      `${axis} Unselect All refresh sends only its WIC axis empty`);
    check(JSON.stringify([
      selected('#wirPositionGroup'), selected('#wirHeroPositionGroup'), selected('#wirOpponentPositionGroup'),
    ]) === wirPositionState, `${axis} Unselect All leaves WIR position UI unchanged`);
    choose(group, originalPositions);
    await until(() => stats()[0] === '12');
  }
  choose('#wicSizeGroup', ['check']);
  choose('#wicHeroPositionGroup', ['BTN']);
  choose('#wicOpponentPositionGroup', ['BB']);
  await until(() => stats()[0] === '1');
  const zeroHeroCheck = qa('#whenICallStats .stat').find(card =>
    card.querySelector('.label').textContent === 'Hero Check');
  const replayRequestsBeforeZeroCheck = requests.filter(request => request.url === '/api/replay/hand').length;
  zeroHeroCheck.click();
  check(!zeroHeroCheck.matches('.stat-replay') && getComputedStyle(zeroHeroCheck).cursor !== 'pointer' &&
    q('#whenICallStats [data-replay-outcome="hero_bet"]') &&
    requests.filter(request => request.url === '/api/replay/hand').length === replayRequestsBeforeZeroCheck,
    'exact-position filtering leaves zero-count Hero Check disabled and Hero Bet clickable');
  choose('#wicHeroPositionGroup', ['UTG', 'HJ', 'CO', 'BTN', 'SB', 'BB']);
  choose('#wicOpponentPositionGroup', ['UTG', 'HJ', 'CO', 'BTN', 'SB', 'BB']);
  choose('#wicSizeGroup', ['check', 'small', 'medium', 'large', 'overbet']);
  await until(() => stats()[0] === '12');
  choose('#wicPotTypeGroup', ['3bet']);
  await until(() => stats()[0] === '1' && stats()[1] === '1');
  check(JSON.stringify(last(metric).options.pot_types) === '["3bet"]', 'Pot Type live refresh sends 3bet');
  choose('#wicPotTypeGroup', ['srp', '3bet', '4bet', '5bet']);
  await until(() => stats()[0] === '12' && stats()[1] === '10');
  choose('#wicSizeGroup', ['large']);
  await until(() => stats()[0] === '1' && stats()[4].includes('100.00%'));
  check(JSON.stringify(last(metric).options.sizes) === '["large"]', 'Opponent Size filters the faced aggression');
  for (const outcome of ['hero_fold', 'hero_call']) {
    const zeroCard = qa('#whenICallStats .stat').find(card =>
      card.querySelector('.label').textContent === (outcome === 'hero_fold' ? 'Hero Fold' : 'Hero Call'));
    const replayRequestsBeforeZero = requests.filter(request => request.url === '/api/replay/hand').length;
    zeroCard.click();
    check(!zeroCard.matches('.stat-replay') && getComputedStyle(zeroCard).cursor !== 'pointer' &&
      requests.filter(request => request.url === '/api/replay/hand').length === replayRequestsBeforeZero,
      `zero-count WIC ${outcome} statistic does not open replay`);
  }
  choose('#wicSizeGroup', ['small', 'medium', 'large', 'overbet']);
  await until(() => stats()[0] === '10');
  check(getComputedStyle(q('#wicFlopTextureRow')).display === 'none', 'flop texture controls hidden initially');
  q('#wicReplayBtn').click();
  await until(() => q('#replayPage').textContent === '1/8');
  check(last('/api/replay/hand').source === 'when_i_call', 'replay source');
  check(JSON.stringify(last('/api/replay/hand').options) === JSON.stringify(last(metric).options), 'replay spot filters match metric');
  check(last('/api/replay/hand').table_format === '6max', 'replay global filter');
  q('#replayNextHand').click();
  await until(() => q('#replayPage').textContent === '2/8');
  q('#replayNextFrame').click();
  check(q('#replayStepLabel').textContent.startsWith('2 /'), 'replay frame navigation');
  q('#replayClose').click();

  q('#wicFlopDetailEnable').click();
  await until(() => !q('#wicReplayBtn').disabled);
  check(JSON.stringify(last(metric).options.streets) === '["flop","turn","river"]', 'flop detail street defaults');
  check(!q('#wicStreetGroup input[value="preflop"]'), 'flop detail has no preflop target');
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
  await until(() => stats()[0] === '10');

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
  check(stats()[0] === '6', 'WIC reanalyzes after reload with retained panel filters');
  q('#panel-when_i_call').scrollIntoView();
  return {ok:true, passed};
})()
