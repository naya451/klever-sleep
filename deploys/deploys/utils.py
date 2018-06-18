#
# Copyright (c) 2018 ISPRAS (http://www.ispras.ru)
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

import errno
import getpass
import logging
import os
import pwd
import shutil
import subprocess
import sys
import tarfile
import tempfile


class Cd:
    def __init__(self, path):
        self.new_path = path

    def __enter__(self):
        self.prev_path = os.getcwd()
        os.chdir(self.new_path)

    def __exit__(self, etype, value, traceback):
        os.chdir(self.prev_path)


def execute_cmd(logger, *args, stdin=None, get_output=False, username=None):
    logger.info('Execute command "{0}"'.format(' '.join(args)))

    kwargs = {'stdin': stdin}

    def demote(uid, gid):
        def set_ids():
            os.setgid(gid)
            os.setuid(uid)

        return set_ids

    if username:
        pw_record = pwd.getpwnam(username)
        kwargs['preexec_fn'] = demote(pw_record.pw_uid, pw_record.pw_gid)

    if get_output:
        return subprocess.check_output(args, **kwargs).decode('utf8')
    else:
        subprocess.check_call(args, **kwargs)


def get_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s (%(filename)s:%(lineno)03d) %(levelname)s> %(message)s',
                                  "%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


def get_password(logger, prompt):
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    else:
        logger.warning('Password will be echoed')
        print(prompt, end='', flush=True)
        return sys.stdin.readline().rstrip()


def install_extra_dep_or_program(logger, name, deploy_dir, deploy_conf, prev_deploy_info, cmd_fn, install_fn):
    if name not in deploy_conf:
        logger.error('Entity "{0}" is not described'.format(name))
        sys.exit(errno.EINVAL)

    desc = deploy_conf[name]

    if 'version' not in desc:
        logger.error('Version is not specified for entity "{0}"'.format(name))
        sys.exit(errno.EINVAL)

    version = desc['version']

    if 'path' not in desc:
        logger.error('Path is not specified for entity "{0}"'.format(name))
        sys.exit(errno.EINVAL)

    path = desc['path'] if os.path.isabs(desc['path']) \
        else os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir, desc['path'])

    if not os.path.exists(path):
        logger.error('Path "{0}" does not exist'.format(path))
        sys.exit(errno.ENOENT)

    is_git_repo = False

    if os.path.isdir(path) and os.path.isdir(os.path.join(path, '.git')):
        is_git_repo = True
        if version != 'CURRENT':
            # Use commit hash to uniquely identify entity version if it is provided as Git repository.
            version = execute_cmd(logger, 'git', '-C', path, 'rev-list', '-n', '1', version, get_output=True).rstrip()

    prev_version = prev_deploy_info[name]['version'] if name in prev_deploy_info else None

    if version == prev_version and version != 'CURRENT':
        logger.info('Entity "{0}" is up to date (version: "{1}")'.format(name, version))
        return False

    if prev_version:
        logger.info('Update "{0}" from version "{1}" to version "{2}"'.format(name, prev_version, version))
    else:
        logger.info('Install "{0}" (version: "{1}")'.format(name, version))

    # Remove previous version of entity if so.
    if prev_version:
        cmd_fn('rm', '-rf', deploy_dir)

    if is_git_repo:
        if version == 'CURRENT':
            install_fn(path, deploy_dir, allow_symlink=True)
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Checkout specified version within local Git repository if this is allowed or clone local Git
                # repository to temporary directory and checkout specified version there.
                if desc.get('allow use local Git repository'):
                    tmp_path = path
                    execute_cmd(logger, 'git', '-C', tmp_path, 'checkout', '-fq', version)
                    execute_cmd(logger, 'git', '-C', tmp_path, 'clean', '-xfdq')
                else:
                    tmp_path = os.path.join(tmpdir, os.path.basename(os.path.realpath(path)))
                    execute_cmd(logger, 'git', 'clone', '-q', path, tmp_path)
                    execute_cmd(logger, 'git', '-C', tmp_path, 'checkout', '-q', version)

                # Remember actual Klever Core version since this won't be able after ignoring ".git" below.
                if name == 'Klever':
                    with Cd(os.path.join(tmp_path, 'core')):
                        execute_cmd(logger, './setup.py', 'egg_info')

                # Directory .git can be quite large so ignore it during installing except one needs it.
                install_fn(tmp_path, deploy_dir, ignore=None if desc.get('copy .git directory') else ['.git'])
    elif os.path.isfile(path) and tarfile.is_tarfile(path):
        archive = os.path.normpath(os.path.join(deploy_dir, os.pardir, os.path.basename(path)))
        install_fn(path, archive)
        cmd_fn('mkdir', '-p', '{0}'.format(deploy_dir))
        cmd_fn('tar', '-C', '{0}'.format(deploy_dir), '-xf', '{0}'.format(archive))
        cmd_fn('rm', '-rf', '{0}'.format(archive))
    elif os.path.isfile(path) or os.path.isdir(path):
        install_fn(path, deploy_dir, allow_symlink=True)
    else:
        logger.error('Could not install extra dependency or program since it is provided in the unsupported format')
        sys.exit(errno.ENOSYS)

    # Remember what extra dependencies were installed just if everything went well.
    prev_deploy_info[name] = {
        'version': version,
        'directory': deploy_dir
    }
    for attr in ('name', 'executable path'):
        if attr in desc:
            prev_deploy_info[name][attr] = desc[attr]

    return True


