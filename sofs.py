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
                raise BlockOutOfFS(str(index))
        self.BLOCK_SIZE, self.INT_SIZE= BLOCK_SIZE, INT_SIZE
        self.TOTAL_INTS= self.BLOCK_SIZE / self.INT_SIZE
        self.sofs= sofs
        self.index= index

    def _writeBytes( self, index, b):
        assert index < self.BLOCK_SIZE
        log.debug("block: writing bytes on index {0}: {1}".format(index, b))
        self.sofs._writeBytes( self.index*self.BLOCK_SIZE + index, b)
    
    def _readBytes( self, index, size ):
        assert index < self.BLOCK_SIZE
        #log.debug("block: reading {0} bytes from index {1}".format(size, index))
        return self.sofs._readBytes( self.index*self.BLOCK_SIZE + index, size)

    def writeInt(self, int_index, the_int):
        log.debug("writing int {0} to offset {1}".format(the_int, int_index))
        to_write= struct.pack('<i', the_int)
        assert len(to_write)==self.INT_SIZE
        self._writeBytes( int_index*self.INT_SIZE, to_write)
    
    def readInt(self,  int_index):
        int_bytes= self._readBytes( int_index*self.INT_SIZE, self.INT_SIZE )
        the_int= struct.unpack('<i', int_bytes)[0]
        #log.debug("read int {0} from offset {1}".format(the_int, int_index))
        return the_int
        
    @staticmethod
    def allocateBlock(sofs):
        fb= sofs.getFreeBlock()         #get free block from head
        nfbi= fb.getNextFreeBlockIndex()#get next free block
        sofs.zero_block.setFirstFreeBlockIndex( nfbi )   #update head
        log.debug("allocated block "+str(nfbi))
        return SofsBlock(sofs, fb.index)
    
    def deallocate(self):
        log.debug("deallocating block "+str(self.index))
        try:
            fb= self.sofs.getFreeBlock()         #get current head
            next_free_index = fb.index
        except NoFreeBlocks:
            next_free_index= -1
        self.writeInt(0, next_free_index )               #update next pointer
        self.sofs.zero_block.setFirstFreeBlockIndex( self.index ) #update head

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
        return i

    def setFirstFreeBlockIndex(self, index):
        self.free_list_head= index
        self.writeInt(4, index)

    def getInodes(self):
        all_inodes_indexes= [self.readInt(i) for i in xrange(self.START_OF_INODES_INDEXES, self.TOTAL_INTS)]
        allocated_indexes=  filter(lambda x:x!=-1, all_inodes_indexes)
        inodes= map(self.sofs.getInodeBlock, allocated_indexes)
        return inodes 
    
    def writeNewInode( self, inode_block):
        all_inodes_indexes= [self.readInt(i) for i in xrange(self.START_OF_INODES_INDEXES, self.TOTAL_INTS)]
        i= self.START_OF_INODES_INDEXES + all_inodes_indexes.index(-1)
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
        self.filename=  self._readBytes( 1*self.INT_SIZE, 64 )
        self.filename= self.filename.split("\0")[0]
        self.size= self.readInt(17)

    def getFilename(self):
        return self.filename

    def setFilename(self, filename):
        if len(filename)>63:
            e= IOError()
            e.errno= errno.ENAMETOOLONG
            raise e
        self._writeBytes( SofsFormat.INT_SIZE, filename+"\0")
        self.filename= filename

    def getSize(self):
        return self.size

    def setSize(self, newsize):
        log.debug("setSize to "+str(newsize))
        if newsize > self.BLOCK_SIZE * self.MAX_BLOCKS:
            e= IOError()
            e.errno= errno.EFBIG
            raise e
        currently_allocated= self.needed_blocks( self.getSize() )
        needed_allocated=   self.needed_blocks( newsize )
        while needed_allocated > currently_allocated:
            #allocated a block
            try:
                newblock= SofsBlock.allocateBlock(self.sofs)
            except NoFreeBlocks:
                self.setSize( self.size )    #reset to original size, before setSize
                raise NoFreeBlocks
            i= self.FILE_BLOCKS_INDEX + currently_allocated
            self.writeInt( i, newblock.index)
            currently_allocated+=1
        while needed_allocated < currently_allocated:
            #deallocate a block
            i= self.FILE_BLOCKS_INDEX + currently_allocated -1  #last block
            block_index= self.readInt(i)
            block= self.sofs.getBlock( block_index )
            block.deallocate()
            self.writeInt( i, -1)
            currently_allocated-=1
        self.writeInt(17, newsize)
        self.size= newsize

    @staticmethod
    def allocateInodeBlock(sofs, filename):
        b= SofsBlock.allocateBlock(sofs)
        b.writeInt(0, INodeBlock.MAGIC)
        sofs.zero_block.writeNewInode( b)
        inode = INodeBlock(sofs, b.index)
        inode.setFilename(filename)
        inode.setSize(0)
        for i in xrange(inode.FILE_BLOCKS_INDEX, inode.TOTAL_INTS):
            #write pointers to blocks of file
            inode.writeInt(i, -1)
        return inode

    def needed_blocks( self, filesize ):
        '''returns the number of FS blocks to contain a file of filesize'''
        return ((filesize-1) / self.BLOCK_SIZE)+1

    def getAllocatedBlocks(self):
        block_number= self.needed_blocks( self.size )
        file_blocks_indexes= map(self.readInt, range( self.FILE_BLOCKS_INDEX, self.FILE_BLOCKS_INDEX + block_number))
        assert self.readInt( self.FILE_BLOCKS_INDEX + block_number)   ==-1   #just
        assert all( [x>=0 for x in file_blocks_indexes] )
        return [SofsBlock(self.sofs, i) for i in file_blocks_indexes]
        
    def readFile(self, readlen, offset):
        if offset + readlen > self.size:
            readlen= self.getSize() - offset
        if readlen==0:
            return ""   #to avoid index error
        blocks= self.getAllocatedBlocks()
        block_to_read = offset/self.BLOCK_SIZE              #index of the block to be read
        block_offset = offset%self.BLOCK_SIZE
        result = []
        while(readlen > 0):
            curr_block = blocks[block_to_read]                  #current block to be read
            block_bytes = self.BLOCK_SIZE - block_offset
            bytes_to_read = min( block_bytes, readlen)
            result.append(curr_block._readBytes(block_offset, bytes_to_read))
            readlen -= bytes_to_read
            block_to_read += 1
            block_offset = 0
        return "".join(result)

    def writeFile(self, buf, offset):
        if offset + len(buf) > self.size:     
            self.setSize(offset + len(buf))
        blocks= self.getAllocatedBlocks()
        block_to_write = offset/self.BLOCK_SIZE                 #index of the block to be written
        block_offset = offset%self.BLOCK_SIZE
        remaining_bytes=len(buf)
        reading_index = 0
        while (remaining_bytes > 0):
            curr_block = blocks[block_to_write] #current block
            block_bytes = self.BLOCK_SIZE - block_offset
            num_bytes_to_write = min( block_bytes, remaining_bytes)
            curr_block._writeBytes(block_offset, buf[reading_index:reading_index+num_bytes_to_write])
            reading_index+=num_bytes_to_write
            block_to_write += 1                                      #get next block to write
            block_offset = 0
            remaining_bytes -= num_bytes_to_write
    
    def unlink(self):
        '''frees data blocks and inode block'''
        self.sofs.zero_block.deleteInode( self )
        for block in self.getAllocatedBlocks():
            block.deallocate()
        self.deallocate()
        

