# 本地保存与 GitHub 同步

主目录：`E:\APP\VSCODE-Project\PDD-project`。目标：`https://github.com/dddpxx/PDD.git` 的 `main`。
Codex 自动化 `pdd`（PDD项目每日同步与优化记录）每天北京时间 04:00 在本任务运行。需本机及 Codex 的本地执行环境可用；不能视为 GitHub 托管的离线电脑备份服务。

## 同步范围

代码、设计文档、提示词、参考图片、工作流、测试、优化记录和可安全同步的业务输出。`backend/output` 原有忽略规则保留；其中经过核对的项目成果复制到 `docs/optimization-archive/output-snapshot-2026-09-13/`，保持相对路径并记录 SHA-256。后续比较哈希后仅归档实际新增或变化，避免每天重复大文件。

登录态、`.env`、Cookie、私人订单/收件信息不上传；虚拟环境、缓存、测试临时目录和大型模型权重不上传。调试状态 `debug_state_*.json` 和 `backend/output/generation-check-20260909/xhs/` 保留原处，前者属于浏览器状态，后者属于其他项目。本机 ComfyUI 外部安装/模型不在本项目备份范围。

归档图片与 HTML 是历史产物，不代表母模、商品准确性或上架已验收。HTML/JSON 可能保留旧机器绝对路径和外部商品链接，归档不改写原件。工作区已有的旧人物图片删除作为现有版本变化记录，旧图仍可从 Git 历史取回；同步不额外删除源文件。

## 每次执行

1. 检查目录、分支、origin、未提交内容与并发修改；fetch。只能执行不会覆盖本地内容的快进同步，冲突/分叉停下报告。
2. 检查相关任务新成果并比较后归入主目录，更新归档清单与 `OPTIMIZATION_LOG.md`。
3. 扫描待提交文件中的凭据和隐私信息；执行适当的离线测试，失败如实记录。
4. 正常提交并推送 `origin main`。已有待推送提交也必须重试。禁止强推或重置本地修改。
5. 比较远端 `refs/heads/main` SHA 与本地 HEAD；相同才报告成功。成功 SHA 留在任务运行记录，避免循环写日志产生新提交。无变化不空提交，不通知。

2026-09-13 GitHub 直连失败，经系统现有代理 `http://127.0.0.1:7897` 可连接；仅作为单次 Git 命令参数，失效时重新检查系统代理。所有权检查使用命令级 `safe.directory=E:/APP/VSCODE-Project/PDD-project`，不修改全局设置。

原 `backend/.venv/pyvenv.cfg` 指向旧用户名和 D 盘路径。此次离线验证使用 Codex 可用 Python，追加旧环境的兼容纯 Python 包及隔离 pytest；未修改业务环境。不要假定恢复的旧虚拟环境可直接运行。
