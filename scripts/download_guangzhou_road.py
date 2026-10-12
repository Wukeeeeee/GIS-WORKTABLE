"""
Download Guangzhou road network (OSMnx)
Usage: python scripts/download_guangzhou_road.py
"""
import os, sys, json, time

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import osmnx

# ===== Settings =====
osmnx.settings.timeout = 600
osmnx.settings.max_query_area_size = 2000 * 1000 * 1000  # 2000 km2 -> ~12 sub-queries
osmnx.settings.max_timeout = 600
osmnx.settings.log_console = True
osmnx.settings.rate_limiter = True
osmnx.settings.memory = 2048
osmnx.settings.bidirectional_network_types = ['drive']

print(f"[INFO] Overpass: {osmnx.settings.overpass_endpoint}")
print(f"[INFO] Timeout: {osmnx.settings.timeout}s")
print(f"[INFO] Max query area: {osmnx.settings.max_query_area_size / 1e6:.0f} km2")
print()

# ===== Download (with retry) =====
max_retries = 5
for attempt in range(1, max_retries + 1):
    try:
        print(f"[INFO] Downloading Guangzhou road network (attempt {attempt}/{max_retries})...")
        print("[INFO] This may take 5-15 minutes. Overpass retries automatically on timeout...")
        G = osmnx.graph_from_place("广州市, 广东省, China", network_type="drive", simplify=True)
        print(f"\n[OK] Graph built: {len(G.nodes)} nodes, {len(G.edges)} edges")
        break
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Attempt {attempt} failed: {str(e)[:200]}")
        if attempt < max_retries:
            wait = attempt * 30
            print(f"[INFO] Retry in {wait}s...")
            time.sleep(wait)
        else:
            print("\n[FAILED] All retries exhausted.")
            print("\nTry asking AI chat: 'download Guangzhou road network'")
            sys.exit(1)

# ===== Save =====
out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(out_dir, exist_ok=True)

edges = osmnx.graph_to_gdfs(G, nodes=False)
edges_geojson = json.loads(edges.to_json())
out_path = os.path.join(out_dir, "guangzhou_road_network.geojson")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(edges_geojson, f, ensure_ascii=False, indent=2)
print(f"[OK] Edges saved: {out_path}")

print(f"[OK] File size: {os.path.getsize(out_path) / 1024 / 1024:.1f} MB")
print(f"[OK] Total road length: {edges['length'].sum() / 1000:.1f} km")
print("[OK] Done!")
