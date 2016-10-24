#
# Copyright (c) 2014-2016 ISPRAS (http://www.ispras.ru)
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
import os
import json


class ErrorTrace:
    MODEL_COMMENT_TYPES = 'AUX_FUNC|MODEL_FUNC|NOTE|ASSERT'

    def __init__(self, logger):
        self._nodes = dict()
        self._files = list()
        self._funcs = list()
        self._logger = logger
        self._entry_node_id = None
        self._violation_node_ids = set()
        self._violation_edges = list()
        self._model_funcs = dict()
        self._notes = dict()
        self._asserts = dict()
        self.aux_funcs = dict()
        self.emg_comments = dict()

    @property
    def functions(self):
        return enumerate(self._funcs)

    @property
    def files(self):
        return enumerate(self._files)

    @property
    def violation_nodes(self):
        return ([key, self._nodes[key]] for key in sorted(self._violation_node_ids))

    @property
    def entry_node(self):
        if self._entry_node_id:
            return self._nodes[self._entry_node_id]
        else:
            raise KeyError('Entry node has not been set yet')

    def serialize(self):
        edge_id = 0
        edges = list()
        # The first
        nodes = [[None]]
        for edge in list(self.trace_iterator()):
            edges.append(edge)
            edge['source node'] = len(nodes) - 1
            edge['target node'] = len(nodes)

            nodes[-1].append(edge_id)
            nodes.append([edge_id])
            edge_id += 1
        # The last
        nodes[-1].append(None)

        data = {
            'nodes': nodes,
            'edges': edges,
            'entry node': 0,
            'violation nodes': [self._nodes[i]['in'][0]['target node'] for i in sorted(self._violation_node_ids)],
            'files': self._files,
            'funcs': self._funcs
        }
        return data

    def add_entry_node_id(self, node_id):
        self._entry_node_id = node_id

    def add_node(self, node_id):
        if node_id in self._nodes:
            raise ValueError('There is already added node with an identifier {!r}'.format(node_id))
        self._nodes[node_id] = {'in': list(), 'out': list()}
        return self._nodes[node_id]

    def add_edge(self, source, target):
        source_node = self._nodes[source]
        target_node = self._nodes[target]

        edge = {'source node': source_node, 'target node': target_node}
        source_node['out'].append(edge)
        target_node['in'].append(edge)
        return edge

    def add_violation_node_id(self, identifier):
        self._violation_node_ids.add(identifier)

    def add_file(self, file_name):
        if file_name not in self._files:
            self._files.append(file_name)
            return self.resolve_file_id(file_name)
        else:
            return self.resolve_file_id(file_name)

    def add_function(self, name):
        if name not in self._funcs:
            self._funcs.append(name)
            return self.resolve_function_id(name)
        else:
            return self.resolve_function_id(name)

    def add_aux_func(self, identifier, name):
        self.aux_funcs[identifier] = name

    def add_emg_comment(self, file, line, data):
        if file not in self.emg_comments:
            self.emg_comments[file] = dict()
        self.emg_comments[file][line] = data

    def resolve_file_id(self, file):
        return self._files.index(file)

    def resolve_file(self, identifier):
        return self._files[identifier]

    def resolve_function_id(self, name):
        return self._funcs.index(name)

    def resolve_function(self, identifier):
        return self._funcs[identifier]

    def trace_iterator(self, begin=None, end=None, backward=False):
        # todo: Warning! This does work only if you guarantee:
        # *having no nore than one input edge for all nodes
        # *existance of at least one violation node and at least one input node
        if backward:
            if not begin:
                begin = [node for identifier, node in self.violation_nodes][0]['in'][0]
            if not end:
                end = self.entry_node['out'][0]
            getter = self.previous_edge
        else:
            if not begin:
                begin = self.entry_node['out'][0]
            if not end:
                end = [node for identifier, node in self.violation_nodes][0]['in'][0]
            getter = self.next_edge

        current = None
        while True:
            if not current:
                current = begin
                yield current
            if current is end:
                raise StopIteration
            else:
                current = getter(current)
                if not current:
                    raise StopIteration
                else:
                    yield current

    def insert_edge_and_target_node(self, edge):
        new_edge = {
            'target node': None,
            'source node': None,
            'file': 0
        }
        new_node = self.add_node(int(len(self._nodes)))

        edge['target node']['in'].remove(edge)
        edge['target node']['in'].append(new_edge)
        new_edge['target node'] = edge['target node']
        edge['target node'] = new_node
        new_node['in'] = [edge]
        new_node['out'] = [new_edge]
        new_edge['source node'] = new_node

        return new_edge

    def remove_edge_and_target_node(self, edge):
        # Do not delete edge with a warning
        if 'warn' in edge:
            raise ValueError('Cannot delete edge with warning: {!r}'.format(edge['source']))
        if id(edge['target node']) in [id(v) for i, v in self.violation_nodes]:
            raise ValueError('Is not allowed to delete violation nodes')

        source = edge['source node']
        target = edge['target node']

        source['out'].remove(edge)
        target['in'].remove(edge)
        for out_edge in target['out']:
            out_edge['source node'] = source
            source['out'].append(out_edge)
        del target

    @staticmethod
    def next_edge(edge):
        if len(edge['target node']['out']) > 0:
            return edge['target node']['out'][0]
        else:
            return None

    @staticmethod
    def previous_edge(edge):
        if len(edge['source node']['in']) > 0:
            return edge['source node']['in'][0]
        else:
            return None
        
    def find_violation_path(self):
        self._find_violation_path()
        self._mark_witness()
        
    def _find_violation_path(self):
        self._logger.info('Get violation path')
        ignore_edges_of_func_id = None
        for edge in self.trace_iterator(backward=True):
            if not ignore_edges_of_func_id and 'return' in edge:
                ignore_edges_of_func_id = edge['return']

            if 'enter' in edge and edge['enter'] == ignore_edges_of_func_id:
                ignore_edges_of_func_id = None

            if not ignore_edges_of_func_id:
                self._violation_edges.append(edge)

    def parse_model_comments(self):
        self._logger.info('Parse model comments from source files referred by witness')
        emg_comment = re.compile('/\*\sLDV\s(.*)\s\*/')

        for file_id, file in self.files:
            if not os.path.isfile(file):
                raise FileNotFoundError('File {!r} referred by witness does not exist'.format(file))

            self._logger.debug('Parse model comments from {!r}'.format(file))

            with open(file, encoding='utf8') as fp:
                line = 0
                for text in fp:
                    line += 1

                    # Try match EMG comment
                    # Expect comment like /* TYPE Instance Text */
                    match = emg_comment.search(text)
                    if match:
                        data = json.loads(match.group(1))
                        self.add_emg_comment(file_id, line, data)

                    # Match rest comments
                    match = re.search(r'/\*\s+({0})\s+(.*)\*/'.format(self.MODEL_COMMENT_TYPES), text)
                    if match:
                        kind, comment = match.groups()

                        comment = comment.rstrip()

                        if kind == 'AUX_FUNC' or kind == 'MODEL_FUNC':
                            # Get necessary function name located on following line.
                            try:
                                text = next(fp)
                                # Don't forget to increase counter.
                                line += 1
                                match = re.search(r'(ldv_\w+)', text)
                                if match:
                                    func_name = match.groups()[0]
                                else:
                                    raise ValueError(
                                        'Auxiliary/model function definition is not specified in {!r}'.format(text))
                            except StopIteration:
                                raise ValueError('Auxiliary/model function definition does not exist')

                            # Deal with functions referenced by witness.
                            for func_id, ref_func_name in self.functions:
                                if ref_func_name == func_name:
                                    if kind == 'AUX_FUNC':
                                        self.add_aux_func(func_id, None)
                                        self._logger.debug("Get auxiliary function '{0}' from '{1}:{2}'".
                                                           format(func_name, file, line))
                                    else:
                                        self._model_funcs[func_id] = comment
                                        self._logger.debug("Get note 'dict()' for model function '{1}' from '{2}:{3}'".
                                                           format(comment, func_name, file, line))

                                    break
                        else:
                            if file_id not in self._notes:
                                self._notes[file_id] = dict()
                            self._notes[file_id][line + 1] = comment
                            self._logger.debug(
                                "Get note '{0}' for statement from '{1}:{2}'".format(comment, file, line + 1))
                            # Some assertions will become warnings.
                            if kind == 'ASSERT':
                                if file_id not in self._asserts:
                                    self._asserts[file_id] = dict()
                                self._asserts[file_id][line + 1] = comment
                                self._logger.debug("Get assertiom '{0}' for statement from '{1}:{2}'".
                                                   format(comment, file, line + 1))

    def _mark_witness(self):
        self._logger.info('Mark witness with model comments')

        # Two stages are required since for marking edges with warnings we need to know whether there notes at violation
        # path below.
        warn_edges = list()
        for edge in self.trace_iterator():
            file_id = edge['file']
            file = self.resolve_file(file_id)
            start_line = edge['start line']

            if 'enter' in edge:
                func_id = edge['enter']
                if func_id in self._model_funcs:
                    note = self._model_funcs[func_id]
                    edge['note'] = note

            if file_id in self._notes and start_line in self._notes[file_id]:
                note = self._notes[file_id][start_line]
                self._logger.debug("Add note {!r} for statement from '{}:{}'".format(note, file, start_line))
                edge['note'] = note

        for edge in self.trace_iterator(backward=True):
            file_id = edge['file']
            file = self.resolve_file(file_id)
            start_line = edge['start line']

            if file_id in self._asserts and start_line in self._asserts[file_id]:
                # Add warning just if there are no more edges with notes at violation path below.
                track_notes = False
                note_found = False
                for violation_edge in reversed(self._violation_edges):
                    if track_notes:
                        if 'note' in violation_edge:
                            note_found = True
                            break
                    if id(violation_edge) == id(edge):
                        track_notes = True

                if not note_found:
                    warn = self._asserts[file_id][start_line]
                    self._logger.debug(
                        "Add warning {!r} for statement from '{}:{}'".format(warn, file, start_line))
                    # Add warning either to edge itself or to first edge that enters function and has note at
                    # violation path. If don't do the latter warning will be hidden by error trace visualizer.
                    warn_edge = edge
                    for violation_edge in self._violation_edges:
                        if 'enter' in violation_edge and 'note' in violation_edge:
                            warn_edge = violation_edge
                            break
                    warn_edge['warn'] = warn
                    warn_edges.append(warn_edge)

                    # Remove added warning to avoid its addition one more time.
                    del self._asserts[file_id][start_line]

        # Remove notes from edges marked with warnings. Otherwise error trace visualizer will be confused.
        for warn_edge in warn_edges:
            if 'note' in warn_edge:
                del warn_edge['note']

        del self._violation_edges, self._model_funcs, self._notes, self._asserts
