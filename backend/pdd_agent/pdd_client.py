"""拼多多开放平台 API 客户端（Module 07 发布模块的底层通信层）。

2026-08-13：写这个文件的时候用户还没申请开放平台的AppKey/AppSecret，只能先把能确认的部分做实，
不确定的部分明确标注TODO，不能像 importer.py 最早那版一样瞎猜字段——那次猜错了字段路径，
花了好几轮才用真实数据修对，这次不重蹈覆辙。

已经通过多方搜索交叉确认、比较有把握的部分：
- 统一网关：POST https://api.pinduoduo.com/router/router，走"公共参数+业务参数"混在一起提交的
  TOP-API标准风格（跟淘宝开放平台是同一套设计思路），不是每个业务方法单独一个URL路径。
  具体某个方法调哪个type、返回什么结构，还是要以官方文档为准，这里只保证"怎么把请求签好名发出去"这一层。
- 公共参数：type（方法名，如pdd.goods.add）、client_id、access_token（除少数免鉴权接口外都需要）、
  timestamp（10位秒级时间戳）、data_type（通常json）、version（通常v1）、sign。
- 签名算法（MD5）：把所有参数（公共+业务）按参数名的ASCII升序排序，紧密拼接成"key1value1key2value2..."
  （不含=和&），首尾拼上client_secret，整体做MD5，转大写，得到sign。

**没有把握、需要用户拿到真实开放平台账号后我们一起核对的部分**：
- access_token 具体怎么获取（拼多多的商家授权走的是OAuth式跳转，需要商家在开放平台后台完成一次授权，
  拿到 code 换 access_token，这个换取流程的具体接口名和参数，等有账号了对着官方文档核实）。
- 商品发布 pdd.goods.add 的具体业务字段（标题/类目ID/SKU结构/图片字段名等），这部分不同信息源
  说法不完全一致，不能瞎猜，见 store_publisher.py 里的 TODO。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

import requests

_GATEWAY_URL = "https://api.pinduoduo.com/router/router"


@dataclass
class PddCredentials:
    client_id: str
    client_secret: str
    access_token: str = ""  # 商家授权后拿到的token，未授权时可以先留空，只调不需要授权的接口


def _sign(params: dict[str, str], client_secret: str) -> str:
    sorted_items = sorted(params.items())
    concatenated = "".join(f"{k}{v}" for k, v in sorted_items)
    raw = f"{client_secret}{concatenated}{client_secret}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


def call(method: str, biz_params: dict[str, str], creds: PddCredentials) -> dict:
    """调用拼多多开放平台API的通用入口。method 是接口名，比如 "pdd.goods.add"。
    biz_params 是这个接口自己的业务参数（不用带公共参数，这里统一加）。"""
    params: dict[str, str] = {
        "type": method,
        "client_id": creds.client_id,
        "timestamp": str(int(time.time())),
        "data_type": "JSON",
        "version": "V1",
        **biz_params,
    }
    if creds.access_token:
        params["access_token"] = creds.access_token
    params["sign"] = _sign(params, creds.client_secret)

    resp = requests.post(_GATEWAY_URL, data=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "error_response" in data:
        err = data["error_response"]
        raise RuntimeError(f"拼多多开放平台调用失败 [{method}]: {err}")
    return data
