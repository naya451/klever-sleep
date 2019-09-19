#
# Copyright (c) 2018 ISP RAS (http://www.ispras.ru)
# Ivannikov Institute for System Programming of the Russian Academy of Sciences
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from urllib.parse import quote

from django.db.models import Count, Case, When, F
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _

from bridge.vars import ASSOCIATION_TYPE, SafeVerdicts, UnsafeVerdicts, JOB_WEIGHT

from reports.models import ReportSafe, ReportUnsafe, ReportUnknown, ReportRoot, ReportComponent, Report
from marks.models import MarkUnknownReport, SafeTag, UnsafeTag

from users.utils import HumanizedValue
from jobs.utils import TITLES
from caches.models import ReportSafeCache, ReportUnsafeCache


def get_leaves_totals(**qs_kwargs):
    data = {}
    data.update(ReportSafe.objects.filter(**qs_kwargs).aggregate(
        safes=Count('id'),
        safes_confirmed=Count(Case(When(cache__marks_confirmed__gt=0, then=1))),
    ))
    data.update(ReportUnsafe.objects.filter(**qs_kwargs).aggregate(
        unsafes=Count('id'),
        unsafes_confirmed=Count(Case(When(cache__marks_confirmed__gt=0, then=1))),
    ))
    data.update(ReportUnknown.objects.filter(**qs_kwargs).aggregate(
        unknowns=Count('id'),
        unknowns_confirmed=Count(Case(When(cache__marks_confirmed__gt=0, then=1))),
    ))
    return data


class VerdictsInfo:
    def __init__(self, view, base_url, queryset, verdicts):
        self._base_url = base_url
        self._verdicts = verdicts
        self._queryset = queryset
        self._with_confirmed = 'hidden' not in view or 'confirmed_marks' not in view['hidden']

        self.info = self.__get_verdicts_info()

    def __get_verdicts_info(self):
        verdicts_qs = self._queryset.values('cache__verdict').annotate(
            total=Count('id'), confirmed=Count(Case(When(cache__marks_confirmed__gt=0, then=1)))
        ).values_list('cache__verdict', 'confirmed', 'total')

        verdicts_numbers = {}
        for verdict, confirmed, total in verdicts_qs:
            if total == 0 or verdict is None:
                continue
            column = self._verdicts.column(verdict)
            if column not in verdicts_numbers:
                verdicts_numbers[column] = {
                    'title': TITLES.get(column, column),
                    'verdict': verdict,
                    'url': self._base_url,
                    'total': 0
                }
                if self._with_confirmed:
                    verdicts_numbers[column]['confirmed'] = 0
            verdicts_numbers[column]['total'] += total
            if self._with_confirmed:
                verdicts_numbers[column]['confirmed'] += confirmed

        info_data = []
        for column in self._verdicts.columns():
            if column in verdicts_numbers and verdicts_numbers[column]['total']:
                info_data.append(verdicts_numbers[column])
        return info_data


