#!/usr/bin/env python
# -*- coding: utf-8 -*-
import errno
import fuse
import stat
import time
import struct
import os

import logging
log= logging.getLogger('sofs')
formatter = logging.Formatter('%(asctime)s\t%(levelname)s\t%(name)s\t%(module)s\t%(funcName)s\t%(message)s')
hdlr = logging.FileHandler('sofs.log.tsv', mode="w")
hdlr.setFormatter(formatter)
log.addHandler(hdlr) 
log.setLevel(logging.DEBUG)

fuse.fuse_python_api = (0, 2)

class BlockOutOfFS( Exception ):
    pass

class CantFindInodeFromPath( Exception ):
    pass

class SofsBlock:
    def __init__( self, sofs, index, BLOCK_SIZE=512, INT_SIZE=4):
        self.BLOCK_SIZE, self.INT_SIZE= BLOCK_SIZE, INT_SIZE
        self.sofs= sofs
        self.index= index

    def _writeBytes( self, index, b):
        assert index < self.BLOCK_SIZE
        self.sofs.writeBytes( self.index*self.BLOCK_SIZE + index, b)
    
    def _readBytes( self, index, size ):
        assert index < self.BLOCK_SIZE
        return self.sofs._readBytes( self.index*self.BLOCK_SIZE + index, size)

    def writeInt(self, int_index, the_int):
        to_write= struct.pack('<I', the_int)
        assert len(to_write)==self.INT_SIZE
        self._writeBytes( int_index*self.INT_SIZE, to_write)
    
    def readInt(self,  int_index):
        int_bytes= self._readBytes( int_index*self.INT_SIZE, self.INT_SIZE )
        return struct.unpack('<I', int_bytes)[0]

class ZeroBlock( SofsBlock ):
    MAGIC_1, MAGIC_2= 0x9aa9aa9a, 0x6d5fa7c3
    def __init__( self, sofs ):
        SofsBlock.__init__(self, sofs, 0) #block number 0
        magic_1, magic_2, block_size, block_count, free_list_head= map(self.readInt,range(5))
        if magic_1!=self.MAGIC_1 or magic_2!=self.MAGIC_2:
            e= IOError("Bad FS magic number")
            e.errno= errno.EINVAL
            raise e
        assert block_size==self.BLOCK_SIZE
        self.block_count= block_count   #total FS blocks
        self.free_list_head= free_list_head  #first free block

    def getBlockCount(self):
        return self.block_count

