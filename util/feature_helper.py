from builtins import str
from builtins import object

from .vtr_2to3 import *

import uuid
import numbers
from .log_helper import info, debug
from .tile_helper import tile_to_latlon


def clip_features(layer, scheme, bounds=None, should_cancel_func=None):
    layer.startEditing()

    try:
        if bounds:
            zoom_level = bounds["zoom"]
            min_extent = tile_to_latlon(zoom=zoom_level, x=bounds["x_min"], y=bounds["y_min"], scheme=scheme)
            max_extent = tile_to_latlon(zoom=zoom_level, x=bounds["x_max"], y=bounds["y_max"], scheme=scheme)
            rect = QgsGeometry.fromRect(QgsRectangle(min_extent[0], max_extent[1], max_extent[2], min_extent[3]))
            info("clip at: {}", (min_extent[0], max_extent[1], max_extent[2], min_extent[3]))

        for f in layer.getFeatures():
            if should_cancel_func and should_cancel_func():
                break

            geom = f.geometry()
            if geom:
                errors = geom.validateGeometry()
                if errors and len(errors) > 0:
                    continue

                if not bounds:
                    col = f.attribute("_col")
                    row = f.attribute("_row")
                    zoom_level = f.attribute("_zoom")
                    extent = tile_to_latlon(zoom=zoom_level, x=col, y=row, scheme=scheme)
                    rect = QgsGeometry.fromRect(QgsRectangle(extent[0], extent[1], extent[2], extent[3]))
                assert rect

                new_geom = geom.intersection(rect)
                f.setGeometry(new_geom)
                layer.updateFeature(f)
    finally:
        layer.commitChanges()


class FeatureMerger(object):
    """
     * The class FeatureMerger can be used to merge features over tile boundaries.
    """

    _DISSOLVE_GROUP_FIELD = "dissolveGroup"

    def __init__(self, should_cancel_func):
        self._should_cancel_func = should_cancel_func

    def merge_features(self, layer):
        layer_name = layer.name()
        info("Merging features of layer: {}".format(layer_name))
        layer.startEditing()
        self._merge_layer(layer)
        layer.commitChanges()

    def _merge_layer(self, layer):
        existing_attributes = layer.dataProvider().fieldNameMap()
        if self._DISSOLVE_GROUP_FIELD not in existing_attributes:
            layer.dataProvider().addAttributes([QgsField(self._DISSOLVE_GROUP_FIELD, QVariant.String, len=36)])
            layer.updateFields()
        # Create a dictionary of all features
        feature_dict = {f.id(): f for f in layer.getFeatures()}

        # Build a spatial index
        index = QgsSpatialIndex()
        for f in list(feature_dict.values()):
            index.insertFeature(f)
            if self._should_cancel_func():
                break

        for f in list(feature_dict.values()):
            if self._should_cancel_func():
                break
            if f[self._DISSOLVE_GROUP_FIELD]:
                continue
            f[self._DISSOLVE_GROUP_FIELD] = "{}".format(uuid.uuid4())
            self._merge_feature(layer=layer,
                                index=index,
                                f=f,
                                feature_dict=feature_dict,
                                feature_handler=lambda feat: layer.updateFeature(feat))
            layer.updateFeature(f)

    def _merge_feature(self, layer, index, f, feature_dict, feature_handler):
        BUFFER_SIZE = 10
        geom = f.geometry().buffer(0, 0)
        if not geom or self._should_cancel_func():
            return

        index.deleteFeature(f)
        intersecting_ids = index.intersects(geom.buffer(BUFFER_SIZE, 0).boundingBox())

        new_neighbours = []
        while len(intersecting_ids) > 0 and not self._should_cancel_func():
            intersecting_id = intersecting_ids.pop(0)
            intersecting_f = feature_dict[intersecting_id]
            index.deleteFeature(intersecting_f)
            if not intersecting_f[self._DISSOLVE_GROUP_FIELD] and not intersecting_f.geometry().disjoint(geom):
                intersecting_f[self._DISSOLVE_GROUP_FIELD] = "{}".format(f[self._DISSOLVE_GROUP_FIELD])
                intersecting_geometry = intersecting_f.geometry().buffer(0, 0)
                errors = []
                errors.extend(geom.validateGeometry())
                errors.extend(intersecting_geometry.validateGeometry())
                for i, e in enumerate(errors):
                    info("err {}: {}", i, e.what())
                if len(errors) > 0:
                    continue

                geom = geom.combine(intersecting_geometry)
                if not geom:
                    continue
                layer.deleteFeature(intersecting_id)
                index.deleteFeature(intersecting_f)
                f.setGeometry(geom)
                new_neighbours.append(intersecting_f)
                feature_handler(f)
                if geom:
                    intersecting_ids = index.intersects(geom.boundingBox())

        for n in new_neighbours:
            if self._should_cancel_func():
                break
            self._merge_feature(layer=layer,
                                index=index,
                                f=n,
                                feature_dict=feature_dict,
                                feature_handler=feature_handler)