class UnknownsInfo:
    def __init__(self, view, base_url, queryset):
        self._view = view

        # reverse('reports:unknowns', args=[self.report.id])
        self._base_url = base_url

        # ReportUnknown.objects.filter(root=self.root)
        # ReportUnknown.objects.filter(leaves__report=self.report)
        self._queryset = queryset

        self.info = self.__unknowns_info()

    @cached_property
    def _nomark_hidden(self):
        return 'hidden' in self._view and 'unknowns_nomark' in self._view['hidden']

    @cached_property
    def _total_hidden(self):
        return 'hidden' in self._view and 'unknowns_total' in self._view['hidden']

    @cached_property
    def _component_filter(self):
        if 'unknown_component' not in self._view:
            return {}
        return {'component__{}'.format(self._view['unknown_component'][0]): self._view['unknown_component'][1]}

    def __filter_problem(self, problem):
        if 'unknown_problem' not in self._view:
            return True
        if self._view['unknown_problem'][0] == 'iexact':
            return self._view['unknown_problem'][1].lower() == problem.lower()
        if self._view['unknown_problem'][0] == 'istartswith':
            return problem.lower().startswith(self._view['unknown_problem'][1].lower())
        if self._view['unknown_problem'][0] == 'icontains':
            return self._view['unknown_problem'][1].lower() in problem.lower()
        return True

    def __unknowns_info(self):
        unknowns_qs = self._queryset.filter(**self._component_filter)\
            .select_related('cache').only('component', 'cache__marks_total', 'cache__problems')

        # Collect unknowns data
        cache_data = {}
        unmarked = {}
        totals = {}
        skipped_problems = set()
        for unknown in unknowns_qs:
            cache_data.setdefault(unknown.component, {})
            if not self._total_hidden:
                totals.setdefault(unknown.component, 0)
                totals[unknown.component] += 1
            if not self._nomark_hidden and unknown.cache.marks_total == 0:
                unmarked.setdefault(unknown.component, 0)
                unmarked[unknown.component] += 1
            for problem in sorted(unknown.cache.problems):
                if problem in skipped_problems:
                    continue
                if not self.__filter_problem(problem):
                    skipped_problems.add(problem)
                    continue
                cache_data[unknown.component].setdefault(problem, 0)
                cache_data[unknown.component][problem] += 1

        # Sort unknowns data for html
        unknowns_data = []
        for c_name in sorted(cache_data):
            component_data = {'component': c_name, 'problems': []}
            has_data = False
            for problem in sorted(cache_data[c_name]):
                component_data['problems'].append({
                    'problem': problem, 'num': cache_data[c_name][problem],
                    'href': '{0}?component={1}&problem={2}'.format(self._base_url, quote(c_name), quote(problem))
                })
                has_data = True
            if not self._nomark_hidden and c_name in unmarked:
                component_data['problems'].append({
                    'problem': _('Without marks'), 'num': unmarked[c_name],
                    'href': '{0}?component={1}&problem=null'.format(self._base_url, quote(c_name))
                })
                has_data = True
            if not self._total_hidden and c_name in totals:
                component_data['total'] = {
                    'num': totals[c_name], 'href': '{0}?component={1}'.format(self._base_url, quote(c_name))
                }
                has_data = True
            if has_data:
                unknowns_data.append(component_data)
        return unknowns_data


class TagsInfo:
    def __init__(self, base_url, cache_qs, tags_model, tags_filter):
        self._tags_filter = tags_filter
        self._tags_model = tags_model

        # reverse('reports:unsafes', args=[self.report.id])
        # reverse('reports:safes', args=[self.report.id])
        self._base_url = base_url

        # ReportSafeCache.objects.filter(report__root=self.root)
        # ReportSafeCache.objects.filter(report__leaves__report=self.report)
        # ReportUnsafeCache.objects.filter(report__root=self.root)
        # ReportUnsafeCache.objects.filter(report__leaves__report=self.report)
        self._cache_qs = cache_qs

        self.info = self.__get_tags_info()

    @cached_property
    def _db_tags(self):
        """
        All DB tags
        :return: dict
        """
        qs_filter = {}
        if self._tags_filter:
            qs_filter['name__{}'.format(self._tags_filter[0])] = self._tags_filter[1]
        return dict(self._tags_model.objects.filter(**qs_filter).values_list('name', 'description'))

    def __get_tags_info(self):
        tags_data = {}
        for cache_obj in self._cache_qs.only('tags'):
            for tag in cache_obj.tags:
                if tag not in self._db_tags:
                    continue
                if tag not in tags_data:
                    tags_data[tag] = {
                        'name': tag, 'value': 0, 'description': self._db_tags[tag],
                        'url': '{}?tag={}'.format(self._base_url, quote(tag))
                    }
                tags_data[tag]['value'] += 1
        return list(tags_data[tag] for tag in sorted(tags_data))


class ResourcesInfo:
    def __init__(self, user, view, instances, data, total):
        self.user = user
        self.view = view
        self._instances = instances
        self._data = data
        self._total = total
        self.info = self.__get_info()

    def __get_info(self):
        resource_data = []
        for component in sorted(self._instances):
            component_data = {
                'component': component,
                'wall_time': '-',
                'cpu_time': '-',
                'memory': '-',
                'instances': '{}/{}'.format(self._instances[component]['finished'], self._instances[component]['total'])
            }
            if self._instances[component]['finished'] and component in self._data:
                component_data['wall_time'] = HumanizedValue(
                    self._data[component]['wall_time'], user=self.user
                ).timedelta
                component_data['cpu_time'] = HumanizedValue(
                    self._data[component]['cpu_time'], user=self.user
                ).timedelta
                component_data['memory'] = HumanizedValue(
                    self._data[component]['memory'], user=self.user
                ).memory
            resource_data.append(component_data)

        if 'hidden' not in self.view or 'resource_total' not in self.view['hidden']:
            if self._total and (self._total['wall_time'] or self._total['cpu_time'] or self._total['memory']):
                resource_data.append({
                    'component': 'total', 'instances': '-',
                    'wall_time': HumanizedValue(self._total['wall_time'], user=self.user).timedelta,
                    'cpu_time': HumanizedValue(self._total['cpu_time'], user=self.user).timedelta,
                    'memory': HumanizedValue(self._total['memory'], user=self.user).memory
                })
        return resource_data


