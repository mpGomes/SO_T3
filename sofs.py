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

class IntTable:
    '''this class maintains a table ints on a region of a block'''
    class NotFound( Exception ):
        pass
    class Full( Exception ):
        pass
    DEFAULT_VALUE= -1 #the default table value
    def __init__(self, sofsblock, start_index, size, initialize=False):
        '''
        start_index: integer index where table starts, on block
        size: number of table entries
        initialize: write DEFAULT_VALUE on whole table
        '''
        assert isinstance( sofsblock, SofsBlock)
        self.block, self.start_index, self.size= sofsblock, start_index, size
        if initialize:
            #write the table filled with empty value
            self.writeInts(0, (self.DEFAULT_VALUE,)*size )

    def writeInt( self, index, integer):
        assert 0 <= index < self.size
        self.block.writeInt( self.start_index + index, integer)

    def writeInts( self, index, integers):
        assert 0<= index
        assert index+len(integers) <= self.size
        self.block.writeInts( self.start_index + index, integers)

    def readInt( self, index):
        assert 0 <= index < self.size
        return self.block.readInt( self.start_index + index )

    def readInts(self, index, size):
        assert 0<= index+size <= self.size
        return self.block.readInts( self.start_index + index, size)

    def readAllInts(self):
        return self.readInts(0, self.size)

    def readAllNonDefaultInts(self):
        return filter( lambda x: x!=self.DEFAULT_VALUE, self.readAllInts() )

    def index(self, value):
        '''finds the table index of the wanted value'''
        i= self.readAllInts()
        try:
            return i.index(value)
        except:
            raise BlockTable.NotFound(value)

class BlockTable( IntTable ):
    '''maintains a list of block pointers on disk'''
    def __init__(self, sofsblock, start_index, size, initialize=False, index_to_block_function=lambda x:None):
        IntTable.__init__(self, sofsblock, start_index, size, initialize=initialize)
        self.bfif= index_to_block_function

    def readBlock( self, index):
        return self.bfif( self.readInt(index) )

    def readBlocks(self, index, size):
        return map(self.bfif, self.readInts( index, size ))
    
    def writeBlock( self, index, block):
        return self.writeInt(index, block.index)
    
    def writeBlocks( self, index, blocks ):
        bi= [b.index for b in blocks]
        self.writeInt(index, bi)

    def readAllBlocks(self):
        '''returns all blocks (ignores EMPTY_VALUE)'''
        return map(self.bfif, self.readAllNonDefaultInts())

    def addBlock(self, block):
        '''writes the block on a free position, if any'''
        try:
            empty_index= self.index( self.DEFAULT_VALUE )
        except BlockTable.NotFound:
            raise self.Full()
        self.writeBlock( empty_index, block)

    def deleteBlock(self, block):
        '''deletes a specific block'''
        index= self.index( block.index )
        self.writeInt( index, self.DEFAULT_VALUE)

class LinearBlockTable( IntTable ):
    '''a BlockTable with no "empty spaces" between blocks'''
    def __init__(self, sofsblock, start_index, size, initialize=False, index_to_block_function=lambda x:None):
        IntTable.__init__(self, sofsblock, start_index, size, initialize=initialize)
        self.bfif= index_to_block_function
        
        #check that all non-empty blocks are continuous and before DEFAULT_VALUEs
        indexes= self.readAllInts()
        if self.DEFAULT_VALUE in indexes:
            i= indexes.index( self.DEFAULT_VALUE )
            empty_part= indexes[i:]
            if empty_part.count( self.DEFAULT_VALUE)!=len(empty_part):
                raise Exception( "Table is not linear")
            self.current_size=i
        else:
            self.current_size= self.size
    
    def readAllBlocks(self):
        '''returns all blocks (ignores EMPTY_VALUE)'''
        return map(self.bfif, self.readInts(0, self.current_size))

    def addBlocks(self, blocks):
        '''writes the block on a free position, if any'''
        if self.size - self.current_size < len(blocks):
            raise self.Full()
        self.writeInts( self.current_size, [b.index for b in blocks])
        self.current_size+= len(blocks)

    def deleteBlocks(self, n):
        if self.current_size < n:
            raise Exception("Trying to delete too many blocks")
        deleted_blocks= map(self.bfif, self.readInts( self.current_size-n,n))
        self.writeInts( self.current_size  - n, (self.DEFAULT_VALUE,)*n)
        self.current_size-=n
        return deleted_blocks

    def getCurrentSize(self):
        return self.current_size

