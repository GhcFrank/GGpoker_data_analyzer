# Poker Analyzer

本地离线的扑克牌谱分析工具。读 GG Poker 导出的 `.txt` 牌谱，在浏览器里看结果。  
纯 Python 标准库，不用装第三方包，也不联网。

工程自带便携 Python（`runtime/`），**不用单独安装 Python**。双击 `run.bat` 即可。

## 怎么用

1. 双击 `run.bat`，浏览器会打开 http://127.0.0.1:8000  
2. 选好牌谱所在文件夹，点「加载」  
3. 按日期 / 游戏类型 / 盲注筛一下，点「分析」  
4. 用上方开关打开你想看的分析面板  

关掉黑色窗口就等于关掉服务。也可以手动启动：

```bash
cd poker_analyzer
python app.py
```

## 功能

- **盈利曲线**：按手数看累计盈亏（费用前 / 费用后两条线）
- **When I Raise**：针对 Hero 是进入 Flop 时最后一个翻前进攻者的牌局，按 SRP / 3-Bet / 4-Bet / 5-Bet Pot 分类，分析 `Hero Bet/Raise → Opponent All Fold/Call/Reraise` 和 `Hero Check → Opponent Check/Bet`；保留人数、位置、Hero action/size、Flop/Turn 细分、对手亮牌范围及回放。Pot Type 只按翻前 raise 次数划分（1/2/3/4 次），不计入 6-Bet 及以上牌局。
- **When I Call**：针对 Hero 进入 Flop、翻前至少发生一次 raise、且 Hero 不是最后翻前进攻者的牌局，按 SRP / 3-Bet / 4-Bet / 5-Bet Pot 分类，分析 `Opponent Bet/Raise → Hero Fold/Call/Raise` 和 `Opponent Check → Hero Check/Bet`；支持人数、位置、Opponent action/size、Flop/Turn 细分、单挑对手亮牌范围及筛选手牌回放。6-max 单挑可按 Hero / 当前 opponent 的精确位置筛选。

牌谱目录会记住，下次启动自动用上次的路径。文件夹里有新牌谱时，点「重新扫描」即可。

## When I Raise / When I Call 当前分析范围与暂未覆盖场景

两个模块都以进入 Flop 时的翻前身份划分 hand universe。翻前 raise 次数决定 Pot Type：1/2/3/4 次分别是 SRP、3-Bet、4-Bet、5-Bet Pot；limp 和 cold call 不改变级别。Pure Limped Pot，以及 5 次或更多翻前 raise 的 6-Bet+ Pot，目前都不分析，6-Bet+ 也不会并入 5-Bet Pot。

### When I Raise

- WIR 只分析 Hero 是最后翻前进攻者且实际进入 Flop 的手牌。Hero open 后所有人翻前弃牌不进入 WIR，因此 WIR 不能计算 Hero open 后的 fold-to-open frequency。
- WIR aggression spot 是 Hero 在 Flop / Turn / River 的 bet 或 raise；Check spot 只统计 Hero check 后仍有 opponent 实际行动，并按后续行动归为 Opponent Check 或 Opponent Bet。真实顺序若是 `Opponent check → Hero check → street ends`，不会倒置为 WIR `Hero Check → Opponent Check`。
- PFA 面对 opponent Donk 后的 Hero Fold / Call 尚无对应模块。Hero versus Donk 的 Call/Fold 是明确的 coverage gap；若 Hero 对 Donk raise，该次 Hero aggression 仍可能成为 WIR spot。
- 6-max heads-up 支持 Hero / Opponent exact positions；9-max 和 multiway 继续使用 IP / OOP / OTHER。9-max exact positions 尚未开发。
- 13×13 opponent showdown matrix 仅支持 heads-up，multiway 暂不聚合。
- Multiway 中，同一个 Hero aggression 可以同时得到 Call 和 Reraise。例如一名对手 call、另一名对手 raise 时，两项都为 true，所以 WIR 的 Call% + Reraise% 不保证等于 100%。

### When I Call

- WIC 只分析 Hero 进入 Flop但不是最后翻前进攻者的手牌。spot 可以是实际的 `Opponent bet/raise → Hero Fold/Call/Raise`，也可以是一个或多个 opponent check 到 Hero 后的 `Hero Check/Bet`。真实顺序若是 `Hero check → Opponent check → street ends`，不会倒置为 WIC `Opponent Check → Hero Check`。
- Hero Donk / Lead 暂不纳入 WIC。如果某条 street 由 Hero 主动 bet/raise 开始，则该 street 的整条 Donk line（包括之后 `Opponent raise → Hero call`）不产生 WIC spot。这是有意暂缓的产品设计，因为 Donk hand universe 和 denominator 尚未最终定义，并非 parser 漏识别。Donk 只排除当前 street；后续 street 若正常面对对手 aggression，仍可产生 WIC spot。
- WIC 顶部只显示 matching decision 的 `spot_count` 和至少含一个 matching spot 的 distinct `hand_count`，不提供所有翻前 non-aggressor 手牌的 Eligible Hands denominator。因此当前不能直接计算“对手在所有 eligible hands 中的 bet frequency”。
- Turn Detail 的 Flop Line 是 Check-Check、Hero Call、Hero Raise。Flop Donk line 返回 unclassified / None，不归入这三类。
- Preflop role 只决定 hand universe；postflop target aggressor 取当前实际下注/加注者，可以不是 final preflop aggressor。Multiway 中若其他玩家领打或加注，Hero 的 decision 会绑定到最新 outstanding aggression 的真实 actor。
- 6-max heads-up 支持 Hero / 当前 aggressor exact positions；9-max 和 multiway 继续使用 IP / OOP / OTHER。9-max exact positions 尚未开发。
- 13×13 opponent showdown matrix 仅支持 heads-up。每个 matching hand 最多计一次，未知底牌仍保留在 `hand_count` denominator 中；multiway showdown range 暂不提供。

## When I Raise / When I Call 验证

针对性测试：`PYTHONPATH=poker_analyzer python3 -m unittest tests.test_when_i_call tests.test_when_i_raise`。

浏览器回归：`node tests/check_when_i_call_browser.mjs`。需要 Node.js 22+、Python 和本机 Chrome；可用 `PYTHON_BIN` / `CHROME_BIN` 指定可执行文件。脚本用临时牌局启动本地服务，分别检查 WIC/WIR 的 Pot Type、postflop Street、结果 cards、size、位置、亮牌矩阵、回放、异步响应和重载，结束后关闭服务并清理临时目录。应用本身仍只依赖 Python 标准库。
