# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, '.')
TMP="E:/my_repo/Gis-WorkTable/.tmpenv"
os.environ["TMP"]=TMP; os.environ["TEMP"]=TMP; os.environ["TMPDIR"]=TMP
os.environ["PYTHONIOENCODING"]="utf-8"; os.environ["PYTHONPYCACHEPREFIX"]=TMP+"/pyc"

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langgraph.prebuilt import create_react_agent
from backend.services.tools import tools
from typing import List, Optional
from langchain_core.callbacks import CallbackManagerForLLMRun

SCEN = sys.argv[1] if len(sys.argv)>1 else "clear_layers"
ARGV = sys.argv[2] if len(sys.argv)>2 else "{}"

class FakeLLM(BaseChatModel):
    model_name: str = "fake"
    calls: int = 0
    def bind_tools(self, tools, **kwargs):
        return self
    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls += 1
        if self.calls == 1:
            import json
            try: args=json.loads(ARGV)
            except: args={}
            msg = AIMessage(content="", tool_calls=[{"name": SCEN, "args": args, "id": "call_1", "type": "tool_call"}])
        else:
            msg = AIMessage(content="完成。")
        return ChatResult(generations=[ChatGeneration(message=msg)])
    @property
    def _llm_type(self): return "fake"

llm = FakeLLM()
agent = create_react_agent(llm, tools)
try:
    out = agent.invoke({"messages":[AIMessage(content="hi")]}, {"recursion_limit": 20})
    print("OK; last:", repr(str(out["messages"][-1].content))[:200])
except Exception as e:
    import traceback; traceback.print_exc()
    print("FAILED:", type(e).__name__, ":", str(e)[:300])
