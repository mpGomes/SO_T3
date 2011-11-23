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
class NotAnInodeBlock( Exception ):
    pass
class NoFreeBlocks( Exception ):
    pass

class SofsBlock:
    def __init__( self, sofs, index, BLOCK_SIZE=512, INT_SIZE=4):
        if hasattr(sofs, "zero_block"):
            if index>= sofs.zero_block.block_count or index<0:
                raise BlockOutOfFS()
        self.BLOCK_SIZE, self.INT_SIZE= BLOCK_SIZE, INT_SIZE
        self.TOTAL_INTS= self.BLOCK_SIZE / self.INT_SIZE
        self.sofs= sofs
        self.index= index

    def _writeBytes( self, index, b):
        assert index < self.BLOCK_SIZE
        self.sofs.writeBytes( self.index*self.BLOCK_SIZE + index, b)
    
    def _readBytes( self, index, size ):
        assert index < self.BLOCK_SIZE
        return self.sofs._readBytes( self.index*self.BLOCK_SIZE + index, size)

    def writeInt(self, int_index, the_int):
        to_write= struct.pack('<i', the_int)
        assert len(to_write)==self.INT_SIZE
        self._writeBytes( int_index*self.INT_SIZE, to_write)
    
    def readInt(self,  int_index):
        int_bytes= self._readBytes( int_index*self.INT_SIZE, self.INT_SIZE )
        return struct.unpack('<i', int_bytes)[0]

    @staticmethod
    def allocateBlock(sofs):
        fb= sofs.getFreeBlock()         #get free block from head
        nfbi= fb.getNextFreeBlockIndex()#get next free block
        sofs.zero_block.setFirstFreeBlock( nfbi )   #update head
        return SofsBlock(sofs, fb.index)
    
    def deallocate(self):
        fb= self.sofs.getFirstFreeBlock()         #get current head
        self.writeInt(0, fb.index )               #update next pointer
        self.sofs.zero_block.setFirstFreeBlock( self.index ) #update head

class ZeroBlock( SofsBlock ):
    MAGIC_1, MAGIC_2= -1700156774, 1834985411 # signed ints for 0x9aa9aa9a, 0x6d5fa7c3
    START_OF_INODES_INDEXES= 5
    def __init__( self, sofs ):
        SofsBlock.__init__(self, sofs, 0) #block number 0
        magic_1, magic_2, block_size, block_count, free_list_head= map(self.readInt,range( self.START_OF_INODES_INDEXES ))
        if magic_1!=self.MAGIC_1 or magic_2!=self.MAGIC_2:
            e= IOError("Bad FS magic number")
            e.errno= errno.EINVAL
            raise e
        assert block_size==self.BLOCK_SIZE
        self.block_count= block_count   #total FS blocks
        self.free_list_head= free_list_head  #first free block
        
    def getFirstFreeBlockIndex(self):
        i= self.free_list_head
        if i==-1:
            raise NoFreeBlocks()

    def setFirstFreeBlockIndex(self, index):
        self.free_list_head= index
        self._writeInt(4, index)

    def getInodes(self):
        all_inodes_indexes= [self.readInt(i) for i in xrange(self.START_OF_INODES_INDEXES, self.TOTAL_INTS)]
        allocated_indexes=  filter(lambda x:x!=-1, all_inodes_indexes)
        inodes= map(self.sofs.getInodeBlock, allocated_indexes)
        return inodes 
    
    def writeNewInode( self, inode_block):
        all_inodes_indexes= [self.readInt(i) for i in xrange(self.START_OF_INODES_INDEXES, self.TOTAL_INTS)]
        i= all_inodes_indexes.index(-1)
        self.writeInt( i, inode_block.index)
        
    def deleteInode(self, inode_block):
        all_inodes_indexes= [self.readInt(i) for i in xrange(self.START_OF_INODES_INDEXES, self.TOTAL_INTS)]
        i= all_inodes_indexes.index( inode_block.index)
        self.writeInt( i, -1)
        
    def getBlockCount(self):
        return self.block_count

