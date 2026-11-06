> 2026-11-06 最新主流程以 [每天一篇、五库驱动](DAILY-CREATION.md) 为准。首页交付可编辑日稿；下文旧管理功能保留为辅助入口。

# 架构
现有：server.py HTTP服务 → growth.py → data/growth_workspace.json；前端 static/daily.html、growth.js、growth.css。五库由 tools/wuku_sync.py 拉取生成 static/wuku-data.json。

本轮已实现：growth_cycle.py 封装五库读取、评分、发布登记与实验、Skill任务包；growth.py保持统一锁、原子保存、版本冲突检查。新增 static/cycle.js、cycle.css，复用既有表单和状态。
新增数据字段：ratings（topic_id映射）、publications（id/title/date）、experiments（id/title/hypothesis/variable/observation/next）、capacity（3篇/180分钟）。兼容旧JSON，读取使用默认值。
GET /api/growth 增加cycle（五库内容、发布登记、实验、评分）；POST /api/growth/rating|publication|experiment 与原version契约一致；POST /api/growth/assist显式调用现有LLM，不执行本地shell或外部发布。
五库导出新增topics_list/review_list，保留record_id和完整日期；失败不覆盖旧文件。所有表串行分页读取；本地写与飞书写分离。新页面不触发旧发布回写接口。
密钥留在原config.json，禁止复制到前端、测试、提交或文档。仅使用现有LLM调用配置。无新依赖。
测试：临时目录单元/接口测试；浏览器验证选题→排期、发布→到期提醒、回填→复盘及移动端。用户数据不用于测试写入。
部署：备份本轮触及文件，替换文件后重启本地8501服务。恢复备份并重启；新增JSON字段可保留，旧代码忽略。已有大量用户未提交改动，不混入提交。

POST /api/growth/sync：串行调用同步脚本，180秒超时，同步锁防重复；失败保留最后成功快照。五库读取已在8501实际验证（2026-11-06）。本地服务已重启。未验证真实付费LLM成功路径，隔离模拟失败路径已验证。

周历通过前端weekOffset切换，首页仍显示真实本周统计；排期context包含生产说明，点击AI任务包带入原有输入字段。源码发布前将私人persona迁移到data/wuku_persona.txt，五库标识迁移到config.json的wuku.base_token（支持WUKU_BASE_TOKEN覆盖）；本地旧记录已保存，不再在initial中硬编码个人粉丝快照。
