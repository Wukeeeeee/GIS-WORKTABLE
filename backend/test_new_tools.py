"""
新工具快速验证脚本
运行：python backend/test_new_tools.py
测试所有新集成的工具：Crawl4AI、Scrapling、B站搜索、Browser-Use
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test(name, fn, *args, **kwargs):
    print(f"\n{'='*50}")
    print(f"🔄 测试: {name}")
    print(f"{'='*50}")
    t0 = time.time()
    try:
        result = fn(*args, **kwargs)
        elapsed = time.time() - t0
        print(f"✅ 成功 ({elapsed:.1f}s)")
        print(f"结果长度: {len(result)} 字符")
        print(f"预览: {result[:200]}")
        return True
    except Exception as e:
        elapsed = time.time() - t0
        print(f"❌ 失败 ({elapsed:.1f}s): {e}")
        return False

if __name__ == "__main__":
    print("🌐 GIS WorkTable 新工具测试")
    print("="*50)

    # 1. 测试 Crawl4AI（省 token 抓取）
    from backend.services.ai_service import fetch_with_crawl4ai
    test("Crawl4AI 抓取 + 清洗", fetch_with_crawl4ai,
         "https://www.baidu.com", 1000)

    # 2. 测试 Playwright 回退（模拟 Crawl4AI 不可用的情况）
    from backend.services.ai_service import _fetch_webpage_fallback
    test("Playwright 回退方案", _fetch_webpage_fallback,
         "https://httpbin.org/get", 1000)

    # 3. 测试 Scrapling 隐身抓取
    from backend.services.ai_service import scrape_page
    test("Scrapling 隐身抓取", scrape_page,
         "https://httpbin.org/headers")

    # 4. 测试 B站搜索
    from backend.services.ai_service import search_platform
    test("B站搜索 GIS", search_platform, "bilibili", "GIS教程")

    # 5. 测试 Browser-Use（需要 API Key）
    from backend.services.ai_service import browser_operate
    from backend.services.ai_service import _current_api_key, _get_default_key
    key = _get_default_key()
    if key:
        import backend.services.ai_service as svc
        svc._current_api_key = key
        test("Browser-Use 浏览器操控", browser_operate,
             "打开 https://httpbin.org/get 返回页面内容",
             "https://httpbin.org/get")
    else:
        print(f"\n{'='*50}")
        print(f"⏭️  跳过: Browser-Use（需要配置 API Key）")
        print(f"{'='*50}")

    # 6. 测试 fetch_webpage 入口（Crawl4AI → Playwright 自动回退）
    from backend.services.ai_service import fetch_webpage
    test("fetch_webpage 综合入口", fetch_webpage,
         "https://www.baidu.com")

    print(f"\n{'='*50}")
    print("✅ 测试完成！")
    print(f"{'='*50}")
