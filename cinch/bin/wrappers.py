from __future__ import print_function

from contextlib import contextmanager
from plumbum import local
from plumbum.commands.processes import ProcessExecutionError
from os import path, chdir, getcwd
from traceback import print_exc

import yaml
import sys


BASE = path.abspath(path.join(path.dirname(__file__), '..'))


def call_ansible(inventory, *args):
    """
    Wraps a call out to the ansible-playbook executable, passing it the cinch
    site.yml file that kicks off this playbook.

    :param inventory: The Ansible inventory file to pass through
    :param args: An array of other command-line arguments to ansible-playbook
    to pass
    :return: The exit code returned from ansible-playbook, or 255 if errors
    come from elsewhere
    """
    # Construct the arguments to pass to Ansible by munging the arguments
    # provided to this method
    ansible_args = [
        path.join(BASE, 'site.yml'),
        '-i', inventory,
        '-v',
        '--ssh-common-args=-o StrictHostKeyChecking=no'
    ]
    ansible_args.extend(args)
    ansible = local['ansible-playbook']
    command_handler(ansible, ansible_args)


def call_linchpin(work_dir, arg):
    """
    Wraps a call out to the linchpin executable, and then kicks off a cinch
    Ansible playbook if necessary.

    :param work_dir: The linch-pin working directory that contains a PinFile
    and associated configuration files
    :param args: An array of other command-line arguments to linchpin to pass
    :return: The exit code returned from linchpin, or 255 if errors come from
    elsewhere
    """
    # cinch will only support a subset of linchpin subcommands
    supported_cmds = ['rise']
    if arg not in supported_cmds:
        raise Exception('linchpin command \'' + arg + '\' not '
                        'supported by cinch')
    # Attempt to open the linch-pin PinFile
    try:
        with open(path.join(work_dir, 'PinFile')) as pin_file:
            pin_file_yaml = yaml.safe_load(pin_file)
    except IOError:
        print('linch-pin PinFile not found in ' + work_dir)
        sys.exit(1)
    # We must find a topology section named 'cinch' to determine where our
    # inventory file will live
    try:
        cinch_topology = 'cinch'
        topology = pin_file_yaml[cinch_topology]['topology']
    except KeyError:
        print('linch-pin PinFile must contain a topology '
              'section named \'' + cinch_topology + '\'')
        sys.exit(1)
    #  The inventory file generated by linchpin that will be used by cinch for
    #  configuration
    try:
        topology_path = path.join(work_dir, 'topologies', topology)
        with open(topology_path) as topology_file:
            topology_yaml = yaml.safe_load(topology_file)
    except IOError:
        print('linch-pin topology file not found at ' +
              topology_path)
        sys.exit(1)
    inventory_file = topology_yaml['topology_name'] + '.inventory'

    # As of right now the linch-pin working directory is not configurable, so
    # we essentially have a 'pushd' here to switch to the linch-pin working
    # directory as needed. This code can be removed if the following issue is
    # resolved:
    # https://github.com/CentOS-PaaS-SIG/linch-pin/issues/119
    @contextmanager
    def pushd(new_dir):
        previous_dir = getcwd()
        chdir(new_dir)
        yield
        chdir(previous_dir)

    with pushd(work_dir):
        linchpin = local['linchpin']
        exit_code = command_handler(linchpin, arg)
    # If linchpin is asked to provision resources, we will then run our
    # cinch playbooks
    # TODO: Add support for 'drop' and other supported linchpin command
    # subsets
    if arg == 'rise' and exit_code == 0:
        call_ansible(path.join(work_dir, 'inventory', inventory_file))


def command_handler(command, args):
    """
    Generic function to run external programs.
    :param command: Exectuable to run
    :param args: arguments to be given to the external executable
    """
    try:
        command.run(args, stdout=sys.stdout, stderr=sys.stderr)
        exit_code = 0
    except ProcessExecutionError as ex:
        print("Error encountered while executing command.",
              file=sys.stderr)
        exit_code = ex.retcode
    except Exception as ex:
        print("Unknown error occurred: {0}".format(ex), file=sys.stderr)
        print_exc()
        exit_code = 255
    return exit_code