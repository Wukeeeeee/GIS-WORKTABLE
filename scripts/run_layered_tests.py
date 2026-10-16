# -*- coding: utf-8 -*-
"""分层测试运行脚本 (Layered Test Runner)

支持三种主要运行模式：
1. 快速模式 (--mode fast): 运行 Layer 1 (单元测试) + Layer 2 (Agent 测试)，极速完成 (<3s)；
2. 集成模式 (--mode integration): 运行 Layer 3 (GIS 工具测试) + Layer 4 (地图集成测试)；
3. 全量回归 (--mode regression / --mode all): 运行全部 5 层测试；
4. 指定单层 (--layer 1..5): 运行特定某一层级。

使用示例：
  python scripts/run_layered_tests.py --mode fast
  python scripts/run_layered_tests.py --mode integration
  python scripts/run_layered_tests.py --mode regression
"""
import sys
import os
import argparse
import subprocess
import time

# 确保在项目根目录
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)

LAYERS = {
    "1": ("Layer 1: 单元测试 (Prompt、上下文、参数校验)", "backend/tests/layered/test_layer1_unit.py", "unit"),
    "2": ("Layer 2: Agent 测试 (意图识别、上下文继承、零追问)", "backend/tests/layered/test_layer2_agent.py", "agent"),
    "3": ("Layer 3: GIS 工具集成测试 (空间计算、真实制图)", "backend/tests/layered/test_layer3_gis_tools.py", "gis_tools"),
    "4": ("Layer 4: 地图集成测试 (图层注册、元数据、API兼容)", "backend/tests/layered/test_layer4_map_integration.py", "map_integration"),
    "5": ("Layer 5: 端到端业务测试 (用户输入 → Agent → 工具 → 地图)", "backend/tests/layered/test_layer5_e2e.py", "e2e"),
}


def run_cmd(cmd_list):
    print(f"\n[执行命令] {' '.join(cmd_list)}")
    start = time.time()
    env = os.environ.copy()
    env.pop("PROJ_LIB", None)
    env.pop("PROJ_DATA", None)
    res = subprocess.run(cmd_list, env=env)
    dur = time.time() - start
    return res.returncode == 0, dur


def main():
    parser = argparse.ArgumentParser(description="GIS WorkTable 分层测试运行工具")
    parser.add_argument("--mode", choices=["fast", "integration", "e2e", "regression", "all"], default="fast",
                        help="测试运行模式: fast (快速), integration (集成), e2e (端到端), regression (全量回归)")
    parser.add_argument("--layer", choices=["1", "2", "3", "4", "5"], default=None,
                        help="运行指定单层测试")
    args = parser.parse_args()

    print("=" * 70)
    print("GIS-WorkTable 分层测试体系 (Layered Testing Suite)")
    print("原则：不割裂 AI Core 与 GIS 主系统，真实链路验证")
    print("=" * 70)

    selected_layers = []
    if args.layer:
        selected_layers = [args.layer]
    elif args.mode == "fast":
        selected_layers = ["1", "2"]
    elif args.mode == "integration":
        selected_layers = ["3", "4"]
    elif args.mode == "e2e":
        selected_layers = ["5"]
    elif args.mode in ["regression", "all"]:
        selected_layers = ["1", "2", "3", "4", "5"]

    results = []
    total_passed = True
    start_total = time.time()

    for l_key in selected_layers:
        title, test_path, marker = LAYERS[l_key]
        print(f"\n>>> 正在运行 [{title}] ...")
        cmd = [sys.executable, "-m", "pytest", test_path, "-v"]
        passed, dur = run_cmd(cmd)
        results.append((title, passed, dur))
        if not passed:
            total_passed = False

    total_dur = time.time() - start_total

    print("\n" + "=" * 70)
    print("分层测试执行汇总报告")
    print("=" * 70)
    for title, passed, dur in results:
        status_str = "[PASS] 通过" if passed else "[FAIL] 失败"
        print(f"[{status_str}] {title:<48} ({dur:.2f}s)")

    print("-" * 70)
    total_status = "全部通过 (PASSED)" if total_passed else "存在失败项 (FAILED)"
    print(f"总计结果: {total_status} | 总耗时: {total_dur:.2f}s")
    print("=" * 70)

    sys.exit(0 if total_passed else 1)


if __name__ == "__main__":
    main()
