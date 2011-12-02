import sys, os, random, string

class Test():
    def __init__(self, name, runtest):
        self.name = name
        self.runtest = runtest

def filenameTest():
    print "Will try naming files until 100 characters length"
    filename_len=1
    for i in range(1,100):
        filename = "a"*i
        try:
            fsfile = open('mountpoint/'+filename, 'w')
            fsfile.close()
            os.remove('mountpoint/'+filename)
        except (IOError):
            filename_len = i-1
            break
    if filename_len != 63:
        raise Exception("Diferent filename length from what's expected : "+str(filename_len))
    assert filename_len == 63

def maxInodesTest():
    print "Will try to create 200 files"
    number_of_files=0
    for i in range(1,200):
        filename = ''.join(random.choice(string.ascii_uppercase) for x in range(10))
        try:
            f= open('mountpoint/'+filename, 'w')
            f.close()
        except(IOError):
            number_of_files=i-1
            break
    if number_of_files != 123:
        raise Exception("Number of files created diferent from what's expected : "+str(number_of_files))
    assert number_of_files == 123

def maxBlocksTest():
    print "Will try to create enough files to a fill the whole disk"
    number_of_files=0
    for i in range(1,300):
        filename = ''.join(random.choice(string.ascii_uppercase) for x in range(10))
        try:
            f= open('mountpoint/'+filename, 'w')
            f.write("something to fill a data block")
            f.close()
        except(IOError):
            number_of_files=i-1
            break
    if number_of_files != 99:
        raise Exception("Number of files created diferent from what's expected : "+str(number_of_files))
    assert number_of_files == 99

def maxFileSizeTest():
    print "Will try to create the largest file possible"
    data_blocks = 0
    for i in range(1,300):
        try:
            f= open('mountpoint/max_file', 'w')
            file_str = ''.join(random.choice(string.ascii_uppercase) for x in range(512))
            f.seek(i*512)
            f.write(file_str)
            f.close()
        except(IOError):
            #import pdb;pdb.set_trace()
            data_blocks-=i-1
            break
    if data_blocks != 110:
        raise Exception("Number of data blocks alocated diferent from what's expected : "+str(data_blocks))
    assert data_bloks == 110

tests = [Test('filename_test', filenameTest),Test('max_inodes_test', maxInodesTest),
         Test('max_blocks_test', maxBlocksTest),Test('max_file_size_test', maxFileSizeTest)]    

print "Choose your test"
for i,test in enumerate(tests):
    print i, test.name
    
test_index =int(raw_input())
assert test_index >= 0 and test_index < len(tests)
tests[test_index].runtest()
print "Test passed."


        
    