class AttrStatisticsInfo:
    def __init__(self, view, **qs_kwargs):
        self.attr_name = self.__get_attr_name(view)
        self._qs_kwargs = qs_kwargs
        self.info = self.__get_info()

    def __get_attr_name(self, view):
        if view['attr_stat'] and len(view['attr_stat']) == 1:
            return view['attr_stat'][0]
        return None

    def __get_info(self):
        if not self.attr_name:
            return None
        attr_name_q = quote(self.attr_name)

        data = {}
        for model, column in [(ReportSafe, 'safes'), (ReportUnsafe, 'unsafes'), (ReportUnknown, 'unknowns')]:
            queryset = model.objects.filter(
                cache__attrs__has_key=self.attr_name, **self._qs_kwargs
            ).values_list('cache__attrs', flat=True)
            for report_attrs in queryset:
                attr_value = report_attrs[self.attr_name]
                if attr_value not in data:
                    data[attr_value] = {
                        'attr_value': attr_value, 'safes': 0, 'unsafes': 0, 'unknowns': 0,
                        'url_params': '?attr_name={}&attr_value={}'.format(attr_name_q, quote(attr_value))
                    }
                data[attr_value][column] += 1
        return list(data[a_val] for a_val in sorted(data))


class ViewJobData:
    def __init__(self, user, view, job):
        self.user = user
        self.view = view
        self.job = job
        self.root = ReportRoot.objects.filter(job=self.job).first()
        self.report = ReportComponent.objects.filter(root__job=self.job, parent=None)\
            .only('id', 'component').first()

    @cached_property
    def core_link(self):
        if self.report and self.job.weight == JOB_WEIGHT[0][0]:
            return reverse('reports:component', args=[self.report.id])
        return None

    @cached_property
    def data(self):
        if 'data' not in self.view:
            return {}
        data = {}
        actions = {
            'safes': self.__safes_info,
            'unsafes': self.__unsafes_info,
            'unknowns': self.__unknowns_info,
            'resources': self.__resource_info,
            'tags_safe': self.__safe_tags_info,
            'tags_unsafe': self.__unsafe_tags_info,
            'attr_stat': self.__attr_statistic
        }
        for d in self.view['data']:
            if d in actions:
                data[d] = actions[d]()
        return data

    @cached_property
    def totals(self):
        if self.root:
            return get_leaves_totals(root=self.root)
        return {}

    @cached_property
    def problems(self):
        if not self.root:
            return []
        queryset = MarkUnknownReport.objects\
            .filter(report__root=self.root).exclude(type=ASSOCIATION_TYPE[2][0])\
            .values_list('report__component', 'problem').distinct().order_by('report__component', 'problem')

        cnt = 0
        problems = []
        for c_name, p_name in queryset:
            problems.append({'id': cnt, 'component': c_name, 'problem': p_name})
            cnt += 1
        return problems

    def __safe_tags_info(self):
        if not self.report:
            return []
        return TagsInfo(
            reverse('reports:safes', args=[self.report.id]),
            ReportSafeCache.objects.filter(report__root=self.root),
            SafeTag, self.view['safe_tag']
        ).info

    def __unsafe_tags_info(self):
        if not self.report:
            return []
        return TagsInfo(
            reverse('reports:unsafes', args=[self.report.id]),
            ReportUnsafeCache.objects.filter(report__root=self.root),
            UnsafeTag, self.view['unsafe_tag']
        ).info

    def __resource_info(self):
        if not self.root:
            return []
        return ResourcesInfo(
            self.user, self.view, self.root.instances,
            self.root.resources, self.root.resources.get('total')
        ).info

    def __unknowns_info(self):
        if not self.report:
            return []
        return UnknownsInfo(
            self.view, reverse('reports:unknowns', args=[self.report.id]),
            ReportUnknown.objects.filter(root=self.root)
        ).info

    def __safes_info(self):
        if not self.report:
            return []
        return VerdictsInfo(
            self.view, reverse('reports:safes', args=[self.report.pk]),
            ReportSafe.objects.filter(root=self.root), SafeVerdicts()
        ).info

    def __unsafes_info(self):
        if not self.report:
            return []
        return VerdictsInfo(
            self.view, reverse('reports:unsafes', args=[self.report.id]),
            ReportUnsafe.objects.filter(root=self.root), UnsafeVerdicts()
        ).info

    def __attr_statistic(self):
        if not self.report:
            return None
        return AttrStatisticsInfo(self.view, root=self.root).info


