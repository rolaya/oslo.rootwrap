# Copyright (c) 2011 OpenStack Foundation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os
import re
import shutil
import sys
import logging
from oslo_rootwrap import log_utils

NETNS_VARS = ('net', 'netn', 'netns')
EXEC_VARS = ('e', 'ex', 'exe', 'exec')

LOG = logging.getLogger(__name__)

if sys.platform != 'win32':
    # NOTE(claudiub): pwd is a Linux-specific library, and currently there is
    # no Windows support for oslo.rootwrap.
    import pwd


def _getuid(user):
    LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
    """Return uid for user."""
    return pwd.getpwnam(user).pw_uid


class CommandFilter(object):
    LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
    """Command filter only checking that the 1st argument matches exec_path."""

    def __init__(self, exec_path, run_as, *args):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        self.name = ''
        self.exec_path = exec_path
        self.run_as = run_as
        self.args = args
        self.real_exec = None

    def get_exec(self, exec_dirs=None):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        """Returns existing executable, or empty string if none found."""
        exec_dirs = exec_dirs or []
        if self.real_exec is not None:
            return self.real_exec
        if os.path.isabs(self.exec_path):
            if os.access(self.exec_path, os.X_OK):
                self.real_exec = self.exec_path
        else:
            for binary_path in exec_dirs:
                expanded_path = os.path.join(binary_path, self.exec_path)
                if os.access(expanded_path, os.X_OK):
                    self.real_exec = expanded_path
                    break
        return self.real_exec

    def match(self, userargs):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        """Only check that the first argument (command) matches exec_path."""
        return userargs and os.path.basename(self.exec_path) == userargs[0]

    def preexec(self):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        """Setuid in subprocess right before command is invoked."""
        if self.run_as != 'root':
            os.setuid(_getuid(self.run_as))

    def get_command(self, userargs, exec_dirs=None):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        """Returns command to execute."""
        exec_dirs = exec_dirs or []
        to_exec = self.get_exec(exec_dirs=exec_dirs) or self.exec_path
        return [to_exec] + userargs[1:]

    def get_environment(self, userargs):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        """Returns specific environment to set, None if none."""
        return None


class RegExpFilter(CommandFilter):
    LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
    """Command filter doing regexp matching for every argument."""

    def match(self, userargs):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        # Early skip if command or number of args don't match
        if (not userargs or len(self.args) != len(userargs)):
            # DENY: argument numbers don't match
            return False
        # Compare each arg (anchoring pattern explicitly at end of string)
        for (pattern, arg) in zip(self.args, userargs):
            try:
                if not re.match(pattern + '$', arg):
                    # DENY: Some arguments did not match
                    return False
            except re.error:
                # DENY: Badly-formed filter
                return False
        # ALLOW: All arguments matched
        return True


class PathFilter(CommandFilter):
    LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
    """Command filter checking that path arguments are within given dirs

        One can specify the following constraints for command arguments:
            1) pass     - pass an argument as is to the resulting command
            2) some_str - check if an argument is equal to the given string
            3) abs path - check if a path argument is within the given base dir

        A typical rootwrapper filter entry looks like this:
            # cmdname: filter name, raw command, user, arg_i_constraint [, ...]
            chown: PathFilter, /bin/chown, root, nova, /var/lib/images

    """

    def match(self, userargs):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        if not userargs or len(userargs) < 2:
            return False

        arguments = userargs[1:]

        equal_args_num = len(self.args) == len(arguments)
        exec_is_valid = super(PathFilter, self).match(userargs)
        args_equal_or_pass = all(
            arg == 'pass' or arg == value
            for arg, value in zip(self.args, arguments)
            if not os.path.isabs(arg)  # arguments not specifying abs paths
        )
        paths_are_within_base_dirs = all(
            os.path.commonprefix([arg, os.path.realpath(value)]) == arg
            for arg, value in zip(self.args, arguments)
            if os.path.isabs(arg)  # arguments specifying abs paths
        )

        return (equal_args_num and
                exec_is_valid and
                args_equal_or_pass and
                paths_are_within_base_dirs)

    def get_command(self, userargs, exec_dirs=None):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        exec_dirs = exec_dirs or []
        command, arguments = userargs[0], userargs[1:]

        # convert path values to canonical ones; copy other args as is
        args = [os.path.realpath(value) if os.path.isabs(arg) else value
                for arg, value in zip(self.args, arguments)]

        return super(PathFilter, self).get_command([command] + args,
                                                   exec_dirs)


