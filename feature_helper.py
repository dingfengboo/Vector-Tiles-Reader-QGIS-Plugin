from qgis.core import QgsMapLayerRegistry, QgsField, QgsVectorLayer
from PyQt4.QtCore import QVariant
import processing
from file_helper import FileHelper


class FeatureMerger:

    def merge_features(self, layer):
        intersection_layer = None
        join_layer = None
        dissolved_layer = None
        layer_name = layer.name()
        print "now merging features of layer: ", layer_name
        intersection_layer = self._create_intersection_layer(layer)
        if intersection_layer:
            join_layer = self._join_by_attribute(intersection_layer)
        else:
            print("Intersection layer not found")

        if join_layer:
            self._create_new_featurenr_attribute(join_layer)
            dissolved_layer = self._dissolve(join_layer)
        else:
            print("Join layer not found")

        # if intersection_layer:
        #     QgsMapLayerRegistry.instance().removeMapLayer(intersection_layer)
        #
        # if join_layer:
        #     QgsMapLayerRegistry.instance().removeMapLayer(join_layer)
        return dissolved_layer

    def _create_intersection_layer(self, layer):
        target_file = FileHelper.get_unique_file_name("shp")
        processing.runalg("qgis:intersection", layer, layer, True, target_file)
        # processing.runandload("qgis:intersection", layer, layer, True, "memory:temp_layer")
        # intersection_layer = self._get_layer("Intersection")
        intersection_layer = QgsVectorLayer(target_file, "Intersection", "ogr")
        return intersection_layer

    def _join_by_attribute(self, layer):
        # print("create join layer")
        target_file = FileHelper.get_unique_file_name("shp")
        processing.runalg("qgis:joinattributesbylocation", layer, layer, u'intersects', 0, 1, "min,max", 1, target_file)
        # processing.runandload("qgis:joinattributesbylocation", layer, layer, u'intersects', 0, 1, "min,max", 1, 'memory:temp_layer')
        # joined_layer = self._get_layer("Joined layer")
        joined_layer = QgsVectorLayer(target_file, "Joined Layer", "ogr")
        return joined_layer

    def _get_layer(self, name):
        result = None
        layers = QgsMapLayerRegistry.instance().mapLayersByName(name)
        if len(layers) > 0:
            result = layers[0]
        return result

    def _create_new_featurenr_attribute(self, layer):
        field = QgsField('newFeatureNr', QVariant.String)
        layer.addExpressionField("concat(\"minfeatureNr\", \"maxfeatureNr\") ", field)

    def _dissolve(self, layer):
        target_file = FileHelper.get_unique_file_name("shp")
        processing.runalg("qgis:dissolve", layer, False, "newFeatureNr", target_file)
        # processing.runandload("qgis:dissolve", layer, False, "newFeatureNr", "memory:temp_layer")
        # dissolved_layer = self._get_layer("Dissolved")
        dissolved_layer = QgsVectorLayer(target_file, "Dissolved", "ogr")
        return dissolved_layer
