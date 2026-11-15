"""File export implementations used by the tools compatibility facade."""

import json
import os
import uuid

from backend.services.tool_modules.runtime import geojson_to_export_gdf


def _remove_unverified_output(path: str, errors: list, artifact_label: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as error:
        errors.append(f"{artifact_label}清理失败:{error}")


def _cleanup_failure_suffix(path: str | None, artifact_label: str) -> str:
    if not path:
        return ""
    errors = []
    _remove_unverified_output(path, errors, artifact_label)
    return f"；{'; '.join(errors)}" if errors else ""




def export_map_impl(format: str = "png", *, pending_layer_ops) -> str:
    """Queue a frontend map-image export operation."""
    format = str(format or "png").strip().lower().lstrip(".")
    if format == "jpeg":
        format = "jpg"
    if format not in {"png", "jpg"}:
        return f"不支持的图片格式：{format}，仅支持 png/jpg"
    try:
        pending_layer_ops.append({"action": "export_map", "format": format})
        return f"已触发地图导出（{format}）"
    except Exception as error:
        return f"导出失败: {str(error)[:200]}"


def export_pdf_impl(
    title: str = "地图导出", rotation_degrees: float = 0, *, pending_layer_ops,
) -> str:
    """Queue a frontend print-layout PDF export operation."""
    try:
        pending_layer_ops.append({
            "action": "export_pdf",
            "title": title,
            "rotation_degrees": rotation_degrees,
        })
        return f"已触发 PDF 出图，标题：{title}，旋转：{rotation_degrees}°"
    except Exception as error:
        return f"PDF 出图失败: {str(error)[:200]}"


def export_layer_impl(
    layer_name: str, format: str = "geojson", *, registered_layers,
    safe_layer_export_stem, output_dir_getter, record_tool_artifact,
    geojson_to_export_gdf,
) -> str:
    """导出指定矢量图层并提供下载链接。format 可选 geojson、shp、gpkg、csv、csv_xy；csv 只导出属性，csv_xy 导出属性及经纬度且仅支持 Point 要素。栅格图层当前不支持此导出工具。"""
    info = registered_layers.get(layer_name)
    if not info:
        matches = [n for n in registered_layers.keys() if layer_name in n]
        if len(matches) == 1:
            info = registered_layers[matches[0]]
            layer_name = matches[0]
        elif len(matches) > 1:
            return f"找到多个匹配：{', '.join(matches)}，请指定完整名称"
        else:
            return f"未找到图层「{layer_name}」，当前图层：{', '.join(registered_layers.keys()) or '无'}"

    if isinstance(info.get("raster"), dict):
        return f"图层「{layer_name}」是栅格图层；当前 export_layer 仅支持矢量导出格式"
    geojson = info.get("geojson")
    if not isinstance(geojson, dict) or not isinstance(geojson.get("features"), list):
        return f"图层「{layer_name}」的矢量数据无效，无法导出"
    safe_name = safe_layer_export_stem(layer_name)

    if format == "geojson":
        path = None
        try:
            # 直接保存 GeoJSON
            import datetime
            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            fname = f"{safe_name}_{ts}_{uuid.uuid4().hex}.geojson"
            _output_dir = output_dir_getter()
            path = os.path.join(_output_dir, fname)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(geojson, f, ensure_ascii=False, indent=2)
            # === 导出真实性验证 ===
            _verr = []
            _src_count = len(geojson.get("features", []))
            if not os.path.exists(path):
                _verr.append("文件未生成")
            elif os.path.getsize(path) < 20:
                _verr.append("文件过小")
            else:
                try:
                    with open(path, "r", encoding="utf-8") as _f:
                        _gj = json.load(_f)
                    if _gj.get("type") != "FeatureCollection":
                        _verr.append("非FeatureCollection")
                    _feat_count = len(_gj.get("features", []))
                    if _feat_count != _src_count:
                        _verr.append(f"Feature数不符({_feat_count}!={_src_count})")
                    if _feat_count > 0 and not all(ft.get("geometry") for ft in _gj["features"]):
                        _verr.append("存在无geometry的Feature")
                except Exception as _ve:
                    _verr.append(f"无法重新读取:{_ve}")
            if _verr:
                _remove_unverified_output(path, _verr, "GeoJSON")
                return "GeoJSON导出验证失败: " + "; ".join(_verr)
            record_tool_artifact(fname, path, artifact_type="geojson")
            return f"GeoJSON已生成：/output/{fname}（{_src_count}个Feature）\n如需要 Shapefile 格式，可再次调用 export_layer 并设 format='shp'"
        except Exception as e:
            return f"GeoJSON导出失败: {str(e)[:200]}{_cleanup_failure_suffix(path, 'GeoJSON')}"

    elif format == "shp":
        # 用 geopandas 转 Shapefile 并打包 zip
        zip_path = None
        try:
            import geopandas as gpd
            import tempfile, zipfile, shutil
            import datetime

            gdf = geojson_to_export_gdf(geojson, serialize_nested=True)
            if gdf.empty:
                return "图层为空，无法导出"

            # 字段名截断
            rename_map = {}
            used_names = {
                str(col).casefold() for col in gdf.columns
                if col != "geometry" and len(str(col)) <= 10
            }
            for col in gdf.columns:
                if col != "geometry" and len(col) > 10:
                    new_name = col[:10]
                    suffix = 1
                    while new_name.casefold() in used_names or new_name.casefold() == "geometry":
                        suffix_text = str(suffix)
                        new_name = col[:10 - len(suffix_text)] + suffix_text
                        suffix += 1
                    rename_map[col] = new_name
                    used_names.add(new_name.casefold())
            if rename_map:
                gdf = gdf.rename(columns=rename_map)

            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            fname = f"{safe_name}_{ts}_{uuid.uuid4().hex}.zip"

            tmp_dir = tempfile.mkdtemp(prefix="shp_export_")
            try:
                shp_base = os.path.join(tmp_dir, safe_name)
                gdf.to_file(shp_base + ".shp", driver="ESRI Shapefile", encoding="utf-8")

                _output_dir = output_dir_getter()
                zip_path = os.path.join(_output_dir, fname)
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fn in os.listdir(tmp_dir):
                        fp = os.path.join(tmp_dir, fn)
                        if os.path.isfile(fp):
                            zf.write(fp, fn)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            # === 导出真实性验证 ===
            _verr = []
            if not os.path.exists(zip_path):
                _verr.append("ZIP文件未生成")
            elif os.path.getsize(zip_path) < 100:
                _verr.append("ZIP文件过小")
            else:
                try:
                    with zipfile.ZipFile(zip_path, "r") as _zf:
                        _ns = _zf.namelist()
                        if not _ns:
                            _verr.append("ZIP内无文件")
                        for _e in [".shp", ".shx", ".dbf"]:
                            if not any(n.endswith(_e) for n in _ns):
                                _verr.append("ZIP缺少" + _e)
                        if gdf.crs and not any(n.endswith(".prj") for n in _ns):
                            _verr.append("ZIP缺少.prj")
                except Exception as _ve:
                    _verr.append("ZIP无法打开")
            if _verr:
                try:
                    os.remove(zip_path)
                except FileNotFoundError:
                    pass
                except OSError as cleanup_error:
                    _verr.append(f"ZIP清理失败:{cleanup_error}")
                return "SHP导出验证失败: " + "; ".join(_verr)
            record_tool_artifact(fname, zip_path, artifact_type="file")
            return f"Shapefile已生成：/output/{fname}（含.shp/.shx/.dbf/.prj/.cpg，{len(gdf)}个要素）"
        except Exception as e:
            if zip_path and os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except OSError as cleanup_error:
                    return (
                        f"SHP 导出失败: {str(e)[:150]}；"
                        f"不完整ZIP清理失败: {str(cleanup_error)[:100]}"
                    )
            return f"SHP 导出失败: {str(e)[:200]}"

    elif format == "gpkg":
        path = None
        try:
            import geopandas as gpd
            import datetime

            gdf = geojson_to_export_gdf(geojson, serialize_nested=True)
            if gdf.empty:
                return "图层为空，无法导出"

            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            fname = f"{safe_name}_{ts}_{uuid.uuid4().hex}.gpkg"

            _output_dir = output_dir_getter()
            path = os.path.join(_output_dir, fname)
            gdf.to_file(path, layer=safe_name, driver="GPKG", encoding="utf-8")

            # === 导出真实性验证 ===
            _verr = []
            if not os.path.exists(path):
                _verr.append("文件未生成")
            elif os.path.getsize(path) < 100:
                _verr.append("文件过小")
            else:
                try:
                    _gdf2 = gpd.read_file(path, layer=safe_name)
                    if len(_gdf2) != len(gdf):
                        _verr.append(f"Feature数不符({len(_gdf2)}!={len(gdf)})")
                    if _gdf2.crs != gdf.crs:
                        _verr.append(f"CRS不符({_gdf2.crs}!={gdf.crs})")
                    if not _gdf2.geom_type.equals(gdf.geom_type):
                        _verr.append("geometry类型不一致")
                except Exception as _ve:
                    _verr.append(f"无法重新读取:{_ve}")
            if _verr:
                _remove_unverified_output(path, _verr, "GPKG")
                return "GPKG导出验证失败: " + "; ".join(_verr)
            record_tool_artifact(fname, path, artifact_type="file")
            return f"GeoPackage已生成：/output/{fname}（{len(gdf)}个Feature，CRS={gdf.crs}）"
        except Exception as e:
            return f"GPKG 导出失败: {str(e)[:200]}{_cleanup_failure_suffix(path, 'GPKG')}"

    elif format == "csv":
        path = None
        try:
            import geopandas as gpd
            import pandas as pd
            import datetime
            from backend.services.csv_utils import write_formula_safe_csv

            gdf = geojson_to_export_gdf(geojson, serialize_nested=True)
            if gdf.empty:
                return "图层为空，无法导出"

            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            fname = f"{safe_name}_{ts}_{uuid.uuid4().hex}.csv"

            _output_dir = output_dir_getter()
            path = os.path.join(_output_dir, fname)
            attr_df = gdf.drop(columns=["geometry"], errors="ignore")
            write_formula_safe_csv(attr_df, path)

            # === 导出真实性验证 ===
            _verr = []
            if not os.path.exists(path):
                _verr.append("文件未生成")
            elif os.path.getsize(path) < 10:
                _verr.append("文件过小")
            else:
                try:
                    _df2 = pd.read_csv(path, encoding="utf-8-sig")
                    if len(_df2) != len(attr_df):
                        _verr.append(f"行数不符({len(_df2)}!={len(attr_df)})")
                    if len(_df2.columns) != len(attr_df.columns):
                        _verr.append(f"列数不符({len(_df2.columns)}!={len(attr_df.columns)})")
                except Exception as _ve:
                    _verr.append(f"无法重新读取:{_ve}")
            if _verr:
                _remove_unverified_output(path, _verr, "CSV")
                return "CSV导出验证失败: " + "; ".join(_verr)
            record_tool_artifact(fname, path, artifact_type="file")
            return (f"CSV属性表已生成：/output/{fname}"
                    f"（{len(attr_df.columns)}列, {len(attr_df)}行）"
                    f"\n如需含坐标的CSV，可用 format='csv_xy'")
        except Exception as e:
            return f"CSV 导出失败: {str(e)[:200]}{_cleanup_failure_suffix(path, 'CSV')}"

    elif format == "csv_xy":
        path = None
        try:
            import geopandas as gpd
            import pandas as pd
            import datetime
            from backend.services.csv_utils import write_formula_safe_csv

            gdf = geojson_to_export_gdf(geojson, serialize_nested=True)
            if gdf.empty:
                return "图层为空，无法导出"
            if not gdf.geometry.geom_type.eq("Point").all():
                return "CSV坐标导出仅支持 Point 点要素；线或面请使用 GeoJSON、Shapefile 或 GeoPackage 格式"

            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            fname = f"{safe_name}_{ts}_{uuid.uuid4().hex}.csv"

            _output_dir = output_dir_getter()
            path = os.path.join(_output_dir, fname)

            longitude_field = "longitude"
            latitude_field = "latitude"
            for field_name, base_name in ((longitude_field, "longitude"), (latitude_field, "latitude")):
                if field_name in gdf.columns:
                    candidate = "geometry_" + base_name
                    suffix = 2
                    while candidate in gdf.columns:
                        candidate = f"geometry_{base_name}_{suffix}"
                        suffix += 1
                    if base_name == "longitude":
                        longitude_field = candidate
                    else:
                        latitude_field = candidate
            gdf[longitude_field] = gdf.geometry.x
            gdf[latitude_field] = gdf.geometry.y
            attr_df = gdf.drop(columns=["geometry"], errors="ignore")
            write_formula_safe_csv(attr_df, path)

            # === 导出真实性验证 ===
            _verr = []
            if not os.path.exists(path):
                _verr.append("文件未生成")
            elif os.path.getsize(path) < 10:
                _verr.append("文件过小")
            else:
                try:
                    _df2 = pd.read_csv(path, encoding="utf-8-sig")
                    if len(_df2) != len(attr_df):
                        _verr.append(f"行数不符({len(_df2)}!={len(attr_df)})")
                    if longitude_field not in _df2.columns:
                        _verr.append(f"缺少{longitude_field}列")
                    if latitude_field not in _df2.columns:
                        _verr.append(f"缺少{latitude_field}列")
                except Exception as _ve:
                    _verr.append(f"无法重新读取:{_ve}")
            if _verr:
                _remove_unverified_output(path, _verr, "CSV")
                return "CSV导出验证失败: " + "; ".join(_verr)
            record_tool_artifact(fname, path, artifact_type="file")
            return (f"CSV（含坐标）已生成：/output/{fname}"
                    f"（{len(attr_df.columns)}列, {len(attr_df)}行，含{longitude_field}/{latitude_field}坐标列）")
        except Exception as e:
            return f"CSV 导出失败: {str(e)[:200]}{_cleanup_failure_suffix(path, 'CSV')}"

    return f"不支持的格式: {format}，可选 geojson / shp / gpkg / csv / csv_xy"
