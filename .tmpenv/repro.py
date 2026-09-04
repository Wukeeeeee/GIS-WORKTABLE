# -*- coding: utf-8 -*-
import sys, os, traceback, io
sys.path.insert(0, '.')
TMP="E:/my_repo/Gis-WorkTable/.tmpenv"
os.environ["TMP"]=TMP; os.environ["TEMP"]=TMP; os.environ["TMPDIR"]=TMP
os.environ["PYTHONIOENCODING"]="utf-8"
os.environ["PYTHONPYCACHEPREFIX"]=TMP+"/pyc"

from langchain_core.messages import SystemMessage, HumanMessage
from backend.services.graph import run_agent

key = open('apikey.txt', encoding='utf-8').read().strip()
print("key len", len(key), "suffix", key[-4:], flush=True)

user = "广州市2025人口普查的数据 分到每个区域 然后不同的区域在地图上用不同的颜色显示 再给我生成一张报告用图"
sys_prompt = ("你是 GIS 助手。请按要求使用工具完成广州市人口普查数据分析、按区域着色并生成报告图。")
res = run_agent(
    messages=[SystemMessage(content=sys_prompt), HumanMessage(content=user)],
    api_key=key,
    provider="deepseek",
    amap_key="",
    skill_text="",
    original_message=user,
)
print("=== RESPONSE ===", flush=True)
print(str(res.get("response"))[:2000], flush=True)