class _GeoTypes(object):
    def __init__(self):
        pass

    POINT = "Point"
    LINE_STRING = "LineString"
    POLYGON = "Polygon"

GeoTypes = _GeoTypes()

geo_types_by_name = {
    "Point": GeoTypes.POINT,
    "MultiPoint": GeoTypes.POINT,
    "Polygon": GeoTypes.POLYGON,
    "MultiPolygon": GeoTypes.POLYGON,
    "LineString": GeoTypes.LINE_STRING,
    "MultiLineString": GeoTypes.LINE_STRING,
}

geo_types = {
    1: GeoTypes.POINT,
    2: GeoTypes.LINE_STRING,
    3: GeoTypes.POLYGON}


def is_multi(geo_type, coordinates):
    """
    * Returns true, if the specified coordinates belong to a Multi geometry (e.g. MultiPolygon or MultiLineString)
    :param geo_type:
    :param coordinates:
    :return:
    """

    if geo_type == GeoTypes.POINT:
        is_single = len(coordinates) == 2 and all(isinstance(c, int) for c in coordinates)
        return not is_single
    elif geo_type == GeoTypes.LINE_STRING:
        is_array_of_tuples = all(len(c) == 2 and all(isinstance(ci, int) for ci in c) for c in coordinates)
        is_single = is_array_of_tuples
        return not is_single
    else:
        assert geo_type == GeoTypes.POLYGON
        return get_array_depth(coordinates, 0) >= 2


def get_array_depth(arr, depth):
    """
    * Returns the depth of an array.
      >> Example: arr=[1,2,3], depth=0, then the resulting depth will be 0
      >> Example: arr=[[1,2], [3,4]], depth=0, then the resulting depth will be 1
    :param arr:
    :param depth:
    :return:
    """

    if all(isinstance(c, numbers.Real) for c in arr[0]):
        return depth
    else:
        depth += 1
        return get_array_depth(arr[0], depth)


def map_coordinates_recursive(coordinates, tile_extent, mapper_func, all_out_of_bounds_func=None):
    """
    Recursively traverses the array of coordinates (depth first) and applies the specified function
    """
    any_tuples_inside_bounds = False
    tuple_count_on_current_array_depth = 0
    tmp = []
    is_coordinate_tuple = len(coordinates) == 2 and all(isinstance(c, int) for c in coordinates)
    if is_coordinate_tuple:
        newval = mapper_func(coordinates)
        tmp.append(newval)
    else:
        for coord in coordinates:
            is_coordinate_tuple = len(coord) == 2 and all(isinstance(c, int) for c in coord)
            if is_coordinate_tuple:
                tuple_count_on_current_array_depth += 1
                if not any_tuples_inside_bounds and 1 <= coord[0] <= tile_extent and 1 <= coord[1] <= tile_extent:
                    any_tuples_inside_bounds = True

                newval = mapper_func(coord)
                tmp.append(newval)
            else:
                tmp.append(map_coordinates_recursive(coordinates=coord,
                                                     tile_extent=tile_extent,
                                                     mapper_func=mapper_func,
                                                     all_out_of_bounds_func=all_out_of_bounds_func))

    all_out_of_bounds = tuple_count_on_current_array_depth > 0 and not any_tuples_inside_bounds
    if all_out_of_bounds_func:
        all_out_of_bounds_func(all_out_of_bounds)
    return tmp