def install_extra_deps(logger, deploy_dir, deploy_conf, prev_deploy_info, cmd_fn, install_fn):
    is_update_controller_and_schedulers = False
    is_update_verification_backends = False
    
    if 'Klever Addons' in deploy_conf:
        deploy_addons_conf = deploy_conf['Klever Addons']

        if 'Klever Addons' not in prev_deploy_info:
            prev_deploy_info['Klever Addons'] = {}

        prev_deploy_addons_conf = prev_deploy_info['Klever Addons']

        for addon in deploy_addons_conf.keys():
            if addon == 'Verification Backends':
                if 'Verification Backends' not in prev_deploy_addons_conf:
                    prev_deploy_addons_conf['Verification Backends'] = {}

                for verification_backend in deploy_addons_conf['Verification Backends'].keys():
                    is_update_verification_backends |= \
                        install_extra_dep_or_program(logger, verification_backend,
                                                     os.path.join(deploy_dir, 'klever-addons', 'verification-backends',
                                                                  verification_backend),
                                                     deploy_addons_conf['Verification Backends'],
                                                     prev_deploy_addons_conf['Verification Backends'],
                                                     cmd_fn, install_fn)
            elif install_extra_dep_or_program(logger, addon, os.path.join(deploy_dir, 'klever-addons', addon),
                                              deploy_addons_conf, prev_deploy_addons_conf, cmd_fn, install_fn) \
                    and addon in ('CIF', 'CIL', 'Consul', 'VerifierCloud Client'):
                is_update_controller_and_schedulers = True

    return is_update_controller_and_schedulers, is_update_verification_backends


def install_programs(logger, deploy_dir, deploy_conf, prev_deploy_info, cmd_fn, install_fn):
    is_update_programs = False

    if 'Programs' in deploy_conf:
        deploy_programs_conf = deploy_conf['Programs']

        if 'Programs' not in prev_deploy_info:
            prev_deploy_info['Programs'] = {}

        prev_deploy_programs_conf = prev_deploy_info['Programs']

        for program in deploy_programs_conf.keys():
            program_deploy_dir = os.path.join(deploy_dir, 'klever-programs', program)
            if install_extra_dep_or_program(logger, program, program_deploy_dir, deploy_programs_conf,
                                            prev_deploy_programs_conf, cmd_fn, install_fn):
                is_update_programs = True
                # Allow using local source directories.
                cmd_fn('chown', '-LR', 'klever', program_deploy_dir)

    return is_update_programs


def need_verifiercloud_scheduler(prev_deploy_info):
    if 'Klever Addons' in prev_deploy_info:
        if 'VerifierCloud Client' in prev_deploy_info['Klever Addons']:
            return True

    return False


def start_services(logger, services):
    logger.info('Start services')
    for service in services:
        execute_cmd(logger, 'service', service, 'start')


def stop_services(logger, services, ignore_errors=False):
    logger.info('Stop services')
    for service in services:
        try:
            execute_cmd(logger, 'service', service, 'stop')
        except subprocess.CalledProcessError:
            if ignore_errors:
                pass
            else:
                raise
