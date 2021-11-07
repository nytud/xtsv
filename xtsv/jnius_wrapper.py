#!/usr/bin/env python3
# -*- coding: utf-8, vim: expandtab:ts=4 -*-

"""
(Mimic the) import of PyJNIus through import (dummy or real) jnius_config and throw exception only when import_pyjnius()
 is actually called
"""

import os


class DummyJniusConfig:
    dummy = True
    classpath_show_warning = True
    options = []
    classpath = None
    vm_running = False

    @staticmethod
    def set_options(*_):
        pass

    @staticmethod
    def add_options(*_):
        pass

    @staticmethod
    def get_options():
        pass

    @staticmethod
    def set_classpath(*_):
        pass

    @staticmethod
    def add_classpath(*_):
        pass

    @staticmethod
    def get_classpath():
        pass

    @staticmethod
    def expand_classpath():
        pass


try:
    import jnius_config
    jnius_config.dummy = False
    jnius_config.classpath_show_warning = True
except ImportError:
    jnius_config = DummyJniusConfig()


def import_pyjnius():
    if jnius_config.dummy:
        raise ImportError('WARNING: PyJNIus could not be imported!')
    """
    PyJNIus can only be imported once per Python interpreter and one must set the classpath before importing...
    """
    # Check if autoclass is already imported...
    if not jnius_config.vm_running:

        # Tested on Ubuntu 18.04 64bit with openjdk-11 JDK and JRE installed:
        # sudo apt install openjdk-11-jdk-headless openjdk-11-jre-headless

        # Set JAVA_HOME for this session
        try:
            os.environ['JAVA_HOME']
        except KeyError:
            os.environ['JAVA_HOME'] = '/usr/lib/jvm/java-11-openjdk-amd64/'

        # Set path and import jnius for this session
        from jnius import autoclass
    elif not jnius_config.classpath_show_warning:
        from jnius import autoclass  # Warning already had shown. It is enough to show it only once!
    else:
        import sys
        from jnius import autoclass
        system_class = autoclass('java.lang.System')
        sep = system_class.getProperty('path.separator')
        urls = system_class.getProperty('java.class.path').split(sep)
        cp = ':'.join(urls)

        jnius_config.classpath_show_warning = False
        print('Warning: PyJNIus is already imported with the following classpath: {0} Please check if it is ok!'.
              format(cp), file=sys.stderr)

    # Return autoclass for later use...
    return autoclass
