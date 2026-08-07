# Poker Analyzer (Phase 1)

本地扑克牌谱分析网页。数据默认读取项目根目录下的 `data/` 文件夹（GG Poker 文本牌谱）。

## 架构

```
poker_analyzer/
  app.py                 # FastAPI 入口与 HTTP 路由
  poker/
    parser.py            # 牌谱解析 → Hand
    models.py            # Hand / HandDataset
    service.py           # 加载 + 调度 metric
    sources/             # 数据源抽象（本地目录 / 预留上传）
    metrics/             # 每个分析指标一个插件
      base.py            # Metric 接口 + 注册表
      profit.py          # 盈利曲线（抽水前 / 抽水后）
  templates/ / static/   # 前端
```

- **新增指标**：在 `poker/metrics/` 新建文件，实现 `Metric`，用 `@register` 注册；再加 `/api/metrics/{id}` 即可被前端调用。
- **数据源**：当前 `LocalDirectorySource`；`TextUploadSource` 已预留，后续可接拖拽上传。

## 启动

双击 `run_local.bat`（纯本地，图表库已内置，不访问外网），会自动打开浏览器。

或手动启动：

```bash
cd poker_analyzer
pip install -r requirements.txt
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

浏览器打开 http://127.0.0.1:8000

## 第一期指标

| 指标 | 接口 |
|------|------|
| 盈利曲线（抽水前 / 抽水后） | `GET /api/metrics/profit_curve` 或 `GET /api/profit/curve` |

- 抽水后 = `collected - (invested - returned)`
- 抽水前 = 抽水后 + Hero 分摊的 Rake（按收池比例）