class AllocatedBlockTable( LinearBlockTable ):
    '''maintains a list of pointers to self-allocated blocks'''
    def __init__(self, sofs, *args, **kwargs):
        LinearBlockTable.__init__(self, *args, **kwargs)
        self.sofs= sofs

    def resize(self, n_blocks):
        '''resizes the table to have n_blocks, allocating or deallocating as necessary'''
        diff=  n_blocks - self.current_size
        if diff < 0:
            deallocated_blocks= self.deleteBlocks( -diff )
            map( SofsBlock.deallocate, deallocated_blocks)
        if diff > 0:
            allocated_blocks= [ SofsBlock.allocateBlock(self.sofs) for x in xrange(diff) ]
            self.addBlocks( allocated_blocks )


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
        #log.debug("block: writing bytes on index {0} of block {1}: {2}".format(index, self.index, b))
        self.sofs._writeBytes( self.index*self.BLOCK_SIZE + index, b)

    def _readBytes( self, index, size ):
        assert index < self.BLOCK_SIZE
        #log.debug("block: reading {0} bytes from index {1} of block {2}".format(size, index, self.index))
        return self.sofs._readBytes( self.index*self.BLOCK_SIZE + index, size)

    def writeInt(self, int_index, the_int):
        log.debug("writing int {0} to offset {1} of block {2}".format(the_int, int_index, self.index))
        to_write= struct.pack('<i', the_int)
        assert len(to_write)==self.INT_SIZE
        self._writeBytes( int_index*self.INT_SIZE, to_write)

    def writeInts(self, int_index, ints):
        to_write= "".join( [struct.pack('<i', i) for i in ints])
        assert len(to_write)==self.INT_SIZE*len(ints)
        self._writeBytes( int_index*self.INT_SIZE, to_write)

    def readInt(self,  int_index):
        int_bytes= self._readBytes( int_index*self.INT_SIZE, self.INT_SIZE )
        the_int= struct.unpack('<i', int_bytes)[0]
        #log.debug("read int {0} from offset {1}".format(the_int, int_index))
        return the_int

    def readInts(self, int_index, size):
        def chunks(l, n):
            """ Yield successive n-sized chunks from l"""
            for i in xrange(0, len(l), n):
                yield l[i:i+n]
        ints_bytes= self._readBytes( int_index*self.INT_SIZE, self.INT_SIZE*size )
        ints= [struct.unpack('<i', ib)[0] for ib in chunks( ints_bytes,self.INT_SIZE )]
        return ints

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
    TABLE_START= 5
    def __init__( self, sofs ):
        SofsBlock.__init__(self, sofs, 0) #block number 0
        magic_1, magic_2, block_size, block_count, free_list_head= map(self.readInt,range( self.TABLE_START ))
        if magic_1!=self.MAGIC_1 or magic_2!=self.MAGIC_2:
            e= IOError("Bad FS magic number")
            e.errno= errno.EINVAL
            raise e
        assert block_size==self.BLOCK_SIZE
        self.block_count= block_count   #total FS blocks
        self.free_list_head= free_list_head  #first free block
        table_size= self.TOTAL_INTS - ZeroBlock.TABLE_START
        self.inodes= BlockTable( self, self.TABLE_START, table_size, index_to_block_function=self.sofs.getInodeBlock)
        
    def getFirstFreeBlockIndex(self):
        i= self.free_list_head
        if i==-1:
            raise NoFreeBlocks()
        return i

    def setFirstFreeBlockIndex(self, index):
        self.free_list_head= index
        self.writeInt(4, index)

    def getBlockCount(self):
        return self.block_count

class INodeBlock( SofsBlock ):
    MAGIC= -274792711 #signed int for 0xf9fe9eef
    DATA_TABLE_START= 18
    DATA_TABLE_SIZE=  100
    MAX_FILE_SIZE= 512 * DATA_TABLE_SIZE
    def __init__(self, sofs, index):
        SofsBlock.__init__(self, sofs, index)
        magic= self.readInt(0)
        if magic!=self.MAGIC:
            raise NotAnInodeBlock()
        self.filename=  self._readBytes( 1*self.INT_SIZE, 64 )
        self.filename= self.filename.split("\0")[0]
        self.size= self.readInt(17)
        self.data_blocks= AllocatedBlockTable( self.sofs, self, self.DATA_TABLE_START, self.DATA_TABLE_SIZE, index_to_block_function=self.sofs.getBlock)

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
        if newsize > self.MAX_FILE_SIZE:
            e= IOError()
            e.errno= errno.EFBIG
            raise e
        self.data_blocks.resize( self.needed_blocks(newsize) )
        self.writeInt(17, newsize)
        self.size= newsize

    @staticmethod
    def allocateInodeBlock(sofs, filename):
        b= SofsBlock.allocateBlock(sofs)
        b.writeInt(0, INodeBlock.MAGIC)
        sofs.zero_block.inodes.addBlock( b)
        inode = INodeBlock(sofs, b.index)
        inode.setFilename(filename)
        inode.writeInt(17, 0)   #size
        BlockTable( inode, INodeBlock.DATA_TABLE_START, INodeBlock.DATA_TABLE_SIZE, initialize=True)    #write empty data_blocks table
        return inode

    def needed_blocks( self, filesize ):
        '''returns the number of FS blocks to contain a file of filesize'''
        return ((filesize-1) / self.BLOCK_SIZE)+1

    def readFile(self, readlen, offset):
        if offset + readlen > self.size:
            readlen= self.getSize() - offset
        if readlen==0:
            return ""   #to avoid index error
        blocks= self.data_blocks.readAllBlocks()
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
        blocks= self.data_blocks.readAllBlocks()
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
        self.sofs.zero_block.inodes.deleteBlock( self )
        for block in self.data_blocks.readAllBlocks():
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
        #log.debug("write bytes to offset {0}: {1}".format(index, b))
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
        inodes= self.zero_block.inodes.readAllBlocks()
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
        filenames.extend( [i.filename for i in self.format.zero_block.inodes.readAllBlocks()] )
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
    fs.multithreaded = 0
    fs.parser.add_option(mountopt="device", metavar="DEVICE", help="device file")
    tmp= fs.parse(values=fs, errex=1)
    fs.format= SofsFormat( fs.device )
    fs.main()
