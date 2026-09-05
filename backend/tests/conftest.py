# -*- coding: utf-8 -*-
"""pytest 全局配置：修复 PROJ_LIB / PROJ_DATA 环境冲突（PostGIS 旧 proj.db 覆盖 rasterio）"""
import os

os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)
