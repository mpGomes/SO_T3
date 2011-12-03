import sys, os

class TestFile():
    def __init__(self, filename):
        self.filename = filename
        self.seek = 0
        self.content = ""
        
class Test():
    def __init__(self, filenm):
        self.filenm = filenm
        self.test = self.getTest(filenm)        
        self.fs_files  = dict()         #keeps the disk state in memory
        self.open_files = dict()        #saves de file descriptors for disk i/o
 
    def datack(self):
        for f in self.fs_files.values():
            self.fs_file = open(f.filename, 'r')
            fsf_content = self.fs_file.read() 
            assert f.content == fsf_content
                
    def getTest(self, filename):
        f = open('../tests/'+filename, 'r')
        test_str = f.read()
        instructions = test_str.split('\n')[:-1]
        test = [instruction.split(' ') for instruction in instructions]
        #split to tuple form (name, arg1,..., argn)
        return test

    def run_test(self):
        for instruction in self.test:
            if instruction[0] == "open":
                self.openFile(instruction[1])
            elif instruction[0] == "close":
                self.closeFile(instruction[1])
            elif instruction[0] == "read":
                self.readFile(instruction[1])
            elif instruction[0] == "write":
                self.writeFile(instruction[1], instruction[2])
            elif instruction[0] == "seek":
                self.seekFile(instruction[1], instruction[2])
            elif instruction[0] == "delete":
                self.deleteFile(instruction[1])
            else:
                raise Exception("Unvalid test instruction :"+str(instruction[0]))
        
    def openFile(self, filename):
        f = open(filename, 'w+')
        if not filename in self.fs_files:
            self.fs_files[filename] = TestFile(filename)
        if not filename in self.open_files:
            self.open_files[filename] = f
            
    def readFile(self, filename):
        f = self.fs_files[filename]
        seek = f.seek
        buf = f.content[seek:]
        f.seek = len(f.content)
        fd = self.open_files[filename]
        real_buf = fd.read()
        assert buf == real_buf
        return buf
        
    def seekFile(self, filename, seek):
        f = self.fs_files[filename]
        f.seek = seek
        fd = self.open_files(filename)
        fd.seek(seek)
        
    def writeFile(self, filename, content):
        f = self.fs_files[filename]
        seek = f.seek
        f.content = f.content[0:seek]+ str(content)
        f.seek = len(f.content)
        fd = self.open_files[filename]
        fd.write(content)
        
    def deleteFile(self, filename):
        del self.fs_files[filename]
        os.remove(filename)
        
    def closeFile(self, filename):
        f = self.fs_files[filename]
        f.seek = 0
        self.open_files[filename].close()
        del self.open_files[filename]

os.chdir('mountpoint')
testfile_name = sys.argv[1]
test = Test(testfile_name)
test.run_test()
test.datack()
print "Test Passed!"