class FreeBlock( SofsBlock ):
    def __init__(self, sofs, index):
        SofsBlock.__init__(self, sofs, index)
    def getNextFreeBlockIndex(self):
        return self.readInt(0)
        


class SofsFormat:
    INT_SIZE=   4
    MAX_INODES= 122
    def __init__(self, filename):
        self.device= open(filename, 'r+')   #read-write
        self.zero_block= ZeroBlock( self )
        
    def getBlock(self, x):
        return SofsBlock(self, x)
        
    def _writeBytes(self, index, b):
        log.debug("write bytes to offset {0}: {1}".format(index, b))
        self.device.seek(index)
        self.device.write(b)
        
    def _readBytes(self, index, size):
        #log.debug("reading {0} bytes from offset {1}".format(size, index))
        self.device.seek(index)
        return self.device.read(size)

    def getInodeBlock(self, index):
        log.debug("getting inode block "+str(index))
        return INodeBlock(self, index)
    
    def getFreeBlock(self):
        log.debug("getting free block")
        i= self.zero_block.getFirstFreeBlockIndex()
        log.debug("returning block "+str(i))
        return FreeBlock(self, i)

    def find(self, path):
        '''returns the inodeBlock of a path'''
        log.debug("executing find on "+path)
        inodes= self.zero_block.getInodes()
        filename = os.path.basename(path)
        for inode in inodes:
            if inode.getFilename()==filename:
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
        st.st_mode = 0755 | stat.S_IFREG
        st.st_nlink = 1
        st.st_atime = 0.0
        st.st_mtime = 0.0
        st.st_ctime = 0.0

        if os.path.abspath(path)=="/":
            st.st_mode = 0755 | stat.S_IFDIR
            return st
        try:
            inode= self.format.find(path)
            st.st_size= inode.getSize()
            st.st_blksize= 512
            st.st_blocks=inode.needed_blocks( inode.getSize() )
            return st
        except CantFindInodeFromPath:
            e= OSError("Couldn't find the given path")
            e.errno= errno.ENOENT
            raise e
    
    def write(self, path, buf, offset):
        log.debug("called write {0} {1} {2}".format(path, buf, offset))
        f = self.format.find(path)
        try:
            f.writeFile(buf, offset)
        except NoFreeBlocks:
            e=IOError("Couldn't find the given path")
            e.errno= errno.ENOSPC
            raise e
        return len(buf)
    
    def read(self, path, length, offset):
        log.debug("called read {0} {1} {2}".format(path, length, offset))
        f = self.format.find(path)
        buf = f.readFile(length,offset)
        return buf
    
    def open( self, path, flags ):
        log.debug("called open {0} {1}".format(path, flags))
        return 0
    
    def flush(self, path):
        log.debug("called close {0}".format(path))
        return 0
        
    def release(self, path, flags):
        log.debug("called close {0} {1}".format(path, flags))
        return 0

    def readdir(self, path, offset):
        log.debug("called readdir {0} {1}".format(path, offset))
        filenames= [".",".."]
        filenames.extend( [i.filename for i in self.format.zero_block.getInodes()] )
        for fn in filenames:
            yield fuse.Direntry( fn )

    def create(self, path, flags, mode):
        log.debug("called create "+path)
        filename = os.path.basename(path)
        try:
            INodeBlock.allocateInodeBlock(self.format, filename)
        except NoFreeBlocks:
            e=IOError("Couldn't find the given path")
            e.errno= errno.ENOSPC
            raise e
        
    def rename(self, pathfrom, pathto):
        inode= self.format.find(os.path.basename(pathfrom))
        inode.setFilename(os.path.basename(pathto))


    def utime ( self, path, times ):
        pass # can't do anything, since we don't have data structures for times on disk

    def unlink ( self, path ):
        log.debug("called unlink "+path)
        inode= self.format.find(path)
        inode.unlink()

    def chmod ( self, path, mode ):
        pass    #can't do without data structures

    def chown ( self, path, uid, gid ):
        pass    #can't do without data structures

    def fsync ( self, path, isFsyncFile ):
        pass    #no need, for now

    def truncate ( self, path, size ):
        log.debug("called truncate {0} {1}".format(path, size))
        inode = self.format.find(path)
        inode.setSize(size)
        
if __name__ == '__main__':
    fs = SoFS()
    fs.parser.add_option(mountopt="device", metavar="DEVICE", help="device file")
    tmp= fs.parse(values=fs, errex=1)
    fs.format= SofsFormat( fs.device )
    fs.main()