class KillFilter(CommandFilter):
    LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
    """Specific filter for the kill calls.

       1st argument is the user to run /bin/kill under
       2nd argument is the location of the affected executable
           if the argument is not absolute, it is checked against $PATH
       Subsequent arguments list the accepted signals (if any)

       This filter relies on /proc to accurately determine affected
       executable, so it will only work on procfs-capable systems (not OSX).
    """

    def __init__(self, *args):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        super(KillFilter, self).__init__("/bin/kill", *args)

    @staticmethod
    def _program_path(command):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        """Try to determine the full path for command.

        Return command if the full path cannot be found.
        """

        # shutil.which() was added to Python 3.3
        if hasattr(shutil, 'which'):
            return shutil.which(command)

        if os.path.isabs(command):
            return command

        path = os.environ.get('PATH', os.defpath).split(os.pathsep)
        for dir in path:
            program = os.path.join(dir, command)
            if os.path.isfile(program):
                return program

        return command

    def _program(self, pid):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        """Determine the program associated with pid"""

        try:
            command = os.readlink("/proc/%d/exe" % int(pid))
        except (ValueError, EnvironmentError):
            # Incorrect PID
            return None

        # NOTE(yufang521247): /proc/PID/exe may have '\0' on the
        # end (ex: if an executable is updated or deleted), because python
        # doesn't stop at '\0' when read the target path.
        command = command.partition('\0')[0]

        # NOTE(dprince): /proc/PID/exe may have ' (deleted)' on
        # the end if an executable is updated or deleted
        if command.endswith(" (deleted)"):
            command = command[:-len(" (deleted)")]

        if os.path.isfile(command):
            return command

        # /proc/PID/exe may have been renamed with
        # a ';......' or '.#prelink#......' suffix etc.
        # So defer to /proc/PID/cmdline in that case.
        try:
            with open("/proc/%d/cmdline" % int(pid)) as pfile:
                cmdline = pfile.read().partition('\0')[0]

            cmdline = self._program_path(cmdline)
            if os.path.isfile(cmdline):
                command = cmdline

            # Note we don't return None if cmdline doesn't exist
            # as that will allow killing a process where the exe
            # has been removed from the system rather than updated.
            return command
        except EnvironmentError:
            return None

    def match(self, userargs):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        if not userargs or userargs[0] != "kill":
            return False
        args = list(userargs)
        if len(args) == 3:
            # A specific signal is requested
            signal = args.pop(1)
            if signal not in self.args[1:]:
                # Requested signal not in accepted list
                return False
        else:
            if len(args) != 2:
                # Incorrect number of arguments
                return False
            if len(self.args) > 1:
                # No signal requested, but filter requires specific signal
                return False

        command = self._program(args[1])
        if not command:
            return False

        kill_command = self.args[0]

        if os.path.isabs(kill_command):
            return kill_command == command

        return (os.path.isabs(command) and
                kill_command == os.path.basename(command) and
                os.path.dirname(command) in os.environ.get('PATH', ''
                                                           ).split(':'))


class ReadFileFilter(CommandFilter):
    LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
    """Specific filter for the utils.read_file_as_root call."""

    def __init__(self, file_path, *args):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        self.file_path = file_path
        super(ReadFileFilter, self).__init__("/bin/cat", "root", *args)

    def match(self, userargs):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        return (userargs == ['cat', self.file_path])


