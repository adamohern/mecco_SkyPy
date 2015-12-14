#!/usr/bin/env python

"""
 python_api_dump.py

 Version: 1.000

 Copyright (c) 2001-2014, Luxology LLC. All Rights Reserved.
 Patents granted and pending.

 Author: Gwynne Reddick

 Description: custom command to dump modo's python API packages & modules to
              dummy files to enable code completion/call tips in IDEs.

 Last Update: 21:16 22/05/14
"""

import os
import errno
import inspect
import re
import shutil
import types
import imp

import lx
import lxifc
import lxu


def msg_dialog(title, msg):
    cmd_svc = lx.service.Command()
    cmd_svc.ExecuteArgString(-1, lx.symbol.iCTAG_NULL, 'dialog.setup yesNo')
    cmd_svc.ExecuteArgString(-1, lx.symbol.iCTAG_NULL, 'dialog.title {%s}' % title)
    cmd_svc.ExecuteArgString(-1, lx.symbol.iCTAG_NULL, 'dialog.msg {%s}' % msg)
    try:
        cmd_svc.ExecuteArgString(-1, lx.symbol.iCTAG_NULL, 'dialog.open')
    except RuntimeError, e:
        pass
    result = lx.eval('dialog.result ?')
    lx.out(result)
    return True if result == 'ok' else False



