#!/usr/bin/env python2
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import print_function

__license__   = 'GPL v3'
__copyright__ = '2010, Kovid Goyal <kovid@kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

import os, shutil, time, sys

from calibre import isbytestring
from calibre.constants import (iswindows, isosx, plugins, filesystem_encoding,
        islinux)

recycle = None

if iswindows:
    from calibre.utils.ipc import eintr_retry_call
    from threading import Lock
    recycler = None
    rlock = Lock()

    def start_recycler():
        global recycler
        if recycler is None:
            from calibre.utils.ipc.simple_worker import start_pipe_worker
            recycler = start_pipe_worker('from calibre.utils.recycle_bin import recycler_main; recycler_main()')

    def recycle_path(path):
        from win32com.shell import shell, shellcon
        flags = (shellcon.FOF_ALLOWUNDO | shellcon.FOF_NOCONFIRMATION | shellcon.FOF_NOCONFIRMMKDIR | shellcon.FOF_NOERRORUI |
                 shellcon.FOF_SILENT | shellcon.FOF_RENAMEONCOLLISION)
        retcode, aborted = shell.SHFileOperation((0, shellcon.FO_DELETE, path, None, flags, None, None))
        if retcode != 0 or aborted:
            raise RuntimeError('Failed to delete: %r with error code: %d' % (path, retcode))

    def recycler_main():
        while True:
            path = eintr_retry_call(sys.stdin.readline)
            if not path:
                break
            try:
                path = path.decode('utf-8').rstrip()
            except (ValueError, TypeError):
                break
            try:
                recycle_path(path)
            except:
                eintr_retry_call(print, b'KO', file=sys.stdout)
                sys.stdout.flush()
                try:
                    import traceback
                    traceback.print_exc()  # goes to stderr, which is the same as for parent process
                except Exception:
                    pass  # Ignore failures to write the traceback, since GUI processes on windows have no stderr
            else:
                eintr_retry_call(print, b'OK', file=sys.stdout)
                sys.stdout.flush()

    def delegate_recycle(path):
        if '\n' in path:
            raise ValueError('Cannot recycle paths that have newlines in them (%r)' % path)
        with rlock:
            start_recycler()
            eintr_retry_call(print, path.encode('utf-8'), file=recycler.stdin)
            recycler.stdin.flush()
            # Theoretically this could be made non-blocking using a
            # thread+queue, however the original implementation was blocking,
            # so I am leaving it as blocking.
            result = eintr_retry_call(recycler.stdout.readline)
            if result.rstrip() != b'OK':
                raise RuntimeError('recycler failed to recycle: %r' % path)

    def recycle(path):
        # We have to run the delete to recycle bin in a separate process as the
        # morons who wrote SHFileOperation designed it to spin the event loop
        # even when no UI is created. And there is no other way to send files
        # to the recycle bin on windows. Le Sigh. So we do it in a worker
        # process. Unfortunately, if the worker process exits immediately after
        # deleting to recycle bin, winblows does not update the recycle bin
        # icon. Le Double Sigh. So we use a long lived worker process, that is
        # started on first recycle, and sticks around to handle subsequent
        # recycles.
        if isinstance(path, bytes):
            path = path.decode(filesystem_encoding)
        path = os.path.abspath(path)  # Windows does not like recycling relative paths
        return delegate_recycle(path)

elif isosx:
    u = plugins['usbobserver'][0]
    if hasattr(u, 'send2trash'):
        def osx_recycle(path):
            if isbytestring(path):
                path = path.decode(filesystem_encoding)
            u.send2trash(path)
        recycle = osx_recycle
elif islinux:
    from calibre.utils.linux_trash import send2trash

    def fdo_recycle(path):
        if isbytestring(path):
            path = path.decode(filesystem_encoding)
        path = os.path.abspath(path)
        send2trash(path)
    recycle = fdo_recycle

can_recycle = callable(recycle)


def nuke_recycle():
    global can_recycle
    can_recycle = False


def restore_recyle():
    global can_recycle
    can_recycle = callable(recycle)


def delete_file(path, permanent=False):
    if not permanent and can_recycle:
        try:
            recycle(path)
            return
        except:
            import traceback
            traceback.print_exc()
    os.remove(path)


def delete_tree(path, permanent=False):
    if permanent:
        try:
            # For completely mysterious reasons, sometimes a file is left open
            # leading to access errors. If we get an exception, wait and hope
            # that whatever has the file (Antivirus, DropBox?) lets go of it.
            shutil.rmtree(path)
        except:
            import traceback
            traceback.print_exc()
            time.sleep(1)
            shutil.rmtree(path)
    else:
        if can_recycle:
            try:
                recycle(path)
                return
            except:
                import traceback
                traceback.print_exc()
        delete_tree(path, permanent=True)

