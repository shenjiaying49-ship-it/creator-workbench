# 大号自媒体工作台

把 Jocelyn 大号的小红书创作流程封装成的本地网页应用：素材箱 → 创作流程 → 稿件库 → 排期看板 → 数据分析。

## 启动

```bash
python3 server.py
# 或双击 启动.command
```

打开 http://127.0.0.1:8501

> 首次使用：`cp config.example.json config.json`，把 `llm.api_key` 换成你自己的 key（`config.json` 与 `data/` 均不入库）。

- 主工作台：`/index.html`
- 数据分析：`/analytics.html`

## 功能

### 1. 素材箱
- 粘贴参考材料（对标笔记、X 帖子转述、商单 brief 文本）
- 上传 PDF / 图片 / markdown 文件
- 勾选「本篇使用」的素材会自动带入 AI 生成上下文

### 2. 创作流程（四步）
- Step 1 选题角度：AI 生成 3 个切入角度 + 内容线判断
- Step 2 标题候选：按标题方法论出 5 个候选，点击选定
- Step 3 正文初稿：基于素材 + 标题生成，严格 1000 字以内
- Step 4 精修定稿：手动编辑或输入意见让 AI 打磨，实时字数统计

商单模式：勾选后自动启用「不说满」规则（技术表述留余地、附品牌确认清单）。

### 3. 稿件库
状态流转：素材 → 草稿 → 待确认 → 已发布。已发布稿件可一键跳数据分析页补录数据。

### 4. 数据分析（独立页面）
- 录入每篇笔记 24h / 7 天的观看、赞、藏、评、分享、涨粉、主页访问
- 概览卡 / 发布趋势图 / 转化漏斗 / 内容线对比 / 单篇表现表（可排序）
- 多账号切换（Jocelyn / Yuki.AI）

## AI 生成配置

编辑 `config.json`：

```json
{
  "llm": {
    "base_url": "https://openrouter.ai/api/v1/chat/completions",
    "api_key": "你的 key",
    "model": "anthropic/claude-sonnet-4"
  }
}
```

兼容任何 OpenAI 格式的接口。未配置 API Key 时，素材箱、稿件库、数据分析均可正常使用，只有 AI 生成按钮会报错提示。

## 数据存储

- `data/materials.json` 素材
- `data/posts.json` 稿件
- `data/analytics.json` 数据录入
- `data/uploads/` 上传的文件

全部为本地 JSON，可随时备份或迁移。

## 演示数据

已导入 Yuki.AI 18 篇历史稿件 + 15 条数据记录。在数据分析页切换到 Yuki.AI 账号即可查看效果。如需清空重导，删除 `data/posts.json` 和 `data/analytics.json` 后运行 `python3 import_yuki_demo.py`。