class INodeBlock( SofsBlock ):
    MAGIC= 0xf9fe9eef
    FILE_BLOCKS_INDEX= 18
    MAX_BLOCKS=109
    def __init__(self, sofs, index):
        SofsBlock.__init__(self, sofs, index)
        magic= self.readInt(0)
        if magic!=self.MAGIC:
            e= OSError("Bad INodeBlock magic")
            e.errno= errno.EINVAL
            raise e
        self.filename=  self._readBytes( 1*INT_SIZE, 64 )
        self.filename= self.filename.split("\0")[0]
        self.size= self.readInt(17)

    def getFilename(self):
        return self.filename

    def readFile(self, readlen, offset):
        block_number= (self.size / self.BLOCK_SIZE) +1
        assert readInt( self.FILE_BLOCKS_INDEX + block_number)   ==-1   #just
        file_blocks= map(self.readInt, range( self.FILE_BLOCKS_INDEX, self.FILE_BLOCKS_INDEX + block_number))
        
        if offset + readlen >= self.size:
            e= OSError("Try to read outside file")
            e.errno= errno.EINVAL
            raise e
        
        block_to_read = offset/self.BLOCK_SIZE                 #index of the block to be read
        block_offset = offset%self.BLOCK_SIZE
        
        curr_block = sofs.getBlock(file_blocks[block_to_read]) #current block to be read
        
        result = []
        while(readlen > 0):
            block_bytes = self.BLOCK_SIZE - block_offset
            bytes_to_read = min( block_bytes, readlen)
            result.append(curr_block.read_bytes(block_offset, bytes_to_read))
            readlen -= bytes_to_read
            block_to_read += 1
            block_offset = 0
            curr_block = sofs.getBlock(file_blocks[block_to_read])
        
        return "".join(result)

    def writeFile(self, writelen, offset):

        if offset > self.size or offset + writelen > self.MAX_BLOCKS*self.BLOCK_SIZE:     
            raise IOError()

        block_number= (self.size / self.BLOCK_SIZE) +1
        assert readInt( self.FILE_BLOCKS_INDEX + block_number)   ==-1   #just
        file_blocks= map(self.readInt, range( self.FILE_BLOCKS_INDEX, self.FILE_BLOCKS_INDEX + block_number))
        
        block_to_write = offset/self.BLOCK_SIZE                 #index of the block to be written
        block_offset = offset%self.BLOCK_SIZE

        curr_block = sofs.getBlock(file_blocks[block_to_read]) #current block

        while (writelen > 0):
            block_bytes = self.BLOCK_SIZE - block_offset
            bytes_to_write = min( block_bytes, writelen)
            curr_block.write_bytes(block_offset, bytes_to_write)
            block_to_read += 1                                      #get next block to write
            curr_block = sofs.getBlock(file_blocks[block_to_read])
            block_offset = 0
            writelen -= bytes_to_write
            
        if offset + writelen == self.size:
            self.size = offset + writelen       #update file size

        return 0 #what to return?
        
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
    MAX_INODES= 122
    def __init__(self, filename):
        self.device= open(filename, 'rw')
        self.zero_block= ZeroBlock( self )
        
    def getBlock(self, x, index_check=True):
        if index_check:
            if x>=self.zero_block.block_count:
                raise BlockOutOfFS()
        return SofsBlock(self, x)
        
    def _writeBytes(self, index, b):
        self.device.seek(index)
        self.device.write(b)
        
    def _readBytes(self, index, size):
        self.device.seek(index)
        return self.device.read(size)

    def getInodeBlock(self, x):
        index= 5+x
        if index>=self.zero_block.block_count:
            raise BlockOutOfFS()
        return INodeBlock(self, index)

    def find(self, path):
        '''returns the inodeBlock of a path'''
        log.debug("finding path "+path)
        inode=0
        while inode < self.MAX_INODES:
            try:
                block= self.getInodeBlock( inode )
                if block.getFilename()==path:
                    return block
            except BlockOutOfFS:
                break   
        log.error("could not find path "+path)
        raise CantFindInodeFromPath()



class SoFS(fuse.Fuse):
    def __init__(self, *args, **kw):
        fuse.Fuse.__init__(self, *args, **kw)
        self.device= None   #device path, will be set outside
        self.format= None   #SofsFormat,  will be set outside

    def getattr(self, path):
        log.debug("called getattr {0}".format(path))
        st = fuse.Stat()
        st.st_mode = 0755 | stat.S_IFDIR
        st.st_nlink = 1
        st.st_atime = 0.0
        st.st_mtime = 0.0
        st.st_ctime = 0.0

        if os.path.abspath(path)=="/":
                return st

        try:
            inode= self.format.find(path)
            return st
        except CantFindInodeFromPath:
            e= OSError("Couldn't find the given path")
            e.errno= errno.ENOENT
            raise e
    
    def write(self, buf, offset):
        log.debug("called write {0} {1}".format(buf, offset))
    
    def read(self, size, offset):
        log.debug("called read {0} {1}".format(size, offset))
    
    def open( self, path, flags ):
        log.debug("called open {0} {1}".format(path, flags))

    def readdir(self, path, offset):
        log.debug("called getdir {0} {1}".format(path, offset))
        for e in ["inexistent.file"]:
            yield fuse.Direntry(e)
    

if __name__ == '__main__':
    fs = SoFS()
    fs.parser.add_option(mountopt="device", metavar="DEVICE", help="device file")
    tmp= fs.parse(values=fs, errex=1)
    fs.format= SofsFormat( fs.device )
    fs.main()
