#!/usr/bin/env python
# -*- coding: utf-8 -*-
import errno
import fuse
import stat
import time
import struct
import os

fuse.fuse_python_api = (0, 2)

class SofsBlock:
    def __init__( self, sofs, index, BLOCK_SIZE=512, INT_SIZE=4):
        self.BLOCK_SIZE, self.INT_SIZE= BLOCK_SIZE, INT_SIZE
        self.sofs= sofs_format
        self.index= index

    def _writeBytes( self, index, b):
        assert index < self.BLOCK_SIZE
        self.sofs.writeBytes( self.index*self.BLOCK_SIZE + index, b)
    
    def _readBytes( self, index, size ):
        assert index < self.BLOCK_SIZE
        return self.sofs.readBytes( self.index*self.BLOCK_SIZE + index, size)

    def writeInt(self, int_index, the_int):
        to_write= struct.pack('<i', the_int)
        assert len(to_write)==self.INT_SIZE
        self.writeBytes( int_index*self.INT_SIZE, to_write)
    
    def readInt(self,  int_index):
        int_bytes= self.readBytes( int_index*self.INT_SIZE, INT_SIZE )
        return struct.unpack('<i', int_bytes)

class ZeroBlock( SofsBlock ):
    MAGIC_1, MAGIC_2= 0x9aa9aa9a, 0x6d5fa7c3
    def __init__( self, sofs ):
        SofsBlock.__init__(self, 0) #block number 0
        magic_1, magic_2, block_size, block_count, free_list_head= map(self.readInt,range(5))]
        if magic_1!=MAGIC_1 or magic_2!=MAGIC_2:
            raise IOException("Bad FS magic number")
        assert block_size==BLOCK_SIZE
        self.block_count= block_count   #total FS blocks
        self.free_list_head= free_list_head  #first free block

    def getBlockCount(self):
        return self.block_count

class INodeBlock( SoftBlock ):
    MAGIC= 0xf9fe9eef
    FILE_BLOCKS_INDEX= 18
    def __init__(self, sofs, index):
        SofsBlock.__init__(self, sofs, index)
        magic, self.readInt(0)
        if magic==-MAGIC:
            raise IOException("Bad INodeBlock magic")
        self.filename=  self._readBytes( 1*INT_SIZE, 64 )
        self.filename= self.filename.split("\0")[0]
        self.size= self.readInt(17)

    def readFile():
        block_number= (self.size / self.BLOCK_SIZE) +1
        assert readInt( self.FILE_BLOCKS_INDEX + block_number)   ==-1   #just
        file_blocks= map(self.readInt, range( self.FILE_BLOCKS_INDEX, self.FILE_BLOCKS_INDEX + block_number))
        #TODO

class FileDescriptor:
    def __init__(self, inode_block, mode):
        self.allow_read, self.allow_write= False, False
        self.seek_position=0
        #check if file exists, or raise exception
        if mode & os.O_RDONLY == os.O_RDONLY:
            self.allow_read= True
        if mode & os.O_WRONLY == os.O_WRONLY:
            self.allow_write= True
        if mode & os.APPEND == os.APPEND:
            #self.seek_position= end of file...
            pass
    
        
        
        
        
class SofsFormat:
    INT_SIZE=   4
    def __init__(self, filename):
        self.device= open(filename, rw)
        self.zero_block= ZeroBlock( self )
        
    def getBlock(x, index_check=True):
        if index_check:
            if x>=self.zero_block.block_count:
                raise IOException("getBlockIndex on a out of bounds index")
        return SofsBlock(self, x)
        
    def _writeBytes(index, b):
        self.device.seek(index)
        self.device.write(b)
        
    def _readBytes(index, size):
        self.device.seek(index)
        return self.device.read(size)

class SofsState(SofsFormat):
    def __init__(self, filename):
        SofsFormat.__init__(self, filename)
        self.open_files=[]


class MyFS(fuse.Fuse):
    def __init__(self, filename, *args, **kw):
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
