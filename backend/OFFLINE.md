# 固定样本离线闭环

- Python：CPython 3.13.12
- 安装：`py -3.13 -m pip install -r backend/requirements.txt`
- 验证：`py -3.13 backend/run_offline_pipeline.py --output output/jing-30`

验证命令只读取仓库内 CC0 合成样本，不需要账号、Cookie、密钥、模型或本地 ComfyUI，也不会访问网络。成功时退出码为 0，并生成供人工复核的 `output/jing-30/preview.html` 与 `output/jing-30/publish_draft.json`；失败时退出码为 1，标准错误包含失败类型和原因。
