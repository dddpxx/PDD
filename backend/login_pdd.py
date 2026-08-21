"""人工登录一次拼多多移动端网页，把登录态存本地文件，供 run_pipeline.py 复用。

用法：
    python login_pdd.py [保存路径，默认 pdd_login_state.json]

会弹出一个真实浏览器窗口，在里面手动登录（手机号+验证码，跟登App是同一套账号，
网页登录不需要装App），登录完成后回终端按回车，脚本会把登录态存下来。
"""

import sys

from pdd_agent.auth import save_login_state

DEFAULT_STATE_PATH = "pdd_login_state.json"


def main() -> None:
    state_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_STATE_PATH
    save_login_state(state_path)


if __name__ == "__main__":
    main()