class ViewReportData:
    def __init__(self, user, view, report):
        self.user = user
        self.report = report
        self.view = view
        self.totals = get_leaves_totals(leaves__report=report)
        self.data = self.__get_view_data()

    def __get_view_data(self):
        if 'data' not in self.view:
            return {}
        data = {}
        actions = {
            'safes': self.__safes_info,
            'unsafes': self.__unsafes_info,
            'unknowns': self.__unknowns_info,
            'resources': self.__resource_info,
            'tags_safe': self.__safe_tags_info,
            'tags_unsafe': self.__unsafe_tags_info,
            'attr_stat': self.__attr_statistic
        }
        for d in self.view['data']:
            if d in actions:
                data[d] = actions[d]()
        return data

    def __safe_tags_info(self):
        return TagsInfo(
            reverse('reports:safes', args=[self.report.id]),
            ReportSafeCache.objects.filter(report__leaves__report=self.report),
            SafeTag, self.view['safe_tag']
        ).info

    def __unsafe_tags_info(self):
        return TagsInfo(
            reverse('reports:unsafes', args=[self.report.id]),
            ReportUnsafeCache.objects.filter(report__leaves__report=self.report),
            UnsafeTag, self.view['unsafe_tag']
        ).info

    def __resource_info(self):
        qs_filters = {}
        if 'resource_component' in self.view:
            filter_key = 'reportcomponent__component__{}'.format(self.view['resource_component'][0])
            qs_filters[filter_key] = self.view['resource_component'][1]
        report_base = Report.objects.get(id=self.report.id)
        reports_qs = report_base.get_descendants(include_self=True)\
            .exclude(reportcomponent=None).filter(**qs_filters).select_related('reportcomponent')\
            .annotate(component=F('reportcomponent__component'), finish_date=F('reportcomponent__finish_date'))\
            .only('reportcomponent__component', 'cpu_time', 'wall_time', 'memory', 'reportcomponent__finish_date')

        instances = {}
        res_data = {}
        res_total = {'cpu_time': 0, 'wall_time': 0, 'memory': 0}
        for report in reports_qs:
            component = report.component

            instances.setdefault(component, {'finished': 0, 'total': 0})
            instances[component]['total'] += 1
            if report.reportcomponent.finish_date:
                instances[component]['finished'] += 1

            if report.cpu_time or report.wall_time or report.memory:
                res_data.setdefault(component, {'cpu_time': 0, 'wall_time': 0, 'memory': 0})
            if report.cpu_time:
                res_data[component]['cpu_time'] += report.cpu_time
                res_total['cpu_time'] += report.cpu_time
            if report.wall_time:
                res_data[component]['wall_time'] += report.wall_time
                res_total['wall_time'] += report.wall_time
            if report.memory:
                res_data[component]['memory'] = max(report.memory, res_data[component]['memory'])
                res_total['memory'] = max(report.memory, res_total['memory'])

        return ResourcesInfo(self.user, self.view, instances, res_data, res_total).info

    def __unknowns_info(self):
        return UnknownsInfo(
            self.view, reverse('reports:unknowns', args=[self.report.id]),
            ReportUnknown.objects.filter(leaves__report=self.report)
        ).info

    def __safes_info(self):
        return VerdictsInfo(
            self.view, reverse('reports:safes', args=[self.report.pk]),
            ReportSafe.objects.filter(leaves__report=self.report), SafeVerdicts()
        ).info

    def __unsafes_info(self):
        return VerdictsInfo(
            self.view, reverse('reports:unsafes', args=[self.report.id]),
            ReportUnsafe.objects.filter(leaves__report=self.report), UnsafeVerdicts()
        ).info

    def __attr_statistic(self):
        return AttrStatisticsInfo(self.view, leaves__report=self.report).info