class IpFilter(CommandFilter):
    LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
    """Specific filter for the ip utility to that does not match exec."""

    def match(self, userargs):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        if userargs[0] == 'ip':
            # Avoid the 'netns exec' command here
            for a, b in zip(userargs[1:], userargs[2:]):
                if a in NETNS_VARS:
                    return b not in EXEC_VARS
            else:
                return True


class EnvFilter(CommandFilter):
    LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
    """Specific filter for the env utility.

    Behaves like CommandFilter, except that it handles
    leading env A=B.. strings appropriately.
    """

    def _extract_env(self, arglist):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        """Extract all leading NAME=VALUE arguments from arglist."""

        envs = set()
        for arg in arglist:
            if '=' not in arg:
                break
            envs.add(arg.partition('=')[0])
        return envs

    def __init__(self, exec_path, run_as, *args):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        super(EnvFilter, self).__init__(exec_path, run_as, *args)

        env_list = self._extract_env(self.args)
        # Set exec_path to X when args are in the form of
        # env A=a B=b C=c X Y Z
        if "env" in exec_path and len(env_list) < len(self.args):
            self.exec_path = self.args[len(env_list)]

    def match(self, userargs):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        # ignore leading 'env'
        if userargs[0] == 'env':
            userargs.pop(0)

        # require one additional argument after configured ones
        if len(userargs) < len(self.args):
            return False

        # extract all env args
        user_envs = self._extract_env(userargs)
        filter_envs = self._extract_env(self.args)
        user_command = userargs[len(user_envs):len(user_envs) + 1]

        # match first non-env argument with CommandFilter
        return (super(EnvFilter, self).match(user_command) and
                len(filter_envs) and user_envs == filter_envs)

    def exec_args(self, userargs):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        args = userargs[:]

        # ignore leading 'env'
        if args[0] == 'env':
            args.pop(0)

        # Throw away leading NAME=VALUE arguments
        while args and '=' in args[0]:
            args.pop(0)

        return args

    def get_command(self, userargs, exec_dirs=[]):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        to_exec = self.get_exec(exec_dirs=exec_dirs) or self.exec_path
        return [to_exec] + self.exec_args(userargs)[1:]

    def get_environment(self, userargs):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        env = os.environ.copy()

        # ignore leading 'env'
        if userargs[0] == 'env':
            userargs.pop(0)

        # Handle leading NAME=VALUE pairs
        for a in userargs:
            env_name, equals, env_value = a.partition('=')
            if not equals:
                break
            if env_name and env_value:
                env[env_name] = env_value

        return env


class ChainingFilter(CommandFilter):
    LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
    def exec_args(self, userargs):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        return []


class IpNetnsExecFilter(ChainingFilter):
    LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
    """Specific filter for the ip utility to that does match exec."""

    def match(self, userargs):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        # Network namespaces currently require root
        # require <ns> argument
        if self.run_as != "root" or len(userargs) < 4:
            return False

        return (userargs[0] == 'ip' and userargs[1] in NETNS_VARS and
                userargs[2] in EXEC_VARS)

    def exec_args(self, userargs):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        args = userargs[4:]
        if args:
            args[0] = os.path.basename(args[0])
        return args


class ChainingRegExpFilter(ChainingFilter):
    LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
    """Command filter doing regexp matching for prefix commands.

    Remaining arguments are filtered again. This means that the command
    specified as the arguments must be also allowed to execute directly.
    """

    def match(self, userargs):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        # Early skip if number of args is smaller than the filter
        if (not userargs or len(self.args) > len(userargs)):
            return False
        # Compare each arg (anchoring pattern explicitly at end of string)
        for (pattern, arg) in zip(self.args, userargs):
            try:
                if not re.match(pattern + '$', arg):
                    # DENY: Some arguments did not match
                    return False
            except re.error:
                # DENY: Badly-formed filter
                return False
        # ALLOW: All arguments matched
        return True

    def exec_args(self, userargs):
        LOG.info('%s() caller: %s()', log_utils.get_fname(1), log_utils.get_fname(2))
        args = userargs[len(self.args):]
        if args:
            args[0] = os.path.basename(args[0])
        return args
