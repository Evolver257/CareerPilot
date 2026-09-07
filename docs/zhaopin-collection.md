# 智联招聘完整详情采集

核实日期：2026-09-04。已用公开页面 HTML 运行实际解析器，未调用网站私有接口，也未将核实样本导入用户数据库。

## 页面选择及已核实结构

- 搜索入口：`https://www.zhaopin.com/sou?jl=530&kw=AI%20Agent`。地点通过 `jl` 城市编码传递；采集页面支持输入常用城市名称（自动转换编码）或直接输入智联编码。未收录的城市使用用户从网站复制的搜索结果 URL，保留完整条件。
- 搜索卡片：`.joblist-box__item`，职位链接 `.jobinfo__name`；公司 `.companyinfo__name`；薪资 `.jobinfo__salary`；地区/经验/学历 `.jobinfo__other-info-item`。列表用于发现链接和补充卡片字段。
- 详情入口：从列表实际链接取得 `/jobdetail/<id>.htm`，不拼造职位编号；统一为 HTTPS。示例：<https://www.zhaopin.com/jobdetail/CC383625320J40873999709.htm>。
- 完整 JD：`.describtion-card__detail-content`，注意官网的 describtion 拼写。标题 `.summary-planes__title`，经验/学历 `.summary-planes__info > li`，公司 `.company-info__name`。保留换行，兼容“任职要求”和“岗位基本需求”等标题。
- 分页：读取 `.soupager` 中真实“下一页”链接，如 `/sou/jl538/kw9QJL9GBUPTQ0C/p2`，不猜页码接口；先滚动并观察新增卡片，再翻页。

## 数据完整性

详情优先于摘要；详情页下方推荐岗位不得混入本岗位。没有识别到完整详情或编号不一致时暂停，保留队列供重试。薪资遮罩不当成有效数字，允许使用本次同一岗位卡片的公开薪资并记录来源。公司介绍、工作地址与 JD 分开保存。扩展只传字段，不保存整页 HTML、Cookie 或页面脚本状态。

重复岗位更新采集时间；完整详情发生变化（包括变短）时更新正文并重新索引。已有完整详情不会被列表摘要覆盖。Provider 归一化的学历、经验和薪资在正文刷新后继续保留。

## 复用及任务行为

复用 BOSS 的导航等待工具，以及现有多平台入库、去重、知识库增量索引、快速评分缓存接口。采用相同的后台任务、增量保存、取消终态保护及断点恢复设计；BOSS 页面采集规则不变。

智联任务占用一个搜索标签页和一个反复导航的详情标签页，均默认后台打开。目标为 1–200 个完整岗位，逐岗入库并评分。进度存入扩展本地存储；前端轮询快照，关闭前端不取消采集。扩展重启后标记 INTERRUPTED，用户点击继续；保存成功但尚未评分的岗位会补评分。登录、验证或访问频率限制进入 WAITING_FOR_USER；“查看当前采集页面”激活原标签页供用户处理。

到末页时显示实际数量和结束原因，不承诺每个条件都有 200 个岗位。页面结构改变、详情缺失或保存失败会明确暂停；已保存岗位保留。评分失败不丢弃岗位，显示未评分提示。页面勾选只是候选标记，不执行投递。

## 验证命令

- `node apps/extension/tests/zhaopin.test.cjs`：真实类名、详情身份、公司/推荐污染、换行、遮罩薪资、验证、跨页、取消、重试和恢复。
- `node scripts/verify-zhaopin-pages.cjs`：联网只读核实搜索页及其中一个详情页，输出字段统计，不入库。
- 在 apps/web：`npm test -- components/zhaopin-plugin-workflow.test.tsx components/boss-plugin-workflow.test.tsx`。
- 在 services/api：`python -m pytest tests/test_recruitment_platforms.py tests/test_quick_matching.py tests/test_boss_adapter.py -q -p no:cacheprovider`。

公开 HTML 验证不能代替用户登录态下的长批次浏览器实测。交付后需要在浏览器扩展管理页重新加载 `apps/extension/.output/chrome-mv3`（0.2.9），再刷新系统页。
