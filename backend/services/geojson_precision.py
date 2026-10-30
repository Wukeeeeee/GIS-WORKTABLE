"""Lossless transport helpers for GeoJSON properties consumed by JavaScript."""
from __future__ import annotations

import copy
import math
import re

JS_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_INTEGER_TEXT = re.compile(r"^[+-]?[0-9]+$")


def protect_geojson_property_integers(geojson):
    """Copy GeoJSON and encode unsafe integers in feature properties as decimal text.

    Geometry coordinates stay numeric; valid GeoJSON coordinates are bounded and
    do not need this representation. Nested property objects are handled too.
    """
    result = copy.deepcopy(geojson)
    features = result.get("features", []) if isinstance(result, dict) else []
    if isinstance(result, dict) and result.get("type") == "Feature":
        features = [result]

    def protect(value, path, protected_paths):
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            if abs(value) > JS_MAX_SAFE_INTEGER:
                protected_paths.append(path)
                return str(value)
            return value
        if isinstance(value, list):
            return [protect(item, path + [index], protected_paths) for index, item in enumerate(value)]
        if isinstance(value, dict):
            return {key: protect(item, path + [key], protected_paths) for key, item in value.items()}
        return value

    for feature in features if isinstance(features, list) else []:
        if isinstance(feature, dict) and isinstance(feature.get("properties"), dict):
            protected_paths = []
            feature["properties"] = protect(feature["properties"], [], protected_paths)
            if protected_paths:
                feature["_gisworktable_integer_paths"] = protected_paths
    return result


def restore_registered_integer_properties(existing_geojson, incoming_geojson):
    """Retain/edit unsafe integer fields without accepting JS-rounded numbers.

    The caller must invoke this only after verifying the matching registration
    token. A decimal string is exact UI input; a numeric value that maps to the
    same IEEE-754 value as the existing integer is an unchanged rounded copy.
    """
    if not isinstance(existing_geojson, dict) or not isinstance(incoming_geojson, dict):
        return incoming_geojson

    def feature_list(value):
        if value.get("type") == "FeatureCollection":
            return value.get("features", [])
        if value.get("type") == "Feature":
            return [value]
        return []

    old_features = feature_list(existing_geojson)
    new_features = feature_list(incoming_geojson)
    old_by_fid = {}
    for index, feature in enumerate(old_features):
        props = feature.get("properties") if isinstance(feature, dict) else None
        fid = props.get("_fid") if isinstance(props, dict) else None
        if fid is not None:
            old_by_fid.setdefault(str(fid), feature)
    for index, new_feature in enumerate(new_features):
        if not isinstance(new_feature, dict):
            continue
        new_props = new_feature.get("properties")
        if not isinstance(new_props, dict):
            continue
        fid = new_props.get("_fid")
        old_feature = old_by_fid.get(str(fid)) if fid is not None else None
        if old_feature is None and len(old_features) == len(new_features) and index < len(old_features):
            old_feature = old_features[index]
        old_props = old_feature.get("properties") if isinstance(old_feature, dict) else None
        if isinstance(old_props, dict):
            for key, old_value in old_props.items():
                if isinstance(old_value, bool) or not isinstance(old_value, int) or abs(old_value) <= JS_MAX_SAFE_INTEGER:
                    continue
                new_value = new_props.get(key)
                if isinstance(new_value, str) and _INTEGER_TEXT.fullmatch(new_value):
                    new_props[key] = int(new_value)
                elif isinstance(new_value, int) and not isinstance(new_value, bool):
                    if float(new_value) == float(old_value):
                        new_props[key] = old_value
                elif isinstance(new_value, float) and math.isfinite(new_value):
                    if new_value.is_integer() and new_value == float(old_value):
                        new_props[key] = old_value
        for path in new_feature.get("_gisworktable_integer_paths", []):
            if not isinstance(path, list) or not path:
                continue
            new_container = new_props
            try:
                for step in path:
                    new_container = new_container[step]
                if isinstance(new_container, str) and _INTEGER_TEXT.fullmatch(new_container):
                    replacement = int(new_container)
                    target = new_props
                    for step in path[:-1]:
                        target = target[step]
                    target[path[-1]] = replacement
            except (KeyError, IndexError, TypeError):
                continue
        new_feature.pop("_gisworktable_integer_paths", None)
    return incoming_geojson
