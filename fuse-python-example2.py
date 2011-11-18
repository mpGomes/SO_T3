#!/usr/bin/env python
# -*- coding: utf-8 -*-
import errno
import fuse
import stat
import time

fuse.fuse_python_api = (0, 2)

class MyFS(fuse.Fuse):
    def __init__(self, *args, **kw):
        fuse.Fuse.__init__(self, *args, **kw)

    def getattr(self, path):
        st = fuse.Stat()
        st.st_mode = stat.S_IFDIR | 0755
        st.st_nlink = 2
        st.st_atime = int(time.time())
        st.st_mtime = st.st_atime
        st.st_ctime = st.st_atime

        if path == '/':
            pass
        else:
            return - errno.ENOENT
        return st

if __name__ == '__main__':
    fs = MyFS()
    fs.parse(errex=1)
    fs.main()