class INodeBlock( SofsBlock ):
    MAGIC= -274792711 #signed int for 0xf9fe9eef
    FILE_BLOCKS_INDEX= 18
    MAX_BLOCKS=109
    def __init__(self, sofs, index):
        SofsBlock.__init__(self, sofs, index)
        magic= self.readInt(0)
        if magic!=self.MAGIC:
            raise NotAnInodeBlock()
        self.filename=  self._readBytes( 1*INT_SIZE, 64 )
        self.filename= self.filename.split("\0")[0]
        self.size= self.readInt(17)

    @staticmethod
    def allocateInodeBlock(sofs, filename):
        if len(filename)>63:
            e= IOError()
            e.errno= errno.ENAMETOOLONG
            raise e
        b= SofsBlock.allocateBlock(sofs)
        b.writeInt(0, self.MAGIC)
        b._writeBytes( SofsFormat.INT_SIZE, filename+"\0")
        b.writeInt(17,0)
        sofs.zero_block.writeInode( b)
        return InodeBlock(sofs, b.index)

    def getFilename(self):
        return self.filename

    def getAllocatedBlocks(self):
        block_number= (self.size / self.BLOCK_SIZE) +1
        assert readInt( self.FILE_BLOCKS_INDEX + block_number)   ==-1   #just
        file_blocks_indexes= map(self.readInt, range( self.FILE_BLOCKS_INDEX, self.FILE_BLOCKS_INDEX + block_number))
        return [SofsBlock(self.sofs, i) for i in file_blocks_indexes]
        
    def readFile(self, readlen, offset):
        if offset + readlen >= self.size:
            e= OSError("Try to read outside file")
            e.errno= errno.EINVAL
            raise e
        block_to_read = offset/self.BLOCK_SIZE                 #index of the block to be read
        block_offset = offset%self.BLOCK_SIZE
        curr_block = blocks[block_to_read] #current block to be read

        blocks= self.getAllocatedBlocks()
        result = []
        while(readlen > 0):
            block_bytes = self.BLOCK_SIZE - block_offset
            bytes_to_read = min( block_bytes, readlen)
            result.append(curr_block.read_bytes(block_offset, bytes_to_read))
            readlen -= bytes_to_read
            block_to_read += 1
            block_offset = 0
            curr_block = blocks[block_to_read]
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
    
    def unlink(self):
        '''frees data blocks and inode block'''
        self.sofs.zero_block.deleteInode( self )
        for block in self.getAllocatedBlocks():
            block.deallocate()
        self.deallocate()
        

class FreeBlock( SofsBlock ):
    def __init__(self, sofs, index):
        SofsBlock.__init__(sofs, index)
    def getNextFreeBlockIndex(self):
        return self.getInt(0)
        


class SofsFormat:
    INT_SIZE=   4
    MAX_INODES= 122
    def __init__(self, filename):
        self.device= open(filename, 'rw')
        self.zero_block= ZeroBlock( self )
        
    def getBlock(self, x, index_check=True):
        if index_check:
            if x>=self.zero_block.block_count:
                raise BlockOutOfFS(str(x))
        return SofsBlock(self, x)
        
    def _writeBytes(self, index, b):
        self.device.seek(index)
        self.device.write(b)
        
    def _readBytes(self, index, size):
        self.device.seek(index)
        return self.device.read(size)

    def getInodeBlock(self, x):
        print "getting inode block"+str(x)
        index= 5+x
        return INodeBlock(self, index)
    
    def getFreeBlock(self):
        log.debug("getting free block")
        i= self.zero_block.getFirstFreeBlockIndex()
        return FreeBlock(self, i)

    def find(self, path):
        '''returns the inodeBlock of a path'''
        log.debug("executing find on "+path)
        inodes= self.zero_block.getInodes()
        for inode in inodes:
            if inode.getFilename()==path:
                log.debug("match on path of inode "+str(inode))
                return inode
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
        filenames= [".",".."]
        filenames.append( [i.filename for i in self.format.zero_block.getInodes()] )
        for fn in filenames:
            yield fuse.Direntry( fn )

    def create(self, path, flags, mode):
        INodeBlock.allocateInodeBlock(self.format, path)
        
    

if __name__ == '__main__':
    fs = SoFS()
    fs.parser.add_option(mountopt="device", metavar="DEVICE", help="device file")
    tmp= fs.parse(values=fs, errex=1)
    fs.format= SofsFormat( fs.device )
    fs.main()
