import itertools

import pandas as pd
from datetime import (
    datetime,
)

from fireant import (
    DatetimeDimension,
    utils,
)
from .base import (
    TransformableWidget,
    Widget,
)
from .formats import (
    date_as_millis,
    metric_value,
)
from .helpers import (
    dimensional_metric_label,
    extract_display_values,
)
from ..exceptions import MetricRequiredException
from ..references import reference_key

DEFAULT_COLORS = (
    "#DDDF0D",
    "#55BF3B",
    "#DF5353",
    "#7798BF",
    "#AAEEEE",
    "#FF0066",
    "#EEAAEE",
    "#DF5353",
    "#7798BF",
    "#AAEEEE",
)

DASH_STYLES = (
    'Solid',
    'Dash',
    'Dot',
    'DashDot',
    'LongDash',
    'LongDashDot',
    'ShortDash',
    'ShortDashDot',
    'LongDashDotDot',
    'ShortDashDotDot',
    'ShortDot',
)

MARKER_SYMBOLS = (
    "circle",
    "square",
    "diamond",
    "triangle",
    "triangle-down",
)


class ChartWidget(Widget):
    type = None
    needs_marker = False
    stacked = False

    def __init__(self, items=(), name=None, stacked=False):
        super(ChartWidget, self).__init__(items)
        self.name = name
        self.stacked = self.stacked or stacked


class ContinuousAxisChartWidget(ChartWidget):
    pass


