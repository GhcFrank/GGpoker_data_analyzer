(async () => {
  const q = selector => document.querySelector(selector);
  const qa = selector => [...document.querySelectorAll(selector)];
  const passed = [];
  function check(value, name) { if (!value) throw Error(name); passed.push(name); }
  async function until(predicate) {
    for (let n = 0; n < 200; n++) {
      if (predicate()) return;
      await new Promise(resolve => setTimeout(resolve, 30));
    }
    throw Error('timeout ' + predicate.toString());
  }
  function choose(group, values) {
    const inputs = qa(group + ' input');
    inputs.forEach(input => { input.checked = values.includes(input.value); });
    (inputs.find(input => input.checked) || inputs[0]).dispatchEvent(new Event('change', { bubbles: true }));
  }
  const stats = () => qa('#whenIRaiseStats .value').map(element => element.textContent.trim());
  const statValue = label => qa('#whenIRaiseStats .stat').find(card =>
    card.querySelector('.label').textContent === label)?.querySelector('.value').textContent.trim();
  const selected = group => qa(group + ' input:checked').map(input => input.value);
  await until(() => q('#summaryText').textContent.includes('已加载'));
  const requests = [];
  const originalFetch = window.fetch;
  let holdNext = false;
  let releaseHeld;
  window.fetch = async (url, init) => {
    const held = url === '/api/metrics/when_i_raise' && holdNext;
    if (held) holdNext = false;
    if (init?.body) requests.push({ url, body: JSON.parse(init.body) });
    const response = await originalFetch(url, init);
    if (held) return new Promise(resolve => { releaseHeld = () => resolve(response); });
    return response;
  };
  const metric = '/api/metrics/when_i_raise';
  const last = url => requests.filter(request => request.url === url).at(-1)?.body;
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
  check(JSON.stringify(selected('#wirPotTypeGroup')) === '["srp","3bet","4bet","5bet"]', 'WIR defaults to all four Pot Types');
  check(qa('#wirPotTypeGroup .stake-chip span').map(element => element.textContent).join('|') ===
    'Single Raised Pot|3-Bet Pot|4-Bet Pot|5-Bet Pot', 'WIR Pot Type labels');
  check(qa('#wirStreetGroup input').map(input => input.value).join('|') === 'ALL|flop|turn|river', 'WIR target streets exclude preflop');
  check(qa('#wicStreetGroup input').map(input => input.value).join('|') === 'ALL|flop|turn|river', 'WIC targets postflop streets only');
  check(qa('#wirSizeGroup input').map(input => input.value).join('|') === 'check|small|medium|large|overbet' &&
    q('#wirSizeGroup input[value="check"]').checked, 'WIR Hero Action / Size includes Check by default');
  q('#tableFormatGroup input[value="6max"]').click();
  q('#analyzeBtn').click();
  await until(() => q('#filterStatus').textContent.startsWith('已分析'));
  check(stats()[0] === '9' && stats()[1] === '5', 'WIR General includes aggression and ordered Hero Check spots');
  check(qa('#whenIRaiseStats .label').map(element => element.textContent).join('|') ===
    '样本数|涉及手数|All Fold|Call|Reraise|Opponent Check|Opponent Bet',
    'WIR General shows both outcome groups');
  check(statValue('Call').includes('57.14%') && statValue('Opponent Check').includes('50.00%') &&
    statValue('Opponent Bet').includes('50.00%'), 'WIR outcome groups use separate denominators');
  check(qa('#whenIRaiseStats .stat-replay').length === 7 &&
    getComputedStyle(q('#whenIRaiseStats .stat-replay')).cursor === 'pointer',
    'nonzero WIR statistics are visibly clickable');
  const allWIRHands = ['wir-3bet', 'wir-3bet-unknown', 'wir-check-bet', 'wir-check-check', 'wir-srp'];
  const baseStatButtons = qa('#whenIRaiseStats .stat-replay:not([data-replay-outcome])');
  const sampleReplay = await openStatReplay(baseStatButtons[0]);
  check(sampleReplay.total === 5 && JSON.stringify(sampleReplay.ids) === JSON.stringify(allWIRHands) &&
    !('replay_outcome' in sampleReplay.firstRequest.options),
    'WIR sample count opens every distinct matching hand without an outcome filter');
  const handReplay = await openStatReplay(baseStatButtons[1]);
  check(handReplay.total === 5 && JSON.stringify(handReplay.ids) === JSON.stringify(allWIRHands) &&
    !('replay_outcome' in handReplay.firstRequest.options),
    'WIR hand count opens the same distinct matching hands');
  for (const [outcome, expected] of [
    ['all_fold', ['wir-3bet-unknown', 'wir-srp']],
    ['call', ['wir-3bet', 'wir-3bet-unknown', 'wir-check-bet', 'wir-srp']],
    ['reraise', ['wir-3bet']],
    ['opponent_check', ['wir-check-check']],
    ['opponent_bet', ['wir-check-bet']],
  ]) {
    const replay = await openStatReplay(q(`#whenIRaiseStats [data-replay-outcome="${outcome}"]`));
    check(replay.firstRequest.options.replay_outcome === outcome &&
      JSON.stringify(replay.ids) === JSON.stringify(expected),
      `WIR ${outcome} statistic opens its distinct matching hands`);
  }
  check(stats()[0] === '9' && stats()[1] === '5', 'closing WIR statistic replay preserves panel results');
  const originalWIRSizes = selected('#wirSizeGroup');
  const wicSizesBeforeWIRClear = JSON.stringify(selected('#wicSizeGroup'));
  const wirOtherFiltersBeforeSizeClear = JSON.stringify({
    potTypes: selected('#wirPotTypeGroup'),
    streets: selected('#wirStreetGroup'),
    players: selected('#wirPlayersGroup'),
    positions: selected('#wirPositionGroup'),
  });
  const wirRequestsBeforeSizeClear = requests.filter(request => request.url === metric).length;
  check(q('#wirActionSizeUnselectAll').classList.contains('stake-chip-btn') &&
    q('#wirActionSizeUnselectAll').getAttribute('aria-label') === 'Hero Action / Size: Unselect All',
    'WIR Action / Size Unselect All reuses the accessible position button style');
  q('#wirActionSizeUnselectAll').click();
  await until(() => stats()[0] === '0');
  check(selected('#wirSizeGroup').length === 0, 'WIR Action / Size Unselect All clears every chip');
  check(requests.filter(request => request.url === metric).length > wirRequestsBeforeSizeClear &&
    JSON.stringify(last(metric).options.sizes) === '[]' && !q('#whenIRaiseEmpty').hidden,
    'WIR Action / Size Unselect All refreshes with an empty sizes array');
  check(JSON.stringify(selected('#wicSizeGroup')) === wicSizesBeforeWIRClear &&
    JSON.stringify({
      potTypes: selected('#wirPotTypeGroup'),
      streets: selected('#wirStreetGroup'),
      players: selected('#wirPlayersGroup'),
      positions: selected('#wirPositionGroup'),
    }) === wirOtherFiltersBeforeSizeClear,
    'WIR Action / Size Unselect All preserves WIC and other WIR filters');
  choose('#wirSizeGroup', originalWIRSizes);
  await until(() => stats()[0] === '9' && stats()[1] === '5');
  choose('#wirSizeGroup', ['check']);
  await until(() => stats()[0] === '2' && stats()[1] === '2');
  check(JSON.stringify(last(metric).options.sizes) === '["check"]' &&
    qa('#whenIRaiseStats .label').map(element => element.textContent).join('|') ===
      '样本数|涉及手数|Opponent Check|Opponent Bet',
    'WIR Check-only mode hides aggression outcomes');
  choose('#wirPositionGroup', ['IP']);
  await until(() => stats()[0] === '1');
  const zeroOpponentCheck = qa('#whenIRaiseStats .stat').find(card =>
    card.querySelector('.label').textContent === 'Opponent Check');
  const replayRequestsBeforeZeroCheck = requests.filter(request => request.url === '/api/replay/hand').length;
  zeroOpponentCheck.click();
  check(!zeroOpponentCheck.matches('.stat-replay') && getComputedStyle(zeroOpponentCheck).cursor !== 'pointer' &&
    requests.filter(request => request.url === '/api/replay/hand').length === replayRequestsBeforeZeroCheck,
    'zero-count WIR Opponent Check card is disabled');
  choose('#wirPositionGroup', ['IP', 'OOP', 'OTHER']);
  choose('#wirSizeGroup', ['check', 'small']);
  await until(() => stats()[0] === '6' && stats()[1] === '5');
  check(statValue('Call').includes('100.00%') && statValue('Opponent Bet').includes('50.00%'),
    'WIR Check plus Small keeps independent outcome percentages');
  choose('#wirSizeGroup', ['small']);
  await until(() => stats()[0] === '4' && !q('#whenIRaiseStats [data-replay-outcome="opponent_bet"]'));
  check(!qa('#whenIRaiseStats .label').some(element => element.textContent.startsWith('Opponent ')),
    'deselecting WIR Check hides Check outcomes');
  choose('#wirSizeGroup', ['check', 'small', 'medium', 'large', 'overbet']);
  await until(() => stats()[0] === '9');
  choose('#wicPlayersGroup', ['2']);
  const wicPositions = () => JSON.stringify([
    selected('#wicPositionGroup'), selected('#wicHeroPositionGroup'), selected('#wicOpponentPositionGroup'),
  ]);
  const originalWicPositions = wicPositions();
  const wicRequests = requests.filter(request => request.url === '/api/metrics/when_i_call').length;
  choose('#wirPotTypeGroup', ['srp']);
  await until(() => stats()[0] === '5' && stats()[1] === '3');
  check(JSON.stringify(last(metric).options.pot_types) === '["srp"]', 'SRP refresh sends pot_types');
  const zeroReraise = qa('#whenIRaiseStats .stat').find(card =>
    card.querySelector('.label').textContent === 'Reraise');
  const replayRequestsBeforeZero = requests.filter(request => request.url === '/api/replay/hand').length;
  zeroReraise.click();
  check(!zeroReraise.matches('.stat-replay') && getComputedStyle(zeroReraise).cursor !== 'pointer' &&
    requests.filter(request => request.url === '/api/replay/hand').length === replayRequestsBeforeZero,
    'zero-count WIR statistic is not clickable and does not open an empty replay');
  choose('#wirPotTypeGroup', ['3bet']);
  await until(() => stats()[0] === '4' && stats()[1] === '2');
  check(JSON.stringify(last(metric).options.pot_types) === '["3bet"]', '3bet refresh sends pot_types');
  choose('#wirPotTypeGroup', []);
  await until(() => stats()[0] === '0');
  check(last(metric).options.pot_types.length === 0 && !q('#whenIRaiseEmpty').hidden, 'empty Pot Type selection produces zero samples');
  choose('#wirPotTypeGroup', ['3bet']);
  q('#wirPlayersGroup input[value="3+"]').click();
  await until(() => stats()[0] === '4');
  check(selected('#wirHeroPositionGroup').length === 6 && selected('#wirOpponentPositionGroup').length === 6 &&
    selected('#wicHeroPositionGroup').length === 6 && selected('#wicOpponentPositionGroup').length === 6,
    'WIR and WIC exact-position controls start with all six positions selected');
  for (const [axis, otherAxis, option, otherOption] of [
    ['Hero', 'Opponent', 'hero_positions', 'opponent_positions'],
    ['Opponent', 'Hero', 'opponent_positions', 'hero_positions'],
  ]) {
    const group = `#wir${axis}PositionGroup`;
    const originalPositions = selected(group);
    const otherPositions = JSON.stringify(selected(`#wir${otherAxis}PositionGroup`));
    q(`#wir${axis}PositionUnselectAll`).click();
    check(selected(group).length === 0, `${axis} Unselect All clears every selected chip`);
    check(JSON.stringify(selected(`#wir${otherAxis}PositionGroup`)) === otherPositions,
      `${axis} Unselect All preserves ${otherAxis} chips`);
    await until(() => stats()[0] === '0');
    check(JSON.stringify(last(metric).options[option]) === '[]' &&
      JSON.stringify(last(metric).options[otherOption]) === otherPositions && !q('#whenIRaiseEmpty').hidden,
      `${axis} Unselect All refresh sends only its axis empty and returns zero samples`);
    check(wicPositions() === originalWicPositions && q('#wicHeroPositionUnselectAll') &&
      q('#wicOpponentPositionUnselectAll'),
      `${axis} Unselect All leaves WIC position UI unchanged`);
    choose(group, originalPositions);
    await until(() => stats()[0] === '4');
  }
  choose('#wirStreetGroup', ['turn']);
  choose('#wirSizeGroup', ['large']);
  choose('#wirHeroPositionGroup', ['BTN']);
  choose('#wirOpponentPositionGroup', ['BB']);
  await until(() => stats()[0] === '2' && stats()[1] === '2');
  check(last(metric).options.pot_types[0] === '3bet' && last(metric).options.streets[0] === 'turn' &&
    last(metric).options.sizes[0] === 'large', 'Pot Type combines with Turn and Hero Size');
  check(qa('#wirShowdownCells td').length === 169 && q('#wirShowdownStatus').textContent === '已知对手手牌：1 / 2', 'WIR grid filters by Pot Type and retains unknown denominator');
  check(qa('#wirShowdownCells td')[13].textContent.includes('50.00%'), 'WIR AKo percentage uses matching hand count');
  q('#wirReplayBtn').click();
  await until(() => q('#replayPage').textContent === '1/2');
  check(last('/api/replay/hand').source === 'when_i_raise' &&
    JSON.stringify(last('/api/replay/hand').options) === JSON.stringify(last(metric).options), 'WIR replay receives identical Pot Type and spot filters');
  q('#replayNextHand').click();
  await until(() => q('#replayPage').textContent === '2/2');
  check(q('#replayMeta').textContent.includes('wir-3bet-unknown'), 'WIR replay excludes other Pot Types');
  q('#replayClose').click();
  q('#wirTurnDetailEnable').click();
  choose('#wirTurnFlopLineGroup', ['flop_raise']);
  await until(() => stats()[0] === '2');
  check(last(metric).options.turn_flop_lines[0] === 'flop_raise', 'Pot Type preserves Turn Detail options');
  choose('#wirTurnFlopLineGroup', ['flop_checkcheck']);
  await until(() => stats()[0] === '0');
  check(!q('#whenIRaiseEmpty').hidden, 'Turn Detail still excludes nonmatching flop lines');
  q('#wirTurnDetailEnable').click();
  choose('#wirStreetGroup', ['ALL']);
  choose('#wirSizeGroup', ['small', 'medium', 'large', 'overbet']);
  await until(() => stats()[0] === '4');
  holdNext = true;
  choose('#wirPotTypeGroup', ['srp']);
  await until(() => !!releaseHeld);
  choose('#wirPotTypeGroup', ['3bet']);
  await until(() => stats()[0] === '4');
  releaseHeld();
  await new Promise(resolve => setTimeout(resolve, 150));
  check(stats()[0] === '4', 'stale Pot Type response cannot replace latest results');
  check(requests.filter(request => request.url === '/api/metrics/when_i_call').length === wicRequests,
    'WIR Pot Type and spot filters never refresh WIC');
  check(last('/api/metrics/when_i_call').options.pot_types.length === 4, 'WIC payload keeps its own Pot Type gate');

  q('#tableFormatGroup input[value="9max"]').click();
  q('#analyzeBtn').click();
  await until(() => q('#filterStatus').textContent.startsWith('已分析'));
  check(last(metric).table_format === '9max' && last(metric).options.pot_types[0] === '3bet' &&
    !('hero_positions' in last(metric).options), 'table-format change preserves Pot Type and uses relative positions');
  q('#resetFilterBtn').click();
  q('#tableFormatGroup input[value="6max"]').click();
  q('#analyzeBtn').click();
  await until(() => q('#filterStatus').textContent.startsWith('已分析'));
  check(stats()[0] === '4' && last(metric).options.pot_types[0] === '3bet', 'new analysis after global reset uses current panel filters');
  q('#reloadBtn').click();
  await until(() => q('#filterStatus').textContent.includes('数据已重新扫描'));
  q('#tableFormatGroup input[value="6max"]').click();
  q('#analyzeBtn').click();
  await until(() => q('#filterStatus').textContent.startsWith('已分析'));
  check(stats()[0] === '4' && last(metric).options.pot_types[0] === '3bet', 'Pot Type works after data reload');
  return { ok: true, passed };
})()
