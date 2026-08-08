# Poker Analyzer (本地离线)

纯本地扑克牌谱分析网页。**无需 pip 安装任何第三方包**，只用 Python 标准库。  
图表库已内置在 `static/js/`，不访问外网。

## 启动

双击 `run.bat`。会自动打开浏览器：http://127.0.0.1:8000  
窗口请保持打开；关掉即停止服务。若启动失败，窗口会停住显示错误信息。

手动启动：

```bash
cd poker_analyzer
python app.py
```

## 数据目录

- 默认：项目上一级的 `all_hand/`（可用页面「数据目录」修改）
- 页面可 **浏览…** 选文件夹，或粘贴路径后点 **加载**
- 选择会写入 `local_settings.json`，下次启动自动沿用
- 「重新扫描」：同一目录下新增/更新了 `.txt` 牌谱后刷新

## 架构

```
poker_analyzer/
  app.py                 # 标准库 HTTP 服务（127.0.0.1）
  poker/
    config.py            # 数据路径配置 / 文件夹对话框
    parser.py            # 牌谱解析 → Hand
    models.py            # Hand / HandDataset
    service.py           # 加载 + 调度 metric
    sources/             # 本地目录数据源
    metrics/             # 分析指标插件
  templates/ / static/   # 前端（本地静态资源）
```

- **新增指标**：在 `poker/metrics/` 新建文件，实现 `Metric`，用 `@register` 注册。
- **接口**：`POST /api/metrics/{id}`，body 示例：

```json
{ "date_from": "2026-08-01", "date_to": "2026-08-07", "stakes": ["0.05/0.1"] }
```

| 指标 | 接口 |
|------|------|
| 盈利曲线（抽水前 / 抽水后） | `GET/POST /api/metrics/profit_curve` |

- 费用后（真实盈亏）= `collected - (invested - returned)`
- 费用前 = 费用后 + Hero 分摊的桌费（Rake + Jackpot 等，按收池比例；与 GG 费用前口径一致）