class HighCharts(TransformableWidget):
    class LineChart(ContinuousAxisChartWidget):
        type = 'line'
        needs_marker = True

    class AreaChart(ContinuousAxisChartWidget):
        type = 'area'
        needs_marker = True

    class AreaPercentageChart(AreaChart):
        stacked = True

    class PieChart(ChartWidget):
        type = 'pie'

    class BarChart(ChartWidget):
        type = 'bar'

    class StackedBarChart(BarChart):
        stacked = True

    class ColumnChart(ChartWidget):
        type = 'column'

    class StackedColumnChart(ColumnChart):
        stacked = True

    def __init__(self, axes=(), title=None, colors=None):
        super(HighCharts, self).__init__(axes)
        self.title = title
        self.colors = colors or DEFAULT_COLORS

    @utils.immutable
    def axis(self, axis: ChartWidget):
        """
        (Immutable) Adds an axis to the Chart.

        :param axis:
        :return:
        """

        self.items.append(axis)

    @property
    def metrics(self):
        """
        :return:
            A set of metrics used in this chart. This collects all metrics across all axes.
        """
        if 0 == len(self.items):
            raise MetricRequiredException(str(self))

        seen = set()
        return [metric
                for axis in self.items
                for metric in axis.metrics
                if not (metric.key in seen or seen.add(metric.key))]

    @property
    def operations(self):
        return utils.ordered_distinct_list_by_attr([operation
                                                    for item in self.items
                                                    for operation in item.operations])

    def transform(self, data_frame, slicer, dimensions):
        """
        - Main entry point -

        Transforms a data frame into highcharts JSON format.

        See https://api.highcharts.com/highcharts/

        :param data_frame:
            The data frame containing the data. Index must match the dimensions parameter.
        :param slicer:
            The slicer that is in use.
        :param dimensions:
            A list of dimensions that are being rendered.
        :return:
            A dict meant to be dumped as JSON.
        """
        colors = itertools.cycle(self.colors)

        def group_series(keys):
            if isinstance(keys[0], datetime) and pd.isnull(keys[0]):
                return tuple('Totals' for _ in keys[1:])
            return tuple(str(key) if not pd.isnull(key) else 'Totals' for key in keys[1:])

        groups = list(data_frame.groupby(group_series)) \
            if isinstance(data_frame.index, pd.MultiIndex) \
            else [([], data_frame)]

        dimension_display_values = extract_display_values(dimensions, data_frame)
        render_series_label = dimensional_metric_label(dimensions, dimension_display_values)

        references = [reference
                      for dimension in dimensions
                      for reference in getattr(dimension, 'references', ())]

        total_num_items = sum([len(axis.items) for axis in self.items])

        y_axes, series = [], []
        for axis_idx, axis in enumerate(self.items):
            colors, series_colors = itertools.tee(colors)
            axis_color = next(colors) if 1 < total_num_items else None

            # prepend axes, append series, this keeps everything ordered left-to-right
            y_axes[0:0] = self._render_y_axis(axis_idx,
                                              axis_color,
                                              references)
            is_timeseries = dimensions and isinstance(dimensions[0], DatetimeDimension)
            series += self._render_series(axis,
                                          axis_idx,
                                          axis_color,
                                          series_colors,
                                          groups,
                                          render_series_label,
                                          references,
                                          is_timeseries)

        x_axis = self._render_x_axis(data_frame, dimensions, dimension_display_values)

        return {
            "title": {"text": self.title},
            "xAxis": x_axis,
            "yAxis": y_axes,
            "series": series,
            "tooltip": {"shared": True, "useHTML": True},
            "legend": {"useHTML": True},
        }

    @staticmethod
    def _render_x_axis(data_frame, dimensions, dimension_display_values):
        """
        Renders the xAxis configuraiton.

        https://api.highcharts.com/highcharts/yAxis

        :param data_frame:
        :param dimension_display_values:
        :return:
        """
        first_level = data_frame.index.levels[0] \
            if isinstance(data_frame.index, pd.MultiIndex) \
            else data_frame.index

        if dimensions and isinstance(dimensions[0], DatetimeDimension):
            return {"type": "datetime"}

        categories = ["All"] \
            if isinstance(first_level, pd.RangeIndex) \
            else [utils.deep_get(dimension_display_values,
                                 [first_level.name, dimension_value],
                                 dimension_value)
                  for dimension_value in first_level]

        return {
            "type": "category",
            "categories": categories,
        }

    @staticmethod
    def _render_y_axis(axis_idx, color, references):
        """
        Renders the yAxis configuration.

        https://api.highcharts.com/highcharts/yAxis

        :param axis_idx:
        :param color:
        :param references:
        :return:
        """
        y_axes = [{
            "id": str(axis_idx),
            "title": {"text": None},
            "labels": {"style": {"color": color}}
        }]

        y_axes += [{
            "id": "{}_{}".format(axis_idx, reference.key),
            "title": {"text": reference.label},
            "opposite": True,
            "labels": {"style": {"color": color}}
        }
            for reference in references
            if reference.is_delta]

        return y_axes

    def _render_series(self, axis, axis_idx, axis_color, colors, data_frame_groups, render_series_label,
                       references, is_timeseries=False):
        """
        Renders the series configuration.

        https://api.highcharts.com/highcharts/series

        :param axis:
        :param axis_idx:
        :param axis_color:
        :param colors:
        :param data_frame_groups:
        :param render_series_label:
        :param references:
        :param is_timeseries:
        :return:
        """
        has_multi_metric = 1 < len(axis.items)

        series = []
        for metric in axis.items:
            symbols = itertools.cycle(MARKER_SYMBOLS)
            series_color = next(colors) if has_multi_metric else None

            for (dimension_values, group_df), symbol in zip(data_frame_groups, symbols):
                dimension_values = utils.wrap_list(dimension_values)

                if not has_multi_metric:
                    series_color = next(colors)

                for reference, dash_style in zip([None] + references, itertools.cycle(DASH_STYLES)):
                    metric_key = reference_key(metric, reference)

                    series.append({
                        "type": axis.type,
                        "color": series_color,
                        "dashStyle": dash_style,

                        "name": render_series_label(metric, reference, dimension_values),

                        "data": self._render_data(group_df, metric_key, is_timeseries),

                        "tooltip": self._render_tooltip(metric),

                        "yAxis": ("{}_{}".format(axis_idx, reference.key)
                                  if reference is not None and reference.is_delta
                                  else str(axis_idx)),

                        "marker": ({"symbol": symbol, "fillColor": axis_color or series_color}
                                   if axis.needs_marker
                                   else {}),

                        "stacking": ("normal"
                                     if axis.stacked
                                     else None),
                    })

        return series

    def _render_data(self, group_df, metric_key, is_timeseries):
        if not is_timeseries:
            return [metric_value(y) for y in group_df[metric_key].values]

        series = []
        for dimension_values, y in group_df[metric_key].iteritems():
            first_dimension_value = utils.wrap_list(dimension_values)[0]

            if pd.isnull(first_dimension_value):
                # Ignore totals on the x-axis.
                continue

            series.append((date_as_millis(first_dimension_value), metric_value(y)))

        return series

    def _render_tooltip(self, metric):
        return {
            "valuePrefix": metric.prefix,
            "valueSuffix": metric.suffix,
            "valueDecimals": metric.precision,
        }
