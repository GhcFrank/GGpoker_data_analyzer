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
- **When I Raise**：你下注或加注后，对手弃牌 / 跟注 / 再加注的频率；可按轮次、人数、位置、下注 size、Flop 牌面细分
- **When I Call**：Hero 面对对手下注/加注并跟注的样本分析；支持轮次、人数、位置、对手下注 size、Flop/Turn 细分、单挑对手亮牌范围及筛选手牌回放。6-max 单挑可按 Hero / 对手精确位置筛选。

牌谱目录会记住，下次启动自动用上次的路径。文件夹里有新牌谱时，点「重新扫描」即可。

## When I Call 验证

针对性测试：`PYTHONPATH=poker_analyzer python3 -m unittest tests.test_when_i_call tests.test_when_i_raise`。

浏览器回归：`node tests/check_when_i_call_browser.mjs`。需要 Node.js 22+、Python 和本机 Chrome；可用 `PYTHON_BIN` / `CHROME_BIN` 指定可执行文件。脚本用临时牌局启动本地服务，检查筛选、亮牌矩阵、回放、异步响应和重载，结束后关闭服务并清理临时目录。应用本身仍只依赖 Python 标准库。
