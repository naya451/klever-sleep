#
# Copyright (c) 2014-2015 ISPRAS (http://www.ispras.ru)
# Institute for System Programming of the Russian Academy of Sciences
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

import re

from core.lkvog.strategies.strategy_utils import Module, Graph
from core.lkvog.strategies.abstract_strategy import AbstractStrategy


class Coverage(AbstractStrategy):
    def __init__(self, logger, strategy_params, params):
        super().__init__(logger)
        self.callgraph = {}
        self.analyzed_modules = set()

        self.coverage_files = params['coverage files']
        self.work_dirs = params.get('work dirs', [])
        self.covered_funcs = None
        self._build_coverage()

    def _divide(self, module_name):
        return [Graph([Module(module_name)])]

    def divide_by_function(self, func):
        file_func = self.get_files_by_func(func)[0]
        process = [((file_func, func), [file_func])]
        found_path = None
        while process:
            current, path = process.pop(0)
            if current in self.covered_funcs:
                self.logger.debug("Found path {0}".format(path))
                found_path = path
                break
            for new_func in self.callgraph.get(current, []):
                new_path = path[:]
                new_path.append(new_func[0])
                process.append((new_func, new_path))

        if found_path:
            modules = set()
            for file in set(found_path):
                modules.add(Module(self.get_module_by_file(file)))
            return [Graph(list(modules))]
        else:
            return [Graph([Module(m)]) for m in self.get_modules_by_func(func)]

    def _set_dependencies(self, deps, sizes):
        pass

    def set_callgraph(self, callgraph):
        for func, desc in callgraph.items():
            for file, desc_file in desc.items():
                if file == 'unknown':
                    continue
                self.callgraph.setdefault((file, func), [])
                for called_func, called_desc in desc_file.get('called in', {}).items():
                    for called_file in called_desc:
                        if called_file == 'unknown':
                            continue
                        self.callgraph[(file, func)].append((called_file, called_func))

                for calls_func, calls_desc in desc_file.get('calls', {}).items():
                    for calls_file in calls_desc:
                        if calls_file == 'unknown':
                            continue
                        self.callgraph.setdefault((calls_file, calls_func), [])
                        self.callgraph[(calls_file, calls_func)].append((file, func))

    def need_callgraph(self):
        return True

    def get_modules_to_build(self, modules):
        return [], True

    def _build_coverage(self):
        self.covered_funcs = set()
        for file in self.coverage_files:
            with open(file, encoding='utf=8') as fp:
                current_file = None
                for line in fp:
                    line = line.rstrip('\n')
                    if line.startswith('SF:'):
                        current_file = line[len('SF:'):]
                        current_file = self._cut_work_dirs(current_file)
                        continue
                    elif line.startswith('FNDA:'):
                        func = line.split(',')[1]
                        self.logger.debug("Covered func is {0}".format((current_file, func)))
                        self.covered_funcs.add((current_file, func))

    def _cut_work_dirs(self, file):
        for work_dir in self.work_dirs:
            if file.startswith(work_dir):
                return file[len(work_dir):]
        return file