class CmdPythonAPIDump(lxu.command.BasicCommand):
    """custom command to dump modo's python API packages & modules."""
    def __init__(self):
        lxu.command.BasicCommand.__init__(self)
        self.dyna_Add('outdir', lx.symbol.sTYPE_STRING)
        self.basic_SetFlags(0, lx.symbol.fCMDARG_OPTIONAL)

        self.outdir = None
        self.outfile = None

        # list of API packages & modules to export. Each is a tuple consisting
        # of the package pr module object and a boolean specifying whether
        # it's a package or not - there's no actual way to determine this
        # programatically that I can find.
        self.exports = [(lx, True),
                        (lxifc, False),
                        (lxu, True)]

        # compiled regex to extract the text between two braces - used to get
        # hold of method arguments specified in the docstrings of builtin
        # methods.
        self.argmatch = re.compile(r'.*\((.*?)\).*')

        # a list of python types this is actually used to test module/package
        # level members to determine whether they're defines (supports the
        # symbols & results modules)
        self.const_types = [types.FloatType,
                       types.IntType,
                       types.LongType,
                       types.StringType]

        # modo build number
        self.buildnum = lx.eval("query platformservice appbuild ?")
        # docstring to use at the head of each package's __init__.py file.
        self.pkg_docstring = "'''Autogenerated dummy {0} package enabling code \
completion in Python editors\n MODO Build #{1}\n'''\n\n"
        # docstring to use at the head of each module file.
        self.module_docstring = "'''Autogenerated dummy {0} module anabling \
code completion in Python editors\n MODO Build #{1}\n'''\n\n"

    def cmd_Flags(self):
        return 0

    def cmd_Enable(self, msg):
        return True

    def cmd_Interact(self):
        if not self.dyna_IsSet(0):
            self.outdir = self.dir_dialog("Output Folder")
            if not self.outdir:
                self._msg.SetCode(lx.symbol.e_ABORT)
                return

    def basic_Execute(self, msg, flags):
        try:
            if self.dyna_IsSet(0):
                self.outdir = self.dyna_String(0)
            # clear the previous API dump
            if os.path.isdir(self.outdir):
                if not msg_dialog("Delete Contents?",
                                  "Folder exists, any contents will be deleted, continue?"):
                    msg.SetCode(lx.symbol.e_ABORT)
                    return
                shutil.rmtree(self.outdir, True)
                for root, dirs, files in os.walk(self.outdir):
                    for f in files:
                        os.unlink(os.path.join(root, f))
                    for d in dirs:
                        shutil.rmtree(os.path.join(root, d))
            os.makedirs(self.outdir)

        except:
            # failed to prep output folder
            msg.SetCode(lx.symbol.e_FAILED)
            return

        # make sure all the lxu modules are explicitly imported so that
        # inspect can enumerate their members.
        extensions = ('.py', '.pyc', '.pyo')
        pathname = imp.find_module('lxu')[1]
        lxumods = set([os.path.splitext(module)[0]
                       for module
                       in os.listdir(pathname)
                       if module.endswith(extensions)])
        for mod in lxumods:
            if not mod.startswith("__"):
                __import__('lxu.{0}'.format(mod))

        for item in self.exports:
            if item[1]:
                # export is a package
                # set up a package directory if we need one
                pkgname = item[0].__name__
                pkgpath = os.path.join(self.outdir, pkgname)
                try:
                    os.makedirs(pkgpath)
                except OSError as exception:
                    if exception.errno != errno.EEXIST:
                        msg.SetCode(lx.symbol.e_FAILED)
                        return

                # check to see if there's an __init__.py and create one if not
                pkg_innit_path = os.path.join(pkgpath, "__init__.py")
                if not os.path.isfile(pkg_innit_path):
                    with open(pkg_innit_path, "w") as self.outfile:
                        self.outfile.write(
                            self.pkg_docstring.format(pkgname, self.buildnum))

                # process the package's modules
                modules = inspect.getmembers(item[0], inspect.ismodule)
                # add import statements to the package __innit__.py
                with open(pkg_innit_path, "a") as self.outfile:
                    for name, module in modules:
                        self.outfile.write("import {0}\n".format(name))
                    self.outfile.write("\n\n\n")

                # now process each module in turn
                for name, module in modules:
                    fname = name + ".py"
                    with open(os.path.join(pkgpath, fname), "w") as self.outfile:
                        self.do_module(name, module)

                # do any classes and/or methods defined at the package level,
                # mostly this is to support the old lx API
                with open(os.path.join(pkg_innit_path), "a") as self.outfile:
                    self.do_classes(item[0])
                    self.do_methods(item[0])

            else:
                # export is a module
                fname = item[0].__name__ + ".py"
                with open(os.path.join(self.outdir, fname), "w") as self.outfile:
                    self.do_module(item[0].__name__, item[0])

    def do_module(self, name, module):
        """Process a module."""
        # add module docstring
        self.outfile.write(self.module_docstring.format(name, self.buildnum))
        # process constants & globals
        self.do_constants(module)
        # process classes
        self.do_classes(module)
        # process module level methods (functions)
        self.do_methods(module, False)

    def do_classes(self, module):
        """Process any classes in a module or package."""
        for cls in inspect.getmembers(module, inspect.isclass):
            self.outfile.write("class {0}:\n".format(cls[0]))
            # class methods
            self.do_methods(cls[1])
            self.outfile.write("\n\n")

    def do_constants(self, module):
        """Process any 'constants' in the root of a package or module.
        Mainly used in order to dump the 'result' and 'symbols' modules.
        """
        for member in inspect.getmembers(module):
            if member[0].startswith("__"):
                continue
            if type(member[1]) in self.const_types:
                self.outfile.write("{0} = None\n".format(member[0]))

    def do_methods(self, cls, methods=True):
        """Process any methods in a class, module or package."""
        modmethod = inspect.ismodule(cls)
        indent = "    "
        if modmethod:
            indent = ""

        if methods:
            # we're looking for methods in a class
            members = inspect.getmembers(cls, inspect.isroutine)
        else:
            # we're looking for module functions
            members = inspect.getmembers(cls, inspect.isfunction)

        # no members found in the class definition so add a pass statement
        if methods and not members:
            self.outfile.write(indent + "pass\n")

        for method in members:
            # deal with any __init__ methods that have instance attributes
            # defined. We're going to try to be 'clever' and extract both the
            # attribute name and it's class so that we can inject it into the
            # code completion file with the right type. Don't know how robust
            # it will prove to be.
            if method[0] == "__init__":
                try:
                    # check for attributes
                    attrs = vars(cls())
                    # if no attributes just skip.
                    if not attrs:
                        continue
                    # output the method definition
                    self.outfile.write(indent + "def {0}(self):\n".format(method[0]))
                    # now try to build the attribute's object type initialise
                    # string.
                    for attr, val in attrs.iteritems():
                        _module = val.__class__.__module__
                        # if the object's class is a builtin we just want to drop
                        # the module string.
                        if _module == "__builtin__":
                            _module = ""
                        else:
                            _module += "."
                        _class = val.__class__.__name__
                        self.outfile.write(indent + "    self.{0} = {1}{2}()\n".format(attr, _module, _class))
                    self.outfile.write("\n")
                except:
                    # no attributes so we'll just punt on this __init__ method.
                    continue

            # skip python builtin methods
            if method[0].startswith("__"):
                continue
            # skip the lxu package which adds some util functions from lxu.utils
            # to that package namespace for convenience (one of Gwynne's less
            # than stellar ideas...)
            if cls.__name__ == "lxu" and modmethod:
                continue

            # get the docstring
            docstring = method[1].__doc__

            # quick hack to deal with the lx module level methods which don't
            # have any queriable data on arguments
            if cls.__name__ == "lx":
                argstring = ""

            # use the inspect module to check if this is a real method (as
            # opposed to a routine). These are methods in physical python
            # files - lxifc, lxu etc
            elif inspect.ismethod(method[1]) or modmethod:
                args = inspect.getargspec(method[1])
                if args:
                    argstring = ", ".join(args[0])

            # otherwise we have a 'routine' which means it's a builtin modo
            # python method and we need to wrangle the docstring to get the
            # method arguments
            elif docstring:
                argstring = self.args_from_docstring(docstring)

            # output the method definition
            self.outfile.write(indent + "def {0}({1}):\n".format(method[0],
                                                                 argstring))

            # write the docstring if one exists
            if docstring:
                self.outfile.write(indent + "    '''{0}'''\n".format(docstring))
            # and add a pass statement to complete the dummy method.
            self.outfile.write(indent + "    pass\n\n")

    def args_from_docstring(self, instring):
        """Extract the arguments from a builtin function's docstring."""
        if "=" in instring:
            instring = instring.split("=")[1].lstrip()
        try:
            argstr = self.argmatch.search(instring).group(1)
        except:
            argstr = None

        if not argstr:
            argstr = "self"
        else:
            funcargs = ["self",]
            tmpargs = argstr.split(",")
            for item in tmpargs:
                funcargs.append(item.split(" ")[1])
            argstr = ", ".join(funcargs)
        return argstr

    def dir_dialog(self, title, path=None):
        """ Display a directory dialog.

        """
        cmd_svc = lx.service.Command()
        cmd_svc.ExecuteArgString(-1, lx.symbol.iCTAG_NULL, 'dialog.setup dir')
        cmd_svc.ExecuteArgString(-1, lx.symbol.iCTAG_NULL, 'dialog.title {%s}' % title)
        if path:
            cmd_svc.ExecuteArgString(-1, lx.symbol.iCTAG_NULL, 'dialog.result {%s}' % path)
        try:
            cmd_svc.ExecuteArgString(-1, lx.symbol.iCTAG_NULL, 'dialog.open')
        except:
            return
        command = cmd_svc.Spawn(lx.symbol.iCTAG_NULL, 'dialog.result')
        val_arr = cmd_svc.Query(command, 0)
        if val_arr.Count() > 0:
            return val_arr.GetString(0)


lx.bless(CmdPythonAPIDump, "python.dumpAPI")